# Alpha Sealing: A-Share Limit-Up Prediction System

![Python](https://img.shields.io/badge/Python-3.12+-blue.svg)
![License](https://img.shields.io/badge/License-MIT-green.svg)
![Framework](https://img.shields.io/badge/Framework-AkShare-orange.svg)
![Contributor](https://img.shields.io/badge/Contributor-@ywan4454-red.svg)

> A quantitative prediction system for A-share "Limit-Up" (Sealing) continuation, driven by Machine Learning and Dynamic Hyperparameter Optimization.

## System Architecture

The core of A-share short-term limit-up trading lies in capital relay and sentiment transmission. This system translates order book and market sentiment dynamics into high-dimensional feature engineering, utilizing Machine Learning (e.g., Random Forest) to extract non-linear continuation patterns.

## Core Algorithm Pipeline

### [1] Advanced Feature Engineering
- Sealing Quality: Quantifies long position conviction by calculating "Sealing Capital / Daily Turnover" and recording the "First Sealing Minute".
- Chips & Seats: Scans recent Dragon Tiger List (LHB) data to gauge the depth of institutional/hot-money involvement.
- Sentiment Z-Score: Standardizes sector momentum and leading stock performance.
- Exponential Penalty: Applies exponential penalty functions to highly extended stocks to mitigate top-reversal risk.

### [2] Dynamic Optimization
- Bayesian Optimization: Iteratively searches for optimal `n_estimators` and `max_depth` combinations to enhance generalization across different market regimes.
- Adaptive Time-Decay (λ): Uses Monte Carlo simulations to dynamically compute λ, allowing the model to adapt its "short-term memory" during violent market regime shifts.

### [3] High-Fidelity Simulation
- Adheres strictly to a [T-1 Predict -> T Buy -> T+1 Sell] logic to prevent look-ahead bias.
- Introduces an "Order Cancellation Protection" mechanism: if a target fails to seal the limit-up on day T, the system simulates a successful early cancellation (0% return), highly replicating real-world defensive tactics.

## Project Structure

- `src/`: Core algorithm libraries, feature engineering, and cache management.
- `scripts/`: Execution entry points (`daily_run.py`, `backtest_run.py`, `midnight_bot.py`).
- `data/`: Local CSV cache (`data_cache/`) and historical records (`records/`).
- `output/`: Auto-generated prediction Excel reports and PDF analysis.
- `notebooks/`: Jupyter environments for exploratory data analysis.

## Deployment

Data is sourced via the open-source **AkShare** interface, utilizing a local file system cache to minimize redundant network requests.

```bash
git clone https://github.com/ywan4454/alpha_sealing.git
cd alpha_sealing
pip install -r requirements.txt

# Run daily prediction (Generates next-day recommendations post-market)
python scripts/daily_run.py

# Run historical backtest
python scripts/backtest_run.py
```

## Contributors

* Core Architect / Quant Developer: [@ywan4454](https://github.com/ywan4454)

---
Disclaimer: This system is for quantitative trading research and academic exchange only. It does not constitute financial advice. The developers are not responsible for any financial losses incurred from using this code.
