# %% [1] 导入模块
import sys, os
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.append(PROJECT_ROOT)
from src.strategy_utils import *
import schedule
import time

# 配置企业微信 Webhook
MY_WEBHOOK = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=你的KEY"
bot = WeComBot(MY_WEBHOOK)

def midnight_job():
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{now_str}] 正在执行百度股市通重组监控...")

    # 1. 抓取百度数据 (日期格式 YYYYMMDD)
    today_api_str = datetime.now().strftime("%Y%m%d")
    report, ma_df = monitor_ma_baidu(today_api_str)

    # 2. 逻辑分发：如果有重组股复牌，发 Markdown 强提醒
    if not ma_df.empty:
        # 专门挑出复牌的（潜在涨停股）
        re_open = ma_df[~pd.isna(ma_df['复牌时间'])]
        if not re_open.empty:
            md_content = f"### 🚨 重组股复牌预警\n"
            for _, row in re_open.iterrows():
                md_content += f"> **{row['股票简称']} ({row['股票代码']})**\n> 原因: {row['停牌事项说明']}\n\n"
            bot.send_markdown(md_content)
    
    # 3. 发送标准汇总报告
    bot.send_text(report)
    print(f"[{now_str}] 推送任务完成。")

# %% [2] 自动化任务调度
# 设置每天凌晨 00:01 分执行
schedule.every().day.at("00:01").do(midnight_job)

# 调试用：立即执行一次看效果
# midnight_job()

print("🤖 重组股零点监控机器人已上线...")
while True:
    schedule.run_pending()
    time.sleep(30) # 减少 CPU 占用