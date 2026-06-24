# backtest_run.py
import pandas as pd
import akshare as ak
import matplotlib.pyplot as plt
from datetime import datetime
import os
import glob
import time

def get_trade_dates():
    """获取所有交易日历"""
    trade_dates_df = ak.tool_trade_date_hist_sina()
    return trade_dates_df["trade_date"].astype(str).str.replace("-", "").tolist()

def check_is_limit_up(code_str, prev_close, buy_open):
    """
    [用户自定义拟合逻辑]
    通过 T-1 收盘价和 T 日开盘价，判断涨幅是否在涨停区间。
    创业板/科创板：[19.8%, 20.2%]
    主板：[9.8%, 10.2%]
    """
    pct = (buy_open - prev_close) / prev_close * 100
    if code_str.startswith(('30', '68')):
        return 19.8 <= pct <= 20.2
    else:
        return 9.8 <= pct <= 10.2

def evaluate_trade(code, buy_date, sell_date, trade_dates):
    """
    极速 K 线验证模块
    只请求包含 T日、T+1、T+2 的超小切片数据（几行数据，零延迟，绝对不会断联）
    """
    code_str = str(code).zfill(6)
    
    # 往前推 5 个交易日作为 start_date，防止股票在 T 日停牌找不到昨收价
    try:
        idx = trade_dates.index(buy_date)
        start_date = trade_dates[idx - 5]
    except:
        return {"status": "error", "reason": "日期异常"}

    # 1. 轻量化请求，带 3 次断线重连
    for attempt in range(3):
        try:
            # 【核心修正】：指定 start_date 和 end_date，数据量极小，极速返回！
            df = ak.stock_zh_a_hist(
                symbol=code_str, 
                period="daily", 
                start_date=start_date, 
                end_date=sell_date, 
                adjust=""  # 必须不复权
            )
            if not df.empty:
                break
        except Exception as e:
            time.sleep(1)
    else:
        return {"status": "error", "reason": "API拉取失败"}

    if df.empty:
        return {"status": "error", "reason": "无交易数据"}

    df['date_key'] = df['日期'].astype(str).str.replace("-", "")
    
    # 2. 定位关键数据
    buy_row = df[df['date_key'] == buy_date]
    sell_row = df[df['date_key'] == sell_date]
    
    if buy_row.empty:
        return {"status": "error", "reason": "买入日停牌或无数据"}

    # 获取买入日之前的最后一天作为“昨收价” (完美兼容复牌股票)
    history_before_buy = df[df['date_key'] < buy_date]
    if history_before_buy.empty:
        return {"status": "error", "reason": "缺失昨收价数据"}
        
    prev_close = float(history_before_buy.iloc[-1]['收盘'])
    buy_open = float(buy_row.iloc[0]['开盘'])
    buy_high = float(buy_row.iloc[0]['最高'])
    buy_close = float(buy_row.iloc[0]['收盘'])

    # 3. 执行撤单判定逻辑
    # 判定一：开盘价是否达到了拟合的涨停区间
    if not check_is_limit_up(code_str, prev_close, buy_open):
        pct = (buy_open - prev_close) / prev_close * 100
        return {"status": "cancelled", "reason": f"开盘未涨停 (涨幅: {pct:.2f}%)"}
        
    # 判定二：开盘是否封死 (开盘价 == 全天最高价)
    if buy_open < buy_high - 0.01:
        return {"status": "cancelled", "reason": "开盘未封死被砸 (Open < High)"}

    # 4. 模拟卖出盈亏
    if sell_row.empty:
        # 如果卖出日停牌，按买入日的收盘价强行结算
        pnl = (buy_close - buy_open) / buy_open - 0.0016
        return {"status": "executed", "pnl": pnl, "note": "次日停牌"}

    sell_open = float(sell_row.iloc[0]['开盘'])
    # 计算扣除万三买卖 + 千一印花税 后的净收益
    pnl = (sell_open - buy_open) / buy_open - 0.0016
    
    return {"status": "executed", "pnl": pnl, "note": "正常卖出"}


def main():
    print("="*60)
    print("   🚀 极速本地 Excel 步进回测引擎 (动态拟合涨停版)   ")
    print("="*60)
    
    excel_files = glob.glob("明日_*.xlsx")
    excel_files.sort()
    
    if not excel_files:
        print("❌ 未找到任何 '明日_*.xlsx' 文件。")
        return
        
    print(f"✅ 扫描到 {len(excel_files)} 个历史预测文件，开始全量回测...\n")

    trade_dates = get_trade_dates()
    today_str = datetime.now().strftime("%Y%m%d")

    INITIAL_CAPITAL = 100000.0
    equity = INITIAL_CAPITAL
    equity_curve = []
    trade_logs = []

    for file in excel_files:
        filename = os.path.basename(file)
        buy_date = "".join([c for c in filename if c.isdigit()]) # 这是我们要买入的 T 日
        
        try:
            idx = trade_dates.index(buy_date)
            sell_date = trade_dates[idx + 1] # 次日开盘卖出
        except (ValueError, IndexError):
            continue
            
        if str(buy_date) >= today_str:
            continue

        try:
            df_rec = pd.read_excel(file, sheet_name='ML_Momentum_Pool')
            if df_rec.empty or 'Message' in df_rec.columns:
                equity_curve.append({"date": buy_date, "equity": equity})
                continue
                
            ticker_col = 'Ticker' if 'Ticker' in df_rec.columns else ('代码' if '代码' in df_rec.columns else None)
            name_col = 'Name' if 'Name' in df_rec.columns else ('名称' if '名称' in df_rec.columns else None)
            
            if not ticker_col: continue
        except Exception:
            continue

        picks = df_rec.head(4)
        if picks.empty: continue
        
        daily_pnl = 0.0
        allocated_capital = equity / len(picks) 
        
        print(f"[{buy_date}] 验证 {len(picks)} 只标的...")
        
        for _, stock in picks.iterrows():
            code = str(stock[ticker_col]).zfill(6)
            name = stock[name_col] if name_col else 'Unknown'
            
            # 直接调用我们上面写的极速切片函数
            res = evaluate_trade(code, buy_date, sell_date, trade_dates)
            
            if res["status"] == "executed":
                pnl = res["pnl"]
                daily_pnl += allocated_capital * pnl
                trade_logs.append({
                    "Buy_Date": buy_date, "Sell_Date": sell_date, "Ticker": code, "Name": name, 
                    "Status": "成交并卖出", "PnL(%)": round(pnl*100, 2), "Reason": res.get("note", "")
                })
                print(f"    🟢 [成交] {name}({code}) -> PnL: {pnl*100:.2f}%")
                
            elif res["status"] == "cancelled":
                trade_logs.append({
                    "Buy_Date": buy_date, "Sell_Date": sell_date, "Ticker": code, "Name": name, 
                    "Status": "9:20撤单", "PnL(%)": 0, "Reason": res['reason']
                })
                print(f"    🛡️ [撤单] {name}({code}) -> {res['reason']}")
            else:
                print(f"    ⚠️ [异常] {name}({code}) -> {res['reason']}")
                
        equity += daily_pnl
        equity_curve.append({"date": buy_date, "equity": equity})

    # ================= 结果统计与可视化 =================
    if not equity_curve: return

    df_curve = pd.DataFrame(equity_curve)
    df_curve['date'] = pd.to_datetime(df_curve['date'])
    df_logs = pd.DataFrame(trade_logs)
    
    final_equity = df_curve['equity'].iloc[-1]
    total_return = (final_equity / INITIAL_CAPITAL) - 1
    
    rolling_max = df_curve['equity'].cummax()
    max_drawdown = ((df_curve['equity'] - rolling_max) / rolling_max).min()
    
    executed = df_logs[df_logs["Status"].str.contains("成交")] if not df_logs.empty else pd.DataFrame()
    cancelled = df_logs[df_logs["Status"].str.contains("撤单")] if not df_logs.empty else pd.DataFrame()
    win_rate = len(executed[executed["PnL(%)"] > 0]) / len(executed) if len(executed) > 0 else 0
    
    print("\n" + "="*45)
    print("          📈 极速实盘文件回测报告         ")
    print("="*45)
    print(f"期初资金: \t{INITIAL_CAPITAL:,.2f} 元")
    print(f"期末资金: \t{final_equity:,.2f} 元")
    print(f"总收益率: \t{total_return*100:.2f}%")
    print(f"最大回撤: \t{max_drawdown*100:.2f}%")
    print("-" * 45)
    print(f"推票总数: \t{len(df_logs)} 只")
    print(f"触发撤单: \t{len(cancelled)} 只 (保护率 {len(cancelled)/max(len(df_logs),1)*100:.1f}%)")
    print(f"真实买入: \t{len(executed)} 只")
    print(f"交易胜率: \t{win_rate*100:.2f}%")
    print("="*45)

    # 导出
    out_file = f"回测详单_{today_str}.xlsx"
    df_logs.to_excel(out_file, index=False)
    print(f"\n✅ 详单已保存: {os.path.abspath(out_file)}")

    plt.figure(figsize=(12, 6))
    plt.plot(df_curve['date'], df_curve['equity'], marker='o', color='#2980b9', linewidth=2.5)
    plt.axhline(INITIAL_CAPITAL, color='gray', linestyle='--')
    plt.fill_between(df_curve['date'], df_curve['equity'], rolling_max, color='#e74c3c', alpha=0.15)
    plt.title('Walk-Forward Backtest (Open Limit-Up Buy -> Next Open Sell)', fontsize=14)
    plt.grid(True, alpha=0.5)
    plt.gcf().autofmt_xdate()
    
    img_file = f"回测资金曲线_{today_str}.png"
    plt.savefig(img_file, dpi=300, bbox_inches='tight')
    plt.show()

if __name__ == "__main__":
    pd.options.mode.chained_assignment = None
    main()