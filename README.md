Alpha Sealing Predictor (A股连板晋级预测系统)

![alt text](https://img.shields.io/badge/python-3.12+-blue.svg)

![alt text](https://img.shields.io/badge/license-MIT-green.svg)

![alt text](https://img.shields.io/badge/framework-AkShare-orange.svg)

1. 项目简介
Alpha Sealing Predictor 是一个专门针对 A 股“打板”逻辑开发的量化研究框架。系统利用机器学习（Random Forest）结合贝叶斯优化，分析每日涨停个股在次日的晋级潜力。本项目的特色在于引入了动态时间衰减权重 (λ) 以及高仿真撤单保护逻辑，旨在还原真实交易场景下的超额收益。


2. 项目目录结构

hit_quant/
├── .gitignore               # 忽略缓存、日志及本地生成的数据文件
├── README.md                # 项目指南 (本文件)
├── requirements.txt         # 依赖清单 (akshare, sklearn, openpyxl, etc.)
├── strategy_utils.py        # 核心算法库：包含因子工程、模型优化及缓存管理
├── daily_run.py             # 生产执行：每日盘后复盘及次日名单生成
├── daily_backtest.py        # 仿真回测：基于本地历史推荐文件的离线测试
└── data_cache/              # 本地数据库：存储行情 CSV 文件 (由系统自动维护)


3. 底层技术逻辑
3.1 因子工程 (Factor Engineering)
系统构建了上百个高维量化因子，涵盖筹码面、技术面及情绪面：
因子小样
	•	封板质量 (Sealing Quality)：
	◦	因子_封金比：计算 封板资金 / 当日成交额。量化多头锁仓力度，是次日高开溢价的核心指标。
	◦	因子_首次封板分钟：记录早盘首次封板时间。9:45 前封板与 14:30 后封板的能量等级具有显著差异。
	•	筹码与席位 (Chips & Seats)：
	◦	因子_席位：扫描过去 3 日龙虎榜，量化活跃营业部（知名游资）的介入深度。
	◦	因子_炸板次数：衡量日内筹码交换的剧烈程度。
	•	热点强度 (Sentiment)：
	◦	因子_板块强度：基于行业板块涨跌幅及领涨股表现的 Z-Score 标准化得分。
	•	非线性惩罚：
	◦	因子_有效连板数：引入指数惩罚函数，对连板数过高的妖股进行期望值修正，规避见顶风险。
3.2 动态超参数优化
	•	贝叶斯搜索 (Bayesian Optimization)： 系统不使用默认的随机森林参数，而是通过贝叶斯迭代寻找 n_estimators（决策树数量）与 max_depth（树深度）的最优组合，提升模型的泛化能力。
	•	自适应时间权重 (λ)： 系统通过蒙特卡洛模拟动态计算 λ 值，使模型能够感知市场的“短时记忆”。当市场风格剧烈切换时，模型会自动加大近期样本的权重。


4. 回测仿真机制
4.1 严格的时间轴对齐
系统严格杜绝“未来函数”，遵循 T-1 预测 -> T 买入 -> T+1 卖出 的逻辑：
	1	复盘日 (T-1)：生成预测 Excel 文件。
	2	买入日 (T)：
	◦	买入：以 T日开盘价买入。
	◦	撤单判定：观察 T日收盘。若股票未封死涨停（最高价 ≠收盘价），回测逻辑认为交易员在早盘撤单成功或未成交，当日收益计为 0%。
	3	卖出日 (T+1)：以  T+1日开盘价强制平仓。
4.2 交易摩擦模拟
	•	仓位管理：默认将初始资金 4 等分（单只个股 25% 仓位）。
	•	费用计算：包含买入佣金（0.03%）、卖出佣金（0.03%）及卖出印花税（0.1%）。

5. 快速开始 
5.1 环境配置
Bash

git clone https://github.com/***/hit_quant.git
cd hit_quant
pip install -r requirements.txt
mkdir data_cache
5.2 每日运行
在 VS Code 中打开 daily_run.py，运行 Run Cell。系统将：
	1	自动识别最新交易日。
	2	更新本地缓存数据库。
	3	训练模型并生成 明日推荐_YYYYMMDD.xlsx。
5.3 运行回测
在生成若干份推荐文件后，运行 daily_backtest.py。 系统将自动绘制 “全买策略 (Strategy A)” 与 “撤单保护策略 (Strategy B)” 的资产曲线对比图，并输出详细的 PDF/Excel 报告。

6. 免责声明 (Disclaimer)
本项仅供量化交易研究与学术交流使用，不构成任何投资建议。股市有风险，入市需谨慎。开发者不对任何因使用本项目代码导致的财务损失负责。

Author: Sean Wong License: MIT License
