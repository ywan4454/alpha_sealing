# %% [1] Setup and System Initialization
# %load_ext autoreload
# %autoreload 2

import akshare as ak
import pandas as pd
from datetime import datetime
import sys, os
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.append(PROJECT_ROOT)
from src.strategy_utils import *

t_date, target_date = get_market_dates()
print(f"--- SYSTEM INITIALIZED ---")
print(f"T-Date (Data Base): {t_date}")
print(f"Target Date (Trade): {target_date}")

# %% [2] Training Pipeline & Model Generation
print("PIPELINE: Loading historical data and training model...")

# 1. 准备训练集
all_dates = get_recent_trade_dates(10) 
all_hist_data = []
for i in range(len(all_dates)-1):
    d_prev, d_curr = all_dates[i], all_dates[i+1]
    zt_prev = fetch_data_with_cache("zt_pool", d_prev, ak.stock_zt_pool_em, date=d_prev)
    zt_curr = fetch_data_with_cache("zt_pool", d_curr, ak.stock_zt_pool_em, date=d_curr)
    
    if zt_prev.empty or zt_curr.empty: continue
    
    zt_curr_codes = set(zt_curr["代码"].unique())
    zt_prev["Label"] = zt_prev["代码"].apply(lambda x: 1 if x in zt_curr_codes else 0)
    zt_prev["日期"] = d_prev
    all_hist_data.append(zt_prev)

train_full = pd.concat(all_hist_data) if all_hist_data else pd.DataFrame()

# 2. 模型训练 (生成 scaler 和 clf)
today_zt = fetch_data_with_cache("zt_pool", t_date, ak.stock_zt_pool_em, date=t_date)

# ==========================================
# 【新增过滤步骤 1】：清洗今日涨停基础数据，踢出垃圾股和监管黑名单
# ==========================================
today_zt = filter_valid_a_shares(today_zt)
today_zt = filter_regulatory_inquiries(today_zt, t_date, lookback_days=10)

clf, scaler = modeling_demo_2_new(today_zt, t_date, train_full)
print("RESULT: Model training completed successfully.")

# %% [3] Prediction, Scan, and Export
print("PIPELINE: Running prediction and event scan...")

# 1. 预测
today_processed, X_pred = factor_engineering_for_tomorrow_new(today_zt, t_date)
X_pred_scaled = scaler.transform(X_pred.values)
today_processed["Success_Prob"] = clf.predict_proba(X_pred_scaled)[:, 1]
today_processed["Final_Score"] = today_processed.apply(
    lambda row: min(0.99, row["Success_Prob"] + apply_client_preference_bonus(row)), axis=1
)
today_processed["Success_Prob"] = today_processed["Final_Score"]

print("\n=== 全市场 ML 预测评分前 20 (筛选前) ===")
# 假设我们关注这些核心指标
display_cols = ["代码", "名称", "Success_Prob", "Factor_Lianban_Height", "流通市值_亿", "封板金额_亿"]
if not today_processed.empty:
    top_20_all = today_processed.sort_values(by="Success_Prob", ascending=False).head(20)
    print(top_20_all[display_cols])
else:
    print("今日打板池经过合规过滤后无候选标的。")

final_ml_pool = select_2_each_market(today_processed) if not today_processed.empty else pd.DataFrame()

# 2. 事件扫描
print("PIPELINE: Scanning events...")
event_df = get_event_driven_pool(t_date, target_date)

# ==========================================
# 【新增过滤步骤 2】：事件驱动池（重组/复牌）也要踢出监管黑名单
# ==========================================
event_df = filter_valid_a_shares(event_df)  
event_df = filter_regulatory_inquiries(event_df, t_date, lookback_days=10)

print(f"DEBUG: 事件池扫描及合规过滤完毕，共剩余 {len(event_df) if event_df is not None else 0} 条有效数据。")

# 3. 导出报告
if not final_ml_pool.empty:
    ml_export = final_ml_pool[["代码", "名称", "Success_Prob", "Factor_Lianban_Height", "流通市值_亿", "封板金额_亿", "Is_One_Word", "所属行业"]].copy()
    ml_export.columns = ["Ticker", "Name", "ML_Success_Prob", "Limit_Height", "Market_Cap", "Sealing_Amt", "Is_One_Word_Board", "Sector"]
else:
    ml_export = pd.DataFrame(columns=["Ticker", "Name", "ML_Success_Prob", "Limit_Height", "Market_Cap", "Sealing_Amt", "Is_One_Word_Board", "Sector"])

filename = os.path.join(PROJECT_ROOT, 'output', f"明日_{target_date}.xlsx")
with pd.ExcelWriter(filename, engine='openpyxl') as writer:
    if not ml_export.empty:
        ml_export.to_excel(writer, sheet_name='ML_Momentum_Pool', index=False)
    else:
        pd.DataFrame([{"Message": "今日无符合条件的合规打板标的"}]).to_excel(
            writer, sheet_name='ML_Momentum_Pool', index=False
        )
    
    if event_df is not None and isinstance(event_df, pd.DataFrame) and not event_df.empty:
        event_df.columns = ["Ticker", "Name", "Event_Type", "Keyword", "Description", "Date"]
        event_df.to_excel(writer, sheet_name='Event_Driven_Pool', index=False)
    else:
        pd.DataFrame([{"Message": "今日无重大并购重组公告或复牌 (No major events)"}]).to_excel(
            writer, sheet_name='Event_Driven_Pool', index=False
        )

print(f"--- PROCESS COMPLETE ---")
print(f"File Saved: {filename}")

# ==========================================
# 4. 推送企业微信机器人 (Github Action 触发)
# ==========================================
webhook_url = os.environ.get("WECHAT_WEBHOOK_URL")
if webhook_url:
    print("PIPELINE: Sending WeCom Webhook...")
    bot = WeComBot(webhook_url)
    
    # 构建推送内容
    md_content = f"### 🚀 Alpha Sealing 盘后预测 ({target_date})\n\n"
    if not final_ml_pool.empty:
        md_content += "**🔥 明日打板核心标的**\n"
        for _, row in final_ml_pool.iterrows():
            md_content += f"> **{row['名称']} ({row['代码']})**\n> 晋级概率: {row['Success_Prob']*100:.1f}%\n> 封板金额: {row['封板金额_亿']}亿\n\n"
    else:
        md_content += "**🔥 明日打板核心标的**\n> 今日无符合条件的合规打板标的。\n\n"
        
    if event_df is not None and not event_df.empty:
        md_content += "**🚨 核心事件驱动 (重组/复牌)**\n"
        for _, row in event_df.head(3).iterrows():
            md_content += f"> **{row['Name']} ({row['Ticker']})** - {row['Keyword']}\n> {row['Description'][:30]}...\n\n"
            
    bot.send_markdown(md_content)
    print("RESULT: Webhook sent successfully.")
# %%