import os
import time
import pandas as pd
import numpy as np
import akshare as ak

import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
from datetime import datetime, timedelta

# ==========================================
# 1. 基础设置与辅助函数
# ==========================================
plt.rcParams['font.sans-serif'] = ['SimHei', 'Arial Unicode MS']
plt.rcParams['axes.unicode_minus'] = False

def get_recent_30_trade_dates():
    cal = ak.tool_trade_date_hist_sina()
    cal['trade_date'] = pd.to_datetime(cal['trade_date']).dt.strftime('%Y%m%d')
    today = datetime.now().strftime('%Y%m%d')
    past_dates = cal[cal['trade_date'] <= today]['trade_date'].tolist()
    return past_dates[-35:]

def calculate_limit_up_price(stock_code, prev_close):
    stock_code = str(stock_code).zfill(6)
    if stock_code.startswith('688') or stock_code.startswith('300'):
        limit_ratio = 0.20
    else:
        limit_ratio = 0.10
    limit_price = int(prev_close * (1 + limit_ratio) * 100 + 0.5) / 100.0
    return limit_price

def extract_6digit_code(ticker):
    return ''.join(filter(str.isdigit, str(ticker)))[-6:]

# ==========================================
# 2. 核心回测逻辑 (严格一字不差还原第一版代码)
# ==========================================
def run_backtest(days=30):
    trade_dates = get_recent_30_trade_dates()
    target_dates = trade_dates[-(days+1):-1]
    
    trade_records = []
    
    print(f"--- 开始执行回测 (回溯 {days} 个交易日) ---")
    
    for i, t_date in enumerate(target_dates):
        file_name = f"明日_{t_date}.xlsx"
        
        if not os.path.exists(file_name):
            continue
            
        try:
            df_pool = pd.read_excel(file_name, sheet_name='ML_Momentum_Pool')
        except Exception as e:
            continue
            
        if df_pool.empty or "Ticker" not in df_pool.columns:
            continue
            
        start_date_str = trade_dates[trade_dates.index(t_date) - 5]
        end_date_str = trade_dates[min(len(trade_dates)-1, trade_dates.index(t_date) + 3)]
        
        for _, row in df_pool.iterrows():
            ticker_val = row['Ticker']
            code = extract_6digit_code(ticker_val)
            name = row.get('Name', 'Unknown')
            
            try:
                hist_data = ak.stock_zh_a_hist(
                    symbol=code, 
                    period="daily", 
                    start_date=start_date_str, 
                    end_date=end_date_str, 
                    adjust="qfq"
                )
            except Exception as e:
                continue
                
            if hist_data.empty: continue
            
            hist_data['日期'] = pd.to_datetime(hist_data['日期']).dt.strftime('%Y%m%d')
            hist_data.reset_index(drop=True, inplace=True)
            
            t_idx_list = hist_data[hist_data['日期'] == t_date].index.tolist()
            if not t_idx_list: continue
            t_idx = t_idx_list[0]
            
            if t_idx == 0 or t_idx == len(hist_data) - 1:
                continue 
                
            prev_close = hist_data.loc[t_idx - 1, '收盘']
            t_open = hist_data.loc[t_idx, '开盘']
            t_next_close = hist_data.loc[t_idx + 1, '收盘']
            t_next_date = hist_data.loc[t_idx + 1, '日期']
            
            limit_up_price = calculate_limit_up_price(code, prev_close)
            
            if abs(t_open - limit_up_price) > 0.015:
                record = {
                    '买入日': t_date, '代码': code, '名称': name,
                    '状态': '撤单 (未开在封板价)',
                    '预期买价': limit_up_price, '实际开盘': t_open,
                    '收益率': 0.0
                }
            else:
                buy_price = t_open
                sell_price = t_next_close
                pnl_pct = (sell_price - buy_price) / buy_price
                
                record = {
                    '买入日': t_date, '卖出日': t_next_date,
                    '代码': code, '名称': name,
                    '状态': '成交',
                    '买入价': buy_price, '卖出价': sell_price,
                    '收益率': pnl_pct
                }
            trade_records.append(record)
            time.sleep(0.1) 
            
    return pd.DataFrame(trade_records)

# ==========================================
# 3. 绘图与分析报告 (在这里将结算改成绝对金额+卖出日)
# ==========================================
def plot_backtest_results(df):
    if df.empty:
        print("没有产生任何交易记录。")
        return
        
    traded_df = df[df['状态'] == '成交'].copy()
    
    print("\n" + "="*45)
    print("           回 测 统 计 报 告")
    print("="*45)
    print(f"信号触发总数: {len(df)} 只")
    print(f"实际达成交易: {len(traded_df)} 只")
    print(f"未封板被撤单: {len(df) - len(traded_df)} 只")
    
    if traded_df.empty:
        print("\n注: 没有股票满足开盘封板的条件，无收益曲线。")
        return
        
    # --- 开始资金结算逻辑 (基于卖出金额-买入金额) ---
    capital_per_stock = 1000000
    fee_rate = 0.0002
    
    # 向下取整买入整数股
    traded_df['实际买入股数'] = (capital_per_stock / traded_df['买入价']) // 100 * 100
    traded_df['买入金额'] = traded_df['实际买入股数'] * traded_df['买入价']
    traded_df['卖出金额'] = traded_df['实际买入股数'] * traded_df['卖出价']
    traded_df['手续费合计'] = (traded_df['买入金额'] + traded_df['卖出金额']) * fee_rate
    
    # 核心：真正的绝对净利润结算
    traded_df['净利润(元)'] = traded_df['卖出金额'] - traded_df['买入金额'] - traded_df['手续费合计']
    # ------------------------------------------------
    
    total_profit = traded_df['净利润(元)'].sum()
    win_trades = traded_df[traded_df['净利润(元)'] > 0]
    win_rate = len(win_trades) / len(traded_df) if len(traded_df) > 0 else 0
    
    print("-" * 45)
    print(f"总计净利润: ¥ {total_profit:,.2f}")
    print(f"交易胜率: {win_rate:.2%}")
    print(f"单笔最大盈利: ¥ {traded_df['净利润(元)'].max():,.2f}")
    print(f"单笔最大亏损: ¥ {traded_df['净利润(元)'].min():,.2f}")
    print("="*45)
    
    # 按【卖出日】汇总每天平仓的盈亏
    daily_profit = traded_df.groupby('卖出日')['净利润(元)'].sum().reset_index()
    daily_profit.sort_values('卖出日', inplace=True)
    daily_profit['累计总利润'] = daily_profit['净利润(元)'].cumsum()
    
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 10), gridspec_kw={'height_ratios': [2, 1]})
    
    # 1. 资金曲线图 (按平仓日)
    ax1.plot(daily_profit['卖出日'], daily_profit['累计总利润'], marker='o', color='#d62728', linewidth=2, label='累计总净利润')
    ax1.axhline(0, color='gray', linestyle='--', linewidth=1)
    ax1.yaxis.set_major_formatter(ticker.StrMethodFormatter('{x:,.0f}'))
    
    ax1.set_title('策略累计总利润曲线 (单只100万 | 双向万二 | 按平仓结算日)', fontsize=14)
    ax1.set_ylabel('累计利润 (元)')
    ax1.grid(True, alpha=0.3)
    ax1.legend()
    ax1.tick_params(axis='x', rotation=45)
    
    # 2. 每日单笔收益柱状图
    colors = ['#2ca02c' if x > 0 else '#d62728' for x in daily_profit['净利润(元)']]
    ax2.bar(daily_profit['卖出日'], daily_profit['净利润(元)'], color=colors, alpha=0.7)
    ax2.yaxis.set_major_formatter(ticker.StrMethodFormatter('{x:,.0f}'))
    ax2.set_title('每日实现净利润 (卖出平仓日)', fontsize=12)
    ax2.set_ylabel('单日平仓盈亏 (元)')
    ax2.axhline(0, color='black', linewidth=0.8)
    ax2.grid(True, alpha=0.3, axis='y')
    ax2.tick_params(axis='x', rotation=45)
    
    plt.tight_layout()
    plt.show()

# ==========================================
# 执行
# ==========================================
if __name__ == "__main__":
    results_df = run_backtest(days=30)
    
    if not results_df.empty:
        results_df.to_excel("回测详细流水_绝对金额版.xlsx", index=False)
        print("回测明细已保存至 -> 回测详细流水_绝对金额版.xlsx")
        
    plot_backtest_results(results_df)