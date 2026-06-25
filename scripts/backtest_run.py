import sys, os
import pandas as pd
import akshare as ak
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
from datetime import datetime, timedelta
import glob
import time
import yfinance as yf
import glob
import time
import yfinance as yf

try:
    PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
except NameError:
    # 兼容 VSCode 交互式窗口 (Run Cell) 模式
    PROJECT_ROOT = os.path.abspath(os.getcwd())
sys.path.append(PROJECT_ROOT)
from src.strategy_utils import calculate_strict_limit_up, get_hist_prices_backtest_cache, get_recent_trade_dates

def get_trade_dates():
    trade_dates_df = ak.tool_trade_date_hist_sina()
    return trade_dates_df["trade_date"].astype(str).str.replace("-", "").tolist()

def get_yfinance_hist_backtest(code_str, start_date_str, end_date_str):
    if code_str.startswith(('60', '68')):
        yf_ticker = f"{code_str}.SS"
    else:
        yf_ticker = f"{code_str}.SZ"
        
    try:
        start_dt = datetime.strptime(start_date_str, "%Y%m%d").strftime("%Y-%m-%d")
        end_dt_obj = datetime.strptime(end_date_str, "%Y%m%d") + timedelta(days=1)
        end_dt = end_dt_obj.strftime("%Y-%m-%d")
        
        ticker = yf.Ticker(yf_ticker)
        df_yf = ticker.history(start=start_dt, end=end_dt, auto_adjust=False)
        
        if df_yf.empty:
            return None
            
        df_yf = df_yf.reset_index()
        df = pd.DataFrame()
        df['date_key'] = df_yf['Date'].dt.strftime('%Y%m%d')
        df['开盘'] = df_yf['Open']
        df['收盘'] = df_yf['Close']
        df['最高'] = df_yf['High']
        df['最低'] = df_yf['Low']
        
        return df
    except Exception as e:
        return None

def evaluate_trade_strict(code, t_date, t1_date, t2_date):
    """
    统一的回测评估引擎 (严格不复权 + Decimal涨停价计算)
    买入: T+1 涨停价开盘且封死
    卖出: T+2 开盘
    """
    code_str = str(code).zfill(6)
    
    # 获取区间内严格不复权数据 (使用 yfinance)
    df = get_yfinance_hist_backtest(code_str, t_date, t2_date)
    if df is None or df.empty:
        return {"status": "error", "reason": "无法获取K线数据(yfinance)"}

    # date_key is already formatted inside get_yfinance_hist_backtest
    
    t_row = df[df['date_key'] == t_date]
    t1_row = df[df['date_key'] == t1_date]
    t2_row = df[df['date_key'] == t2_date]
    
    if t_row.empty or t1_row.empty:
        return {"status": "error", "reason": "T日或T+1日无数据(可能停牌)"}

    # 获取不复权昨收价
    prev_close = float(t_row['收盘'].iloc[-1])
    buy_open = float(t1_row['开盘'].iloc[0])
    buy_high = float(t1_row['最高'].iloc[0])

    # 2. 开盘价判定 (只要涨幅达到9%以上就算涨停)
    if buy_open < (prev_close * 1.09):
        return {"status": "cancelled", "reason": f"开盘未涨停(开盘:{buy_open:.2f}, 昨收:{prev_close:.2f})"}
        
    # 3. 封死判定 (一字封死意味着全天最低价和开盘价一致)
    buy_low = float(t1_row['最低'].iloc[0])
    if buy_low < (buy_open - 0.01):
        return {"status": "cancelled", "reason": f"开盘未封死被砸(开盘:{buy_open:.2f}, 最低:{buy_low:.2f})"}

    # T+2 卖出
    if t2_row.empty:
        # 如果 T+2 停牌，按 T+1 收盘价结算 (保守估算)
        buy_close = float(t1_row['收盘'].iloc[0])
        return {"status": "executed", "buy_price": buy_open, "sell_price": buy_close, "note": "T+2停牌_按T+1收盘估算"}

    sell_open = float(t2_row['开盘'].iloc[0])
    return {"status": "executed", "buy_price": buy_open, "sell_price": sell_open, "note": "正常卖出"}


def main():
    print("="*60)
    print("   🚀 统一高精度回测引擎 (不复权 + 绝对金额/复利双轨)   ")
    print("="*60)
    
    excel_files = glob.glob(os.path.join(PROJECT_ROOT, 'output', "明日_*.xlsx"))
    excel_files.sort()
    
    if not excel_files:
        print("❌ 未找到任何 '明日_*.xlsx' 文件。")
        return
        
    print(f"✅ 扫描到 {len(excel_files)} 个历史预测文件，开始全量回测...\n")

    trade_dates = get_trade_dates()
    today_str = datetime.now().strftime("%Y%m%d")

    # 双轨资金记录
    # 1. 复利模式
    COMPOUND_CAPITAL = 100000.0
    comp_equity = COMPOUND_CAPITAL
    # 2. 绝对金额模式 (单只股票分配100万)
    FIXED_CAPITAL_PER_STOCK = 1000000.0
    total_absolute_profit = 0.0
    
    trade_logs = []
    comp_equity_curve = []

    for file in excel_files:
        filename = os.path.basename(file)
        # buy_date 即为 T+1 (交易日)
        t_plus_1_date = "".join([c for c in filename if c.isdigit()]) 
        
        try:
            idx = trade_dates.index(t_plus_1_date)
            t_date = trade_dates[idx - 1]     # T日 (数据产生日)
            t_plus_2_date = trade_dates[idx + 1] # T+2日 (卖出日)
        except (ValueError, IndexError):
            continue
            
        if str(t_plus_1_date) >= today_str:
            continue

        try:
            df_rec = pd.read_excel(file, sheet_name='ML_Momentum_Pool')
            if df_rec.empty or 'Message' in df_rec.columns:
                comp_equity_curve.append({"date": t_plus_1_date, "equity": comp_equity})
                continue
                
            ticker_col = 'Ticker' if 'Ticker' in df_rec.columns else ('代码' if '代码' in df_rec.columns else None)
            name_col = 'Name' if 'Name' in df_rec.columns else ('名称' if '名称' in df_rec.columns else None)
            
            if not ticker_col: continue
        except Exception:
            continue

        picks = df_rec.head(4) # 取前4只
        if picks.empty: 
            comp_equity_curve.append({"date": t_plus_1_date, "equity": comp_equity})
            continue
        
        comp_daily_pnl = 0.0
        comp_allocated_capital = comp_equity / len(picks)
        
        print(f"[{t_plus_1_date}] 验证 {len(picks)} 只标的...")
        
        for _, stock in picks.iterrows():
            code = str(stock[ticker_col]).zfill(6)
            name = stock[name_col] if name_col else 'Unknown'
            
            res = evaluate_trade_strict(code, t_date, t_plus_1_date, t_plus_2_date)
            
            if res["status"] == "executed":
                buy_p = res["buy_price"]
                sell_p = res["sell_price"]
                
                # 收益率 (扣除综合成本: 印花税+佣金=约0.16%)
                pnl_pct = (sell_p - buy_p) / buy_p - 0.0016
                
                # 复利结算
                comp_daily_pnl += comp_allocated_capital * pnl_pct
                
                # 绝对金额结算
                shares = (FIXED_CAPITAL_PER_STOCK / buy_p) // 100 * 100
                buy_amount = shares * buy_p
                sell_amount = shares * sell_p
                fee = (buy_amount + sell_amount) * 0.0002 + sell_amount * 0.0005 # 双向万二 + 卖出千0.5印花税
                abs_profit = sell_amount - buy_amount - fee
                total_absolute_profit += abs_profit
                
                trade_logs.append({
                    "T日": t_date, "买入日": t_plus_1_date, "卖出日": t_plus_2_date, 
                    "代码": code, "名称": name, "状态": "成交", 
                    "买入价": buy_p, "卖出价": sell_p, 
                    "收益率": pnl_pct, "净利润(元)": abs_profit,
                    "备注": res.get("note", "")
                })
                print(f"    🟢 [成交] {name}({code}) -> 净利润: {abs_profit:,.2f}元 ({pnl_pct*100:.2f}%)")
                
            elif res["status"] == "cancelled":
                trade_logs.append({
                    "T日": t_date, "买入日": t_plus_1_date, "卖出日": t_plus_2_date, 
                    "代码": code, "名称": name, "状态": "撤单", 
                    "收益率": 0.0, "净利润(元)": 0.0,
                    "备注": res['reason']
                })
                print(f"    🛡️ [撤单] {name}({code}) -> {res['reason']}")
            else:
                print(f"    ⚠️ [异常] {name}({code}) -> {res['reason']}")
                
        comp_equity += comp_daily_pnl
        comp_equity_curve.append({"date": t_plus_1_date, "equity": comp_equity})

    # ================= 结果统计与可视化 =================
    if not comp_equity_curve: return

    df_curve = pd.DataFrame(comp_equity_curve)
    df_curve['date'] = pd.to_datetime(df_curve['date'])
    df_logs = pd.DataFrame(trade_logs)
    
    # --- 指标计算 ---
    final_equity = df_curve['equity'].iloc[-1]
    total_return = (final_equity / COMPOUND_CAPITAL) - 1
    rolling_max = df_curve['equity'].cummax()
    max_drawdown = ((df_curve['equity'] - rolling_max) / rolling_max).min()
    
    executed = df_logs[df_logs["状态"] == "成交"] if not df_logs.empty else pd.DataFrame()
    cancelled = df_logs[df_logs["状态"] == "撤单"] if not df_logs.empty else pd.DataFrame()
    win_rate = len(executed[executed["净利润(元)"] > 0]) / len(executed) if len(executed) > 0 else 0
    
    print("\n" + "="*45)
    print("          📈 统一回测综合报告         ")
    print("="*45)
    print("【复利模式 (10万起步)】")
    print(f"期初资金: \t{COMPOUND_CAPITAL:,.2f} 元")
    print(f"期末资金: \t{final_equity:,.2f} 元")
    print(f"总收益率: \t{total_return*100:.2f}%")
    print(f"最大回撤: \t{max_drawdown*100:.2f}%")
    print("-" * 45)
    print("【绝对金额模式 (单只固定 100万)】")
    print(f"总计净利润: \t¥ {total_absolute_profit:,.2f}")
    if not executed.empty:
        print(f"单笔最大盈利: \t¥ {executed['净利润(元)'].max():,.2f}")
        print(f"单笔最大亏损: \t¥ {executed['净利润(元)'].min():,.2f}")
    print("-" * 45)
    print("【交易统计】")
    print(f"推票总数: \t{len(df_logs)} 只")
    print(f"触发撤单: \t{len(cancelled)} 只 (保护率 {len(cancelled)/max(len(df_logs),1)*100:.1f}%)")
    print(f"真实买入: \t{len(executed)} 只")
    print(f"交易胜率: \t{win_rate*100:.2f}%")
    print("="*45)

    # 导出日志
    out_file = os.path.join(PROJECT_ROOT, 'output', f"回测综合详单_{today_str}.xlsx")
    os.makedirs(os.path.dirname(out_file), exist_ok=True)
    df_logs.to_excel(out_file, index=False)
    print(f"\n✅ 综合回测详单已保存: {out_file}")

    # 绘图设计
    plt.rcParams['font.sans-serif'] = ['SimHei', 'Arial Unicode MS']
    plt.rcParams['axes.unicode_minus'] = False
    
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 10), gridspec_kw={'height_ratios': [2, 1]})
    
    # 1. 资金曲线 (复利)
    ax1.plot(df_curve['date'], df_curve['equity'], marker='o', color='#d62728', linewidth=2.5, label='复利曲线')
    ax1.axhline(COMPOUND_CAPITAL, color='gray', linestyle='--')
    ax1.fill_between(df_curve['date'], df_curve['equity'], rolling_max, color='#e74c3c', alpha=0.15, label='回撤区间')
    ax1.set_title('资金复利曲线 (Open Limit-Up Buy -> Next Open Sell)', fontsize=14)
    ax1.grid(True, alpha=0.5)
    ax1.legend()
    
    # 2. 绝对盈亏柱状图 (以平仓日为准)
    if not executed.empty:
        daily_profit = executed.groupby('卖出日')['净利润(元)'].sum().reset_index()
        # 将 YYYYMMDD 转为 datetime
        daily_profit['卖出日'] = pd.to_datetime(daily_profit['卖出日'])
        colors = ['#2ca02c' if x > 0 else '#d62728' for x in daily_profit['净利润(元)']]
        ax2.bar(daily_profit['卖出日'], daily_profit['净利润(元)'], color=colors, alpha=0.7)
        ax2.yaxis.set_major_formatter(ticker.StrMethodFormatter('{x:,.0f}'))
        ax2.set_title('每日实现净利润 (固定100万/只)', fontsize=12)
        ax2.axhline(0, color='black', linewidth=0.8)
        ax2.grid(True, alpha=0.3, axis='y')
    else:
        ax2.set_title('无成交记录', fontsize=12)

    plt.tight_layout()
    img_file = os.path.join(PROJECT_ROOT, 'output', f"回测综合报告_{today_str}.png")
    plt.savefig(img_file, dpi=300, bbox_inches='tight')
    print(f"✅ 可视化报告已保存: {img_file}")

if __name__ == "__main__":
    pd.options.mode.chained_assignment = None
    main()