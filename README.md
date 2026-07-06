# Alpha Sealing Predictor (A股连板晋级量化预测系统)

![Python](https://img.shields.io/badge/python-3.12+-blue.svg)
![License](https://img.shields.io/badge/license-MIT-green.svg)
![AkShare](https://img.shields.io/badge/framework-AkShare-orange.svg)

**AI-Quant System**: 基于机器学习与动态超参数优化的 A 股打板及连板晋级预测系统。

本系统专门针对 A 股的“打板”逻辑与短线情绪周期开发。利用机器学习（如 Random Forest）结合贝叶斯优化，系统能在每日盘后自动分析涨停个股的封板质量、筹码结构和板块情绪，并在次日开盘前输出具有高晋级潜力的核心标的池。系统引入了动态时间衰减权重 (λ) 与高仿真撤单保护机制，力求还原真实交易场景下的超额收益 (Alpha)。

## 核心逻辑 (The Logic)

A 股短线打板交易的核心在于资金接力与情绪传导，但传统人工复盘容易受主观偏见影响。系统将盘口语言转化为高维特征工程，通过机器学习提取非线性的晋级规律。

**核心算法机制 (Algorithm Pipeline)**：
1. **多维特征工程 (Advanced Feature Engineering)**:
   - **封板质量 (Sealing Quality)**: 计算“封板资金 / 当日成交额”，量化多头锁仓力度；记录“首次封板分钟”，区分早盘秒板与尾盘偷袭的能量等级。
   - **筹码与席位 (Chips & Seats)**: 扫描近期龙虎榜，量化活跃营业部（知名游资）的介入深度；统计“炸板次数”，衡量日内筹码交换的剧烈程度。
   - **热点强度 (Sentiment)**: 基于行业板块涨跌幅及领涨股表现的 Z-Score 标准化得分。
   - **非线性惩罚 (Exponential Penalty)**: 引入指数惩罚函数，对连板数过高的“妖股”进行期望值修正，规避见顶风险。
2. **动态超参数优化 (Dynamic Optimization)**:
   - **贝叶斯搜索 (Bayesian Optimization)**: 通过贝叶斯迭代寻找 `n_estimators` 与 `max_depth` 的最优组合，提升模型在不同市场阶段的泛化能力。
   - **自适应时间权重 (λ)**: 通过蒙特卡洛模拟动态计算 λ 值，使模型能够感知市场的“短时记忆”。当市场风格剧烈切换时，系统会自动加大近期样本的权重。
3. **回测仿真机制 (High-Fidelity Simulation)**:
   - **T-1 预测 -> T 买入 -> T+1 卖出** 逻辑，严格杜绝未来函数。
   - 引入“撤单保护策略”，若标的当日未封死涨停，则模拟早盘撤单成功或未成交，收益计 0%，高度还原实战防守动作。

## 目录结构 (Project Structure)

基于模块化与整洁架构设计，系统划分为 5 个核心基础目录：

- 📁 **`src/`** (核心源码)
  - 核心算法库、因子工程、模型优化及缓存管理工具 (`strategy_utils.py` 等)
- 📁 **`scripts/`** (独立运行入口)
  - 生产执行 (`daily_run.py`)：每日盘后复盘及次日名单生成
  - 仿真回测 (`backtest_run.py`, `daily_backtest.py`)：离线测试与资产曲线生成
  - 自动化机器人 (`midnight_bot.py`)：盘前自动化定时任务
- 📁 **`data/`** (数据管理)
  - `data_cache/`：本地行情 CSV 缓存库 (由系统自动维护)
  - `records/`：历史推荐名单与预测记录
- 📁 **`output/`** (报表归档)
  - 存放系统自动生成的预测 Excel 表格 (`明日_*.xlsx`) 与 PDF 分析报告
- 📁 **`notebooks/`** (交互式探索)
  - Jupyter Notebook 环境 (`Interactive-1.ipynb` 等)，用于因子探索与临时调试

## 数据来源 (Data Sources)

所有量化数据与行情切片均通过开源数据接口 **AkShare** 抓取，并利用本地文件系统构建高效的高速缓存，减少重复网络请求。

## 部署与运行 (Usage)

系统提供独立运行入口，主要支持以下功能模式：

```bash
# 1. 下载代码到本地
git clone https://github.com/您的用户名/alpha_sealing.git

# 2. 进入项目目录
cd alpha_sealing

# 3. 安装必备依赖 (Python 3.12+)
pip install -r requirements.txt

# 4. 每日运行预测模型 (盘后生成次日推荐)
python scripts/daily_run.py

# 5. 运行最近历史回测并生成评估报告
python scripts/daily_backtest.py
```

## 如何贡献代码 (How to Contribute)

欢迎开源社区贡献代码！本项目遵循标准的 GitHub 开源工作流：
1. **Fork 本仓库**：复制项目到你的账号下。
2. **克隆到本地**：`git clone https://github.com/你的用户名/alpha_sealing.git`
3. **创建分支**：`git checkout -b feature/your-feature-name`
4. **提交代码**：`git commit -m 'Add new alpha factors'`
5. **推送到你的仓库**：`git push origin feature/your-feature-name`
6. **发起 Pull Request (PR)**：在主仓库发起 PR，审核通过后合并。

---
* **开源协议 (License)**: 本项目采用 **MIT License** 开源。
* **免责声明 (Disclaimer)**: 本系统仅供量化交易研究与学术交流使用，不构成任何投资建议。股市有风险，入市需谨慎。开发者不对任何因使用本项目代码及预测结果而导致的财务损失负责。
