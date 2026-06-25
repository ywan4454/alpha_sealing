import akshare as ak
import pandas as pd
import numpy as np
import os
import glob
import time
import requests
import warnings
import matplotlib.pyplot as plt
from datetime import datetime, timedelta
from matplotlib import gridspec
from sklearn.ensemble import RandomForestClassifier
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import roc_curve, auc, accuracy_score, classification_report
from sklearn.model_selection import TimeSeriesSplit, cross_val_score
from bayes_opt import BayesianOptimization
from scipy.stats import ttest_rel
from decimal import Decimal, ROUND_HALF_UP


warnings.filterwarnings('ignore')

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))

# ==================== [3. Market Monitoring: Resumptions & Events] ====================
def get_event_driven_pool(t_date_str, target_trade_date_str):
    from datetime import datetime, timedelta
    import pandas as pd
    import akshare as ak
    
    events_list = []
    cols = ["Ticker", "Name", "Event_Type", "Keyword", "Description", "Date"]
    
    keyword_map = {
        '业绩预增': '业绩预增', 
        '战略投资': '资本运作', '入股': '资本运作',
        '溢价': '资本运作', '受让': '资本运作', 
        '协议转让': '资本运作','投资协议': '资本运作',
        '控制权': '控制权变更', 
        '重组': '重组并购', '吸收合并': '重组并购', '购买资产': '重组并购'
    }

    # =========================================================
    # 核心修正 1：精准计算扫描日期区间 (T+1日 到 Target日)
    # 盘中运行(如周四)：只扫周四的公告。
    # 周末运行(如周日)：扫周六、周日、周一的公告，完美避开多余历史。
    # =========================================================
    start_dt = datetime.strptime(t_date_str, "%Y%m%d") + timedelta(days=1)
    end_dt = datetime.strptime(target_trade_date_str, "%Y%m%d")
    
    scan_dates = []
    curr_dt = start_dt
    while curr_dt <= end_dt:
        scan_dates.append(curr_dt.strftime("%Y%m%d"))
        curr_dt += timedelta(days=1)
        
    # 如果逻辑反转兜底
    if not scan_dates:
        scan_dates = [target_trade_date_str]

    all_notices_list = []

    # ==========================================
    # 1. 扫描重要公告
    # ==========================================
    for d in scan_dates:
        try:
            df_notice = ak.stock_notice_report(symbol="全部", date=d)
            if df_notice is not None and not df_notice.empty:
                df_notice['code_str'] = df_notice['代码'].astype(str).str.zfill(6)
                
                # 核心修正 2：过滤可转债，仅保留 A股 (00, 30, 60, 68开头)
                df_notice = df_notice[df_notice['code_str'].str.startswith(('00', '30', '60', '68'))]
                all_notices_list.append(df_notice)
        except Exception:
            continue

    if all_notices_list:
        master_notice_df = pd.concat(all_notices_list, ignore_index=True)
        mask = master_notice_df['公告标题'].str.contains('|'.join(keyword_map.keys()), na=False)
        hit_df = master_notice_df[mask]
        
        for _, row in hit_df.iterrows():
            title = str(row['公告标题'])
            found_k = next((keyword_map[k] for k in keyword_map if k in title), "其他")
            
            events_list.append({
                "Ticker": row['code_str'],
                "Name": row['名称'],
                "Event_Type": "重要公告",
                "Keyword": found_k,
                "Description": title,
                "Date": target_trade_date_str
            })
    else:
        master_notice_df = pd.DataFrame()

    # ==========================================
    # ==========================================
    # 2. 扫描复牌信息 (接口触发机制：接口为主，公告增强)
    # ==========================================
    try:
        df_tfp = pd.DataFrame()
        # 扫描 T日 和 目标日，获取最新的停复牌预告
        for query_date in [t_date_str, target_trade_date_str]:
            try:
                temp = ak.stock_tfp_em(date=query_date)
                if temp is not None and not temp.empty:
                    df_tfp = pd.concat([df_tfp, temp], ignore_index=True)
            except:
                continue

        if not df_tfp.empty:
            # 1. 基础清洗
            df_tfp = df_tfp.drop_duplicates(subset=['代码'])
            df_tfp['code_str'] = df_tfp['代码'].astype(str).str.zfill(6)
            df_tfp['expected'] = df_tfp['预计复牌时间'].astype(str).str.replace("-", "")
            
            # 2. 筛选：只要预计复牌日期等于下一个交易日
            resuming = df_tfp[df_tfp['expected'] == str(target_trade_date_str)]
            
            for _, row in resuming.iterrows():
                ticker = row['code_str']
                
                # 设置默认值：此时即便公告池里没东西，也会保留这条记录
                final_k = "复牌"
                final_d = row['停牌原因'] if row['停牌原因'] else "交易所预告复牌"
                
                # 3. 公告增强逻辑：如果公告池里能找到更详细的，就替换掉默认值
                if not master_notice_df.empty:
                    stock_notices = master_notice_df[master_notice_df['code_str'] == ticker]
                    if not stock_notices.empty:
                        # 尝试匹配并购/重组等核心关键字
                        found_special_keyword = False
                        for _, n_row in stock_notices.iterrows():
                            title = str(n_row['公告标题'])
                            match = next((keyword_map[k] for k in keyword_map if k in title), None)
                            if match:
                                final_k = match
                                final_d = title
                                found_special_keyword = True
                                break
                        
                        # 如果没匹配到重组关键字，但有公告，看看公告里有没有带“复牌”二字的标题
                        if not found_special_keyword:
                            fupai_notices = stock_notices[stock_notices['公告标题'].str.contains('复牌')]
                            if not fupai_notices.empty:
                                final_d = str(fupai_notices.iloc[0]['公告标题'])
                            else:
                                # 如果连“复牌”二字都没有，就取当天的第一条公告标题作为描述，增加专业感
                                final_d = str(stock_notices.iloc[0]['公告标题'])

                # 4. 写入池子：不再受 is_true_resumption 限制
                events_list.append({
                    "Ticker": ticker,
                    "Name": row['名称'],
                    "Event_Type": "复牌",
                    "Keyword": final_k,
                    "Description": final_d,
                    "Date": target_trade_date_str
                })
                    
    except Exception as e:
        print(f"复牌扫描异常: {e}")

    # ==========================================
    # 3. 去重与兜底返回
    # ==========================================
    if events_list:
        df_res = pd.DataFrame(events_list, columns=cols)
        # 精准去重
        df_res = df_res.drop_duplicates(subset=['Ticker', 'Description'])
        return df_res
    
    return pd.DataFrame(columns=cols)
# ==================== [4. Data & Caching] ====================
# ==================== [新增: 数据清洗过滤模块] ====================
def filter_valid_a_shares(df):
    """
    过滤候选池，仅保留正常的A股，剔除 ST、*ST、退市股及北交所股票。
    兼容列名为 '代码/名称' 或 'Ticker/Name' 的情况。
    """
    if df is None or df.empty:
        return df
    
    df_clean = df.copy()
    
    # 动态匹配列名，兼容打板池和事件池
    code_col = '代码' if '代码' in df_clean.columns else 'Ticker'
    name_col = '名称' if '名称' in df_clean.columns else 'Name'
    
    # 1. 确保代码补齐6位
    df_clean[code_col] = df_clean[code_col].astype(str).str.zfill(6)
    
    # 2. 仅保留 沪市(60), 科创板(68), 深市主板(00), 创业板(30)
    mask_code = df_clean[code_col].str.startswith(('00', '30', '60', '68'))
    
    # 3. 剔除名称中包含 ST, *ST, 或 退 的股票
    mask_name = ~df_clean[name_col].str.contains('ST|退', na=False, regex=True)
    
    return df_clean[mask_code & mask_name].reset_index(drop=True)

def filter_regulatory_inquiries(df, target_date_str, lookback_days=10):
    """
    过滤近期收到交易所关注函、问询函、监管函的股票。
    说明交易所正在重点监控，直接踢出打板候选池。
    """
    if df is None or df.empty:
        return df
        
    print(f"-> [合规扫描] 正在扫描近 {lookback_days} 个交易日的监管层问询/关注函...")
    
    # 1. 获取目标日期往前倒推的 lookback_days 个交易日
    trade_dates_df = ak.tool_trade_date_hist_sina()
    trade_dates = trade_dates_df["trade_date"].astype(str).str.replace("-", "").tolist()
    past_dates = [d for d in trade_dates if d <= str(target_date_str)]
    scan_dates = past_dates[-lookback_days:]
    
    inquiry_tickers = set()
    
    # 核心细节：严格限定为监管下发的敏感词。
    # 注意：千万别把“异常波动”加进去，因为正常连板股都会发《股票交易异常波动公告》，那个不能杀。
    # 只有带“函”字的才是交易所真正发话。
    keyword_patterns = ['问询函', '关注函', '监管函', '警示函', '监管工作函']
    
    # 2. 扫描历史公告（加入本地缓存机制，加速回测和重复运行）
    if not os.path.exists(os.path.join(PROJECT_ROOT, "data", "data_cache")):
        os.makedirs(os.path.join(PROJECT_ROOT, "data", "data_cache"))
        
    for d in scan_dates:
        cache_path = os.path.join(PROJECT_ROOT, "data", "data_cache", f"notices_{d}.csv")
        df_notice = pd.DataFrame()
        
        # 尝试读取缓存
        if os.path.exists(cache_path):
            try:
                df_notice = pd.read_csv(cache_path, dtype={'代码': str})
            except:
                pass
                
        # 缓存缺失或损坏时，重新拉取
        if df_notice.empty:
            try:
                df_notice = ak.stock_notice_report(symbol="全部", date=d)
                if df_notice is not None and not df_notice.empty:
                    # 保存缓存，加速下次执行
                    df_notice.to_csv(cache_path, index=False, encoding='utf-8-sig')
            except Exception as e:
                # 接口波动时静默跳过
                continue
                
        # 3. 解析当日公告
        if df_notice is not None and not df_notice.empty:
            df_notice['code_str'] = df_notice['代码'].astype(str).str.zfill(6)
            # 仅限A股
            df_notice = df_notice[df_notice['code_str'].str.startswith(('00', '30', '60', '68'))]
            
            # 正则匹配标题
            mask = df_notice['公告标题'].str.contains('|'.join(keyword_patterns), na=False)
            hit_df = df_notice[mask]
            
            inquiry_tickers.update(hit_df['code_str'].tolist())
            
    # 4. 剔除涉事股票
    if inquiry_tickers:
        # 兼容处理 DataFrame 中的代码列名
        code_col = '代码' if '代码' in df.columns else 'Ticker'
        if code_col in df.columns:
            original_len = len(df)
            
            # 保留没有在黑名单里的股票
            df_clean = df[~df[code_col].astype(str).str.zfill(6).isin(inquiry_tickers)].reset_index(drop=True)
            
            kicked_out = original_len - len(df_clean)
            if kicked_out > 0:
                print(f"-> [风险排除] 剔除了 {kicked_out} 只处于监管问询/关注期的股票。")
            return df_clean
            
    return df

def fetch_data_with_cache(cache_name, date_str, func, **kwargs):
    if not os.path.exists(os.path.join(PROJECT_ROOT, "data", "data_cache")):
        os.makedirs(os.path.join(PROJECT_ROOT, "data", "data_cache"))
        
    file_path = os.path.join(PROJECT_ROOT, "data", "data_cache", f"{cache_name}_{date_str}.csv")
    fetch_new = True
    
    if os.path.exists(file_path):
        try:
            df = pd.read_csv(file_path, dtype={'代码': str, '股票代码': str})
            
            # 1. 获取文件的最后修改时间
            mtime = os.path.getmtime(file_path)
            mtime_dt = datetime.fromtimestamp(mtime)
            
            # 2. 计算目标数据日期的收盘时间 (当天 15:30)
            target_date_dt = datetime.strptime(str(date_str), "%Y%m%d")
            target_close_dt = target_date_dt.replace(hour=15, minute=30, second=0)
            now_dt = datetime.now()
            
            # 3. 核心校验逻辑
            if mtime_dt < target_close_dt:
                # 情况 A：缓存是在当天盘中创建的 (残缺数据)
                if now_dt > target_close_dt:
                    print(f"-> [更新缓存] 发现 {date_str} 的盘中残缺数据，正在重新拉取全天完整数据...")
                    fetch_new = True
                else:
                    print(f"-> [实时拉取] {date_str} 交易尚未结束，重新拉取最新盘中数据...")
                    fetch_new = True
            else:
                # 情况 B：缓存是在收盘后创建的 (理论上是完整数据)
                if len(df) < 10:
                    # 兜底：如果数据异常少（比如只有5只），强制重新请求，防止API脏数据污染
                    print(f"-> [异常拦截] {date_str} 缓存数据过少({len(df)}只)，强制重新拉取...")
                    fetch_new = True
                else:
                    # 数据健康，正常使用缓存
                    fetch_new = False
                    
        except Exception as e:
            print(f"-> [读取错误] 缓存文件损坏 {file_path}: {e}")
            fetch_new = True
            
    if fetch_new:
        try:
            df = func(**kwargs)
            if df is not None and not df.empty:
                # 重新拉取成功，覆盖掉有问题的旧缓存
                df.to_csv(file_path, index=False, encoding='utf-8-sig')
                return df
            return pd.DataFrame()
        except Exception as e:
            print(f"-> [网络异常] 无法获取 {cache_name}: {e}")
            # 如果断网了，只能委屈求全用之前的残缺缓存
            if os.path.exists(file_path):
                return pd.read_csv(file_path, dtype={'代码': str, '股票代码': str})
            return pd.DataFrame()
            
    return df

def get_market_dates():
    """
    获取 数据日(T日) 和 目标交易日(T+1日)
    返回: (data_date, target_date)
    """
    trade_dates_df = ak.tool_trade_date_hist_sina()
    trade_dates = trade_dates_df["trade_date"].astype(str).str.replace("-", "").tolist()
    
    from datetime import datetime, timezone, timedelta
    now = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=8)
    today_str = now.strftime("%Y%m%d")
    
    past_dates =[d for d in trade_dates if d <= today_str]
    
    # 核心修正：15:30 之后，当天的收盘数据（涨停池）已经更新完毕
    if today_str == past_dates[-1] and (now.hour > 15 or (now.hour == 15 and now.minute >= 30)):
        data_date = past_dates[-1]
    else:
        # 盘前或盘中，使用上一个已收盘的交易日数据
        data_date = past_dates[-2] if today_str == past_dates[-1] else past_dates[-1]
        
    # 目标交易日（客户要去买的那个日子，即 data_date 的下一个交易日）
    idx = trade_dates.index(data_date)
    target_date = trade_dates[idx + 1]
    
    return data_date, target_date

def get_recent_trade_dates(days=7):
    trade_dates_df = ak.tool_trade_date_hist_sina()
    trade_dates_df["trade_date"] = trade_dates_df["trade_date"].astype(str).str.replace("-", "")
    from datetime import datetime, timezone, timedelta
    today_str = (datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=8)).strftime("%Y%m%d")
    filtered_df = trade_dates_df[trade_dates_df["trade_date"] <= today_str]
    return sorted(filtered_df["trade_date"].tolist())[-days:]

def get_hist_prices_cache(code, start_date, end_date):
    """用于机器学习模型训练的前复权(qfq)日K线拉取，带盘中残缺数据识别"""
    if not os.path.exists(os.path.join(PROJECT_ROOT, "data", "data_cache")): os.makedirs(os.path.join(PROJECT_ROOT, "data", "data_cache"))
    clean_code = str(code).zfill(6)
    cache_path = os.path.join(PROJECT_ROOT, "data", "data_cache", f"price_{clean_code}.csv")
    
    fetch_new = True
    if os.path.exists(cache_path):
        try:
            df = pd.read_csv(cache_path)
            if not df.empty and '日期' in df.columns:
                df['date_str'] = df['日期'].astype(str).str.replace("-", "")
                max_date = df['date_str'].max()
                
                # 1. 检查日期是否覆盖
                if str(max_date) >= str(end_date):
                    # 2. 检查是否是“当天的残缺数据”
                    # 如果缓存最大日期正好是我们请求的日期
                    if str(max_date) == str(end_date):
                        mtime = os.path.getmtime(cache_path)
                        mtime_dt = datetime.fromtimestamp(mtime)
                        
                        target_dt = datetime.strptime(str(end_date), "%Y%m%d")
                        target_close_dt = target_dt.replace(hour=15, minute=30, second=0)
                        from datetime import timezone, timedelta
                        now_dt = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=8)
                        
                        if mtime_dt < target_close_dt:
                            if now_dt > target_close_dt:
                                print(f"    -> [更新训练K线] 发现 {clean_code} 的盘中残缺数据，拉取收盘完整版...")
                                fetch_new = True
                            else:
                                # 盘中时刻，需要拉取最新的盘中 K 线
                                fetch_new = True
                        else:
                            # 缓存是在 15:30 收盘后建立的，数据已完整
                            fetch_new = False
                    else:
                        # 历史日期，肯定是完整的
                        fetch_new = False
        except Exception:
            fetch_new = True
            
    if fetch_new:
        max_retries = 3
        for attempt in range(max_retries):
            try:
                # 训练模型必须用 qfq
                df = ak.stock_zh_a_hist(symbol=clean_code, period="daily", adjust="qfq")
                if not df.empty:
                    df.to_csv(cache_path, index=False)
                    return df
            except Exception as e:
                time.sleep(1.5)
        
        # 兜底
        if os.path.exists(cache_path):
            return pd.read_csv(cache_path)
        return pd.DataFrame()
        
    return df

def get_next_trade_date(current_date_str):
    """根据当前日期，获取下一个有效交易日 (用于寻找明日复牌的股票)"""
    trade_dates_df = ak.tool_trade_date_hist_sina()
    trade_dates = trade_dates_df["trade_date"].astype(str).str.replace("-", "").tolist()
    # 找出所有大于当前日期的交易日
    future_dates =[d for d in trade_dates if d > current_date_str]
    return future_dates[0] if future_dates else current_date_str
# ==================== [5. Factor Engineering] ====================
def convert_lianban_num(s):
    try:
        if isinstance(s, (int, float)): return int(s)
        s = str(s).strip()
        if "连板" in s: return int(''.join(filter(str.isdigit, s)))
        return 1 if "首" in s else 0
    except: return 0

def convert_chengjiao(s):
    try:
        s = str(s).strip()
        if "亿" in s: return float(s.replace("亿", "")) * 1e8
        if "万" in s: return float(s.replace("万", "")) * 1e4
        return float(s)
    except: return 0.0

def time_to_min(s):
    s = str(s).replace(":","").zfill(6)
    try: return int(s[:2])*60 + int(s[2:4])
    except: return 0

def chair(raw_df):
    dates = get_recent_trade_dates(3)
    try:
        df_lhb = ak.stock_lhb_hyyyb_em(start_date=dates[0], end_date=dates[-1])
        if df_lhb.empty: return pd.Series([0]*len(raw_df), index=raw_df.index)
        buy_stocks = "".join(df_lhb["买入股票"].astype(str).tolist())
        return pd.Series([1 if str(name) in buy_stocks else 0 for name in raw_df["名称"]], index=raw_df.index)
    except: return pd.Series([0]*len(raw_df), index=raw_df.index)

def conception(df, t_date):
    try:
        df_board = ak.stock_board_industry_name_em()
        df_board['strength'] = (df_board['涨跌幅'] - df_board['涨跌幅'].mean()) / (df_board['涨跌幅'].std() + 1e-6)
        mapping = df_board.set_index('板块名称')['strength'].to_dict()
        df['Factor_Board_Strength'] = df['所属行业'].map(mapping).fillna(0)
    except: df['Factor_Board_Strength'] = 0
    return df

def factor_engineering_for_tomorrow_new(df, t_date):
    df = df.copy()
    
    # Client presentation features
    df["封板金额_亿"] = pd.to_numeric(df.get("封板资金", 0), errors='coerce').fillna(0) / 1e8
    df["封板金额_亿"] = df["封板金额_亿"].round(2)
    df["流通市值_亿"] = pd.to_numeric(df.get("流通市值", 0), errors='coerce').fillna(0) / 1e8
    df["流通市值_亿"] = df["流通市值_亿"].round(2)
    
    def is_one_word_board(row):
        # 1. 验证炸板次数 (必须为0)
        zhaban = str(row.get("炸板次数", "0"))
        is_no_explode = zhaban in ["0", "0次"]
        
        # 2. 验证封板时间 (必须在09:25集合竞价阶段)
        # 考虑到可能传入的是今日涨停池(首次封板时间)或昨日涨停池(昨日封板时间)
        seal_time_raw = row.get("首次封板时间", row.get("昨日封板时间", "000000"))
        
        # 清洗时间戳：去掉冒号，并在左侧补零到6位
        # 例如: "09:25:03" -> "092503", "92500" -> "092500"
        seal_time_clean = str(seal_time_raw).replace(":", "").zfill(6)
        
        # 判断前4位是否为 0925
        is_auction_seal = seal_time_clean.startswith("0925")
        
        return "Yes" if (is_no_explode and is_auction_seal) else "No"
    
    df["Is_One_Word"] = df.apply(is_one_word_board, axis=1)

    # ML Features
    df["成交额_val"] = df.get("成交额", 0).apply(convert_chengjiao)
    df["Factor_Sealing_Ratio"] = (df["封板金额_亿"] * 1e8) / (df["成交额_val"] + 1)
    df["Factor_Sealing_Time"] = df.get("首次封板时间", "093000").apply(time_to_min)
    df["Factor_Explode_Count"] = df.get("炸板次数", "0次").apply(lambda x: int(str(x).replace("次","")))
    df["Factor_Lianban_Height"] = df.get("连板数", 1).apply(convert_lianban_num)
    df["Factor_Industry_ID"] = df.get("所属行业", "Unknown").factorize()[0]
    df["Factor_Brokerage_Seat"] = chair(df)
    df = conception(df, t_date)
    
    alpha, n = 0.5, 3
    df["Factor_Effective_Lianban"] = df["Factor_Lianban_Height"].apply(lambda x: x / (1 + alpha * max(0, x - n)))
    
    features =[c for c in df.columns if c.startswith("Factor_")]
    return df, df[features]

# ====================[6. Model Optimization & Expert Rules] ====================
def compute_sample_weights_from_dates(date_array, current_date, lambda_val):
    current_dt = datetime.strptime(str(current_date), "%Y%m%d")
    weights =[]
    for d in date_array:
        sample_dt = datetime.strptime(str(d), "%Y%m%d")
        diff_days = (current_dt - sample_dt).days
        weights.append(np.exp(-lambda_val * diff_days))
    return np.array(weights)

def get_best_lambda(X, y, dates, t_date, clf_params):
    candidate_lambdas =[0, 0.1, 0.3, 0.5, 0.7, 0.9, 1.0]
    best_score, best_lam = -1, 0.5
    base_clf = RandomForestClassifier(**clf_params)
    tscv = TimeSeriesSplit(n_splits=3)
    
    for lam in candidate_lambdas:
        weights = compute_sample_weights_from_dates(dates, t_date, lambda_val=lam)
        scores =[]
        for train_idx, val_idx in tscv.split(X):
            sw_train = weights[train_idx]
            base_clf.fit(X[train_idx], y.iloc[train_idx], sample_weight=sw_train)
            scores.append(base_clf.score(X[val_idx], y.iloc[val_idx]))
        avg_score = np.mean(scores)
        if avg_score > best_score:
            best_score, best_lam = avg_score, lam
    return best_lam

def modeling_demo_2_new(merged_df, t_date, historical_data):
    hist_processed, X_hist = factor_engineering_for_tomorrow_new(historical_data, t_date)
    test_processed, X_test = factor_engineering_for_tomorrow_new(merged_df, t_date)
    
    train_dates = hist_processed["日期"].values
    X_train, y_train = X_hist, hist_processed["Label"]
    
    scaler = StandardScaler()
    X_train_s = scaler.fit_transform(X_train)
    X_test_s = scaler.transform(X_test)

    def rf_cv(n_estimators, max_depth, min_samples_split, min_samples_leaf):
        clf = RandomForestClassifier(
            n_estimators=int(n_estimators), max_depth=int(max_depth),
            min_samples_split=int(min_samples_split), min_samples_leaf=int(min_samples_leaf),
            random_state=42
        )
        return cross_val_score(clf, X_train_s, y_train, cv=TimeSeriesSplit(n_splits=3)).mean()

    optimizer = BayesianOptimization(
        f=rf_cv, pbounds={"n_estimators":(100, 300), "max_depth":(5, 15), 
                         "min_samples_split":(2, 10), "min_samples_leaf":(1, 4)},
        random_state=42, verbose=0
    )
    optimizer.maximize(init_points=5, n_iter=10)
    best_params = {k: int(v) for k, v in optimizer.max["params"].items()}
    best_params["random_state"] = 42
    
    best_lambda = get_best_lambda(X_train_s, y_train, train_dates, t_date, best_params)
    final_weights = compute_sample_weights_from_dates(train_dates, t_date, lambda_val=best_lambda)
    
    clf = RandomForestClassifier(**best_params)
    clf.fit(X_train_s, y_train, sample_weight=final_weights)
    return clf, scaler

def apply_client_preference_bonus(row):
    """
    Expert Rule Overlay: Add probability bonus based on client preferences.
    Pref 1: Market Cap between 10B and 20B CNY (+5%)
    Pref 2: One-word limit-up board (+10%)
    Pref 3: Massive sealing amount >= 500M CNY (+5%)
    Pref 4 (Penalty): Non-linear penalty for limit-up streaks > 3
    """
    bonus = 0.0
    
    # 1. 基础加分项
    market_cap = row.get("流通市值_亿", 0)
    if 100 <= market_cap <= 200: 
        bonus += 0.05
        
    if row.get("Is_One_Word") == "Yes": 
        bonus += 0.15
        
    sealing_amt = row.get("封板金额_亿", 0)
    if sealing_amt >= 5.0: 
        bonus += 0.05
    if sealing_amt >= 10.0: 
        bonus += 0.10

    # 2. 高位连板非线性惩罚机制 (核心改动)
    # 取出连板高度因子
    lianban_height = row.get("Factor_Lianban_Height", 1)
    
    if lianban_height > 1:
        penalty = -0.2 * ((lianban_height - 1))
        bonus += penalty
        
    return bonus

def select_2_each_market(df):
    df_copy = df.copy()
    if "Success_Prob" not in df_copy.columns:
        raise KeyError("Success_Prob not calculated.")
        
    def classify_market(code):
        c = str(code).zfill(6)
        if c.startswith(('60', '68')):
            return "SH"
        elif c.startswith(('00', '30')):
            return "SZ"
        else:
            return "OTHER" # 防止北交所或其他代码混入
    
    df_copy["Market"] = df_copy["代码"].apply(classify_market)
    
    # 只从明确的 SH 和 SZ 中选股
    sh_recs = df_copy[df_copy["Market"] == "SH"].sort_values("Success_Prob", ascending=False).head(2)
    sz_recs = df_copy[df_copy["Market"] == "SZ"].sort_values("Success_Prob", ascending=False).head(2)
    
    final_df = pd.concat([sh_recs, sz_recs]).drop_duplicates(subset=['代码'])
    
    if len(final_df) < 4:
        # 补齐时也必须排除掉 OTHER
        remaining = df_copy[(~df_copy.index.isin(final_df.index)) & (df_copy["Market"] != "OTHER")]
        remaining = remaining.sort_values("Success_Prob", ascending=False)
        final_df = pd.concat([final_df, remaining.head(4 - len(final_df))])
        
    return final_df.sort_values("Success_Prob", ascending=False)
# ==================== [7. Backtest Logic] ====================


    if res_a.empty or res_b.empty: return
    res_a['date'] = pd.to_datetime(res_a['date'])
    res_b['date'] = pd.to_datetime(res_b['date'])
    
    plt.figure(figsize=(16, 12))
    gs = gridspec.GridSpec(3, 1, height_ratios=[2, 1, 1])

    ax1 = plt.subplot(gs[0])
    ax1.plot(res_a['date'], res_a['equity'], label='Strategy A: All-In', color='#e74c3c', linewidth=2)
    ax1.plot(res_b['date'], res_b['equity'], label='Strategy B: Smart Withdrawal', color='#3498db', linewidth=2.5)
    ax1.axhline(INITIAL_CAPITAL, color='gray', linestyle='--', alpha=0.6)
    ax1.set_title(f'Strategy Comparison: Total Equity (Initial: {INITIAL_CAPITAL})', fontsize=16)
    ax1.set_ylabel('Account Value (CNY)')
    ax1.legend(loc='upper left')
    ax1.grid(True, alpha=0.3)

    ax2 = plt.subplot(gs[1])
    rets = res_b['daily_ret'] * 100
    ax2.bar(res_b['date'], rets, color=np.where(rets >= 0, '#2ecc71', '#e74c3c'), alpha=0.7)
    ax2.axhline(0, color='black', linewidth=0.8)
    ax2.set_title('Strategy B: Daily Returns (%)', fontsize=14)
    ax2.set_ylabel('Return %')
    ax2.grid(True, alpha=0.3)

    ax3 = plt.subplot(gs[2])
    rolling_max = res_b['equity'].cummax()
    drawdown = (res_b['equity'] - rolling_max) / rolling_max
    ax3.fill_between(res_b['date'], 0, drawdown * 100, color='#e74c3c', alpha=0.3)
    ax3.set_title('Strategy B: Drawdown (%)', fontsize=14)
    ax3.set_ylabel('Decline %')
    ax3.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.show()

# ==================== [7. 30-Day Specific Backtest Module (T+1 Open Buy, T+2 Open Sell)] ====================

# ==================== [8. Backtest Engine (Pure K-Line, Unadjusted)] ====================

def get_hist_prices_backtest_cache(code, start_date, end_date):
    """
    【回测专属K线获取器】：强制使用不复权(adjust="")数据。
    与原有的 get_hist_prices_cache 完全隔离，文件存为 price_unadj_xxxxxx.csv，
    绝不会影响或污染机器学习的 qfq 训练池！
    """
    if not os.path.exists(os.path.join(PROJECT_ROOT, "data", "data_cache")): 
        os.makedirs(os.path.join(PROJECT_ROOT, "data", "data_cache"))
        
    clean_code = str(code).zfill(6)
    # 独立的缓存文件名，防止和复权数据冲突
    cache_path = os.path.join(PROJECT_ROOT, "data", "data_cache", f"price_unadj_{clean_code}.csv")
    
    # 1. 尝试读本地缓存
    if os.path.exists(cache_path):
        try:
            df = pd.read_csv(cache_path)
            if not df.empty and '日期' in df.columns:
                df['date_str'] = df['日期'].astype(str).str.replace("-", "")
                max_date = df['date_str'].max()
                
                # 本地数据够用，直接返回，不再请求 API
                if str(max_date) >= str(end_date):
                    return df
        except Exception:
            pass
            
    # 2. 如果本地数据不够，请求 akshare 补齐 (加入防并发断联机制)
    max_retries = 3
    for attempt in range(max_retries):
        try:
            # 强制 adjust=""
            df = ak.stock_zh_a_hist(symbol=clean_code, period="daily", adjust="")
            if not df.empty:
                df.to_csv(cache_path, index=False)
                return df
        except Exception as e:
            print(f"    🔄 [API重试] {clean_code} 第 {attempt+1} 次拉取受阻, 休眠1.5秒后重试... ({e})")
            time.sleep(1.5)
            
    # 3. 彻底失败时的兜底
    print(f"    ❌ [API失败] {clean_code} 多次重试均失败，可能是退市或网络异常。")
    if os.path.exists(cache_path):
        return pd.read_csv(cache_path)
        
    return pd.DataFrame()

def calculate_strict_limit_up(prev_close, code):
    """
    严格按照 A 股交易所规则计算理论涨停价。
    A股是标准四舍五入，必须使用 Decimal 库来进行 ROUND_HALF_UP。
    """
    code_str = str(code).zfill(6)
    
    if code_str.startswith(('30', '68')):
        multiplier = Decimal('1.20')
    else:
        multiplier = Decimal('1.10')
        
    prev_c = Decimal(str(prev_close))
    limit_p = prev_c * multiplier
    
    return float(limit_p.quantize(Decimal('0.00'), rounding=ROUND_HALF_UP))

def evaluate_t1_open_to_t2_open(code, t_date, t1_date, t2_date):
    """
    纯本地 K 线评估逻辑，完美避开 7 天涨停池 API 限制。
    """
    clean_code = str(code).zfill(6)
    
    # 【核心修改】：这里调用回测专属的不复权函数
    df = get_hist_prices_backtest_cache(clean_code, t_date, t2_date)
    
    if df is None or df.empty:
        return {"status": "error", "reason": "无法获取历史K线数据"}

    df['date_key'] = df['日期'].astype(str).str.replace("-", "")
    
    t_row = df[df['date_key'] == str(t_date)]
    t1_row = df[df['date_key'] == str(t1_date)]
    t2_row = df[df['date_key'] == str(t2_date)]
    
    if t_row.empty or t1_row.empty:
        return {"status": "error", "reason": "此区间内可能停牌或无交易"}

    # 提取 T 日收盘价，T+1 日的开盘与最高价
    close_t = float(t_row['收盘'].iloc[0])
    open_t1 = float(t1_row['开盘'].iloc[0])
    high_t1 = float(t1_row['最高'].iloc[0])
    
    # 1. 判断是否涨停开盘 (开盘价较昨收上涨至少9%)
    if open_t1 < (close_t * 1.09):
        return {"status": "cancelled", "reason": f"未达涨停价(开盘:{open_t1:.2f}, 昨收:{close_t:.2f})"}
        
    # 2. 判断开盘价是否是全天的最低价 (保证竞价确实是一字封死，未被砸)
    low_t1 = float(t1_row['最低'].iloc[0])
    if low_t1 < (open_t1 - 0.01):
        return {"status": "cancelled", "reason": f"未封死被砸(开盘:{open_t1:.2f}, 盘中最低:{low_t1:.2f})"}
    
    # ========== 交易执行逻辑 ==========
    if t2_row.empty:
         close_t1 = float(t1_row['收盘'].iloc[0])
         pnl_raw = (close_t1 - open_t1) / open_t1
         return {"status": "suspended_t2", "pnl_net": pnl_raw - 0.0016, "buy_price": open_t1}

    open_t2 = float(t2_row['开盘'].iloc[0])
    
    # 算术净收益，扣除 0.16% 综合成本
    pnl_raw = (open_t2 - open_t1) / open_t1
    pnl_net = pnl_raw - 0.0016 
    
    return {
        "status": "executed",
        "buy_price": open_t1,
        "sell_price": open_t2,
        "pnl_net": pnl_net
    }
    print(f"\n========== 启动过去 {days} 个交易日滚动回测 ==========")
    print("规则: T日选股 -> T+1日必须一字涨停开盘才买入 (否则9:20撤单) -> T+2日开盘无脑卖出")
    
    # 获取需要的所有交易日日期 (需要 days + 前置训练10天 + 后续结果评估2天)
    all_dates = get_recent_trade_dates(days + 10 + 2)
    backtest_dates = all_dates[10:-2] # 提取用于回测的 T 日
    
    INITIAL_CAPITAL = 100000.0
    equity = INITIAL_CAPITAL
    equity_curve = []
    trade_logs = []
    
    for i, t_date in enumerate(backtest_dates):
        # 定位 T+1 和 T+2 交易日
        current_idx = all_dates.index(t_date)
        t1_date = all_dates[current_idx + 1]
        t2_date = all_dates[current_idx + 2]
        
        print(f"\n[{i+1}/{days}] 正在处理 T日: {t_date} (操作日: {t1_date}, 卖出日: {t2_date})")
        
        # 1. 动态准备历史训练数据 (T 日往前推10个交易日)
        train_dates = all_dates[current_idx-10 : current_idx]
        all_hist_data = []
        for j in range(len(train_dates)-1):
            d_prev, d_curr = train_dates[j], train_dates[j+1]
            zt_prev = fetch_data_with_cache("zt_pool", d_prev, ak.stock_zt_pool_em, date=d_prev)
            zt_curr = fetch_data_with_cache("zt_pool", d_curr, ak.stock_zt_pool_em, date=d_curr)
            if zt_prev.empty or zt_curr.empty: continue
            zt_curr_codes = set(zt_curr["代码"].unique())
            zt_prev["Label"] = zt_prev["代码"].apply(lambda x: 1 if x in zt_curr_codes else 0)
            zt_prev["日期"] = d_prev
            all_hist_data.append(zt_prev)
            
        train_full = pd.concat(all_hist_data) if all_hist_data else pd.DataFrame()
        
        # 2. 拉取 T 日涨停池并过滤
        t_zt = fetch_data_with_cache("zt_pool", t_date, ak.stock_zt_pool_em, date=t_date)
        t_zt = filter_valid_a_shares(t_zt)
        t_zt = filter_regulatory_inquiries(t_zt, t_date, lookback_days=10)
        
        if t_zt.empty or train_full.empty:
            print(f" -> {t_date} 缺乏训练数据或打板候选池为空，空仓。")
            equity_curve.append({"date": t1_date, "equity": equity})
            continue
            
        # 3. 训练模型并预测
        try:
            clf, scaler = modeling_demo_2_new(t_zt, t_date, train_full)
            t_processed, X_pred = factor_engineering_for_tomorrow_new(t_zt, t_date)
            X_pred_scaled = scaler.transform(X_pred.values)
            t_processed["Success_Prob"] = clf.predict_proba(X_pred_scaled)[:, 1]
            t_processed["Final_Score"] = t_processed.apply(
                lambda row: min(0.99, row["Success_Prob"] + apply_client_preference_bonus(row)), axis=1
            )
            t_processed["Success_Prob"] = t_processed["Final_Score"]
            
            # 选出符合条件的两市前2名 (一共最多4只)
            picks = select_2_each_market(t_processed)
        except Exception as e:
            print(f" -> 模型训练/预测异常: {e}，跳过此日。")
            equity_curve.append({"date": t1_date, "equity": equity})
            continue

        # 4. 执行交易模拟
        daily_pnl = 0.0
        allocated_capital = equity / max(len(picks), 1) # 平均分配仓位
        executed_count = 0
        
        for _, stock in picks.iterrows():
            code = stock['代码']
            name = stock['名称']
            
            trade_res = evaluate_t1_open_to_t2_open(code, t_date, t1_date, t2_date)
            
            if trade_res["status"] == "executed" or trade_res["status"] == "suspended_t2":
                pnl = trade_res["pnl_net"]
                money_earned = allocated_capital * pnl
                daily_pnl += money_earned
                executed_count += 1
                
                trade_logs.append({
                    "T_Date": t_date, "T1_Date": t1_date, "Ticker": code, "Name": name, 
                    "Status": "成交并卖出", "PnL(%)": round(pnl*100, 2)
                })
                print(f"    [成交] {name}({code}) -> T+1开盘买入, PnL: {pnl*100:.2f}%")
            
            elif trade_res["status"] == "cancelled":
                trade_logs.append({
                    "T_Date": t_date, "T1_Date": t1_date, "Ticker": code, "Name": name, 
                    "Status": "开盘未涨停_已撤单", "PnL(%)": 0
                })
                print(f"    [撤单] {name}({code}) -> {trade_res['reason']}")
        
        equity += daily_pnl
        equity_curve.append({"date": t1_date, "equity": equity, "daily_pnl": daily_pnl, "executed_trades": executed_count})
        print(f" -> 今日结束资金: {equity:.2f}")

    return pd.DataFrame(equity_curve), pd.DataFrame(trade_logs), INITIAL_CAPITAL

# ==================== [9. Webhook Integration] ====================
class WeComBot:
    def __init__(self, webhook_url):
        # 修复 HTTP 大小写问题，requests 库仅支持小写的 http:// 和 https://
        if webhook_url.startswith("HTTP://"):
            webhook_url = "http://" + webhook_url[7:]
        elif webhook_url.startswith("HTTPS://"):
            webhook_url = "https://" + webhook_url[8:]
        self.webhook_url = webhook_url

    def send_text(self, text):
        import requests
        headers = {"Content-Type": "application/json"}
        data = {"msgtype": "text", "text": {"content": text}}
        try:
            requests.post(self.webhook_url, json=data, headers=headers)
        except Exception as e:
            print(f"Failed to send text: {e}")

    def send_markdown(self, md):
        import requests
        headers = {"Content-Type": "application/json"}
        # 企业微信对 markdown 文本有 4000 字节左右的限制，这里进行安全分段
        max_len = 4000
        chunks = [md[i:i + max_len] for i in range(0, len(md), max_len)]
        for chunk in chunks:
            data = {"msgtype": "markdown", "markdown": {"content": chunk}}
            try:
                requests.post(self.webhook_url, json=data, headers=headers)
            except Exception as e:
                print(f"Failed to send markdown: {e}")

    def send_file(self, file_path):
        import requests
        import os
        
        if not os.path.exists(file_path):
            print(f"File not found: {file_path}")
            return
            
        # 构建企微上传临时素材的 URL
        upload_url = self.webhook_url.replace("webhook/send?", "webhook/upload_media?type=file&")
        
        try:
            with open(file_path, "rb") as f:
                # 1. 上传文件获取 media_id
                # 必须指定 filename 和 file-like object
                files = {"media": (os.path.basename(file_path), f)}
                upload_res = requests.post(upload_url, files=files).json()
                
                if upload_res.get("errcode") == 0:
                    media_id = upload_res.get("media_id")
                    
                    # 2. 推送文件消息
                    data = {
                        "msgtype": "file",
                        "file": {"media_id": media_id}
                    }
                    requests.post(self.webhook_url, json=data)
                    print(f"File {os.path.basename(file_path)} sent successfully.")
                else:
                    print(f"Failed to upload media: {upload_res}")
        except Exception as e:
            print(f"Failed to send file: {e}")