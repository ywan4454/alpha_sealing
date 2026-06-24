# Alpha Sealing 项目重构计划 (Refactor Plan)

根据您的需求，我分析了当前工作区中的所有 `.py` 文件、输入输出逻辑以及文件组织形式。以下是第二阶段的详细重构和整理方案，完全遵守“**绝对不修改核心策略和算法逻辑**”的原则，仅进行物理移动、模块化封装和路径调整。

## 1. 目录结构设计 (Physical File Moves)

我将创建以下 5 个基础目录，并将现有文件进行归类：

- 📁 **`src/`** (核心源码)
  - 移入：`strategy_utils.py`
  - 新建：`__init__.py` (使其成为标准 Python 模块)
- 📁 **`scripts/`** (独立运行入口)
  - 移入：`daily_run.py`, `midnight_bot.py`, `backtest_run.py`, `daily_backtest.py`, `records_run.py`
- 📁 **`output/`** (报表归档)
  - 移入：根目录下所有的 `明日_*.xlsx`、`回测*.xlsx` 等输出文件。
- 📁 **`data/`** (数据管理)
  - 移入：当前的 `data_cache/` 文件夹。
  - 移入：当前的 `records/` 文件夹。
- 📁 **`notebooks/`** (Jupyter 笔记)
  - 移入：`Interactive-1.ipynb`

## 2. 代码修改计划 (Code Modifications)

移动文件会导致原有的 `import` 引用和硬编码的读写路径失效。我需要对以下代码进行最小化修改以保证 100% 正常运行：

### 2.1 路径动态化 (Path Resolution)
为保证不管在项目根目录还是 `scripts` 目录下执行脚本都能正确识别路径，我会在涉及读写的脚本和库顶部注入自动识别根目录的代码：
```python
import os
import sys
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
```

### 2.2 `src/strategy_utils.py` 修改
- **数据缓存路径修正**：将所有硬编码的 `"data_cache/..."` 替换为动态路径：`os.path.join(PROJECT_ROOT, 'data', 'data_cache', "...")`。
- 包括函数 `filter_regulatory_inquiries`, `fetch_data_with_cache`, `get_hist_prices_cache`, `get_hist_prices_backtest_cache` 中的 `os.makedirs` 和文件读写。

### 2.3 `scripts/daily_run.py` 修改
- **模块导入修正**：增加 `sys.path.append(PROJECT_ROOT)` 并将 `from strategy_utils import *` 改为 `from src.strategy_utils import *`。
- **输出路径修正**：
  将 `filename = f"明日_{target_date}.xlsx"` 改为 `filename = os.path.join(PROJECT_ROOT, 'output', f"明日_{target_date}.xlsx")`。

### 2.4 `scripts/backtest_run.py` 修改
- **模块导入修正**：虽然没直接导入 utils，但以防万一添加 `PROJECT_ROOT` 变量。
- **读取路径修正**：`glob.glob("明日_*.xlsx")` 修改为 `glob.glob(os.path.join(PROJECT_ROOT, 'output', "明日_*.xlsx"))`。
- **输出路径修正**：`out_file` 和 `img_file` 均指向 `os.path.join(PROJECT_ROOT, 'output', ...)`。

### 2.5 `scripts/daily_backtest.py` 修改
- **读取路径修正**：`file_name = f"明日_{t_date}.xlsx"` 改为 `os.path.join(PROJECT_ROOT, 'output', f"明日_{t_date}.xlsx")`。
- **输出路径修正**：`results_df.to_excel` 保存路径指向 `os.path.join(PROJECT_ROOT, 'output', ...)`。

### 2.6 `scripts/records_run.py` 修改
- **读取路径修正**：`glob.glob("明日推荐_*.xlsx")`。由于您的历史推荐文件在 `records/` 目录下，我会将其修改为 `glob.glob(os.path.join(PROJECT_ROOT, 'data', 'records', "明日推荐_*.xlsx"))`。
- **输出路径修正**：`output_name` 指向 `output/` 目录。

### 2.7 `scripts/midnight_bot.py` 修改
- **模块导入修正**：增加 `sys.path.append` 及更改为 `from src.strategy_utils import *`。

---

**请您审查以上重构方案。如果确认无误并且同意，请告诉我“开始重构”或者“同意”，我将立即进入第三阶段，执行文件移动和代码修改！**
