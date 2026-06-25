# %% [1] Setup
import pandas as pd
import glob
import os
import akshare as ak
from datetime import datetime

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))

# %% [2] 增强型列名对齐字典 (Synonym Mapping)
# 无论你的历史文件里用了什么名字，都会统一归化
COLUMN_MAPPING = {
    # 股票代码同义词
    '代码': 'Stock_Code', 'Ticker': 'Stock_Code', 'Stock Code': 'Stock_Code',
    # 股票名称同义词
    '名称': 'Stock_Name', 'Name': 'Stock_Name', 'Company Name': 'Stock_Name',
    # 概率评分同义词
    '晋级概率': 'Alpha_Score', 'Success_Prob': 'Alpha_Score', 'Success_Probability': 'Alpha_Score', 
    'ML_Score': 'Alpha_Score', 'Alpha Model Score': 'Alpha_Score',
    # 连板高度同义词
    '因子_连板高度': 'Board_Count', 'Factor_Lianban_Height': 'Board_Count', 
    'Limit_Height': 'Board_Count', 'Consecutive Board Count': 'Board_Count', 'Board_Height': 'Board_Count',
    # 封金比同义词
    '因子_封金比': 'Sealing_Ratio', 'Factor_Sealing_Ratio': 'Sealing_Ratio', 
    'Sealing_Ratio': 'Sealing_Ratio', 'Buy Force Ratio': 'Sealing_Ratio',
    # 行业同义词
    '所属行业': 'Industry', 'Sector': 'Industry', 'Industry Sector': 'Industry'
}

# 最终呈现给客户的专业表头 (面向客户的 UI 层)
CLIENT_HEADERS = {
    'Signal_Date': 'Signal Date (T-1)',  # 明确标注这是 T-1 日的复盘信号
    'Stock_Code': 'Ticker',
    'Stock_Name': 'Name',
    'Alpha_Score': 'Prediction Score',
    'Board_Count': 'Board Count',
    'Sealing_Ratio': 'Sealing Strength',
    'Industry': 'Sector'
}

# %% [3] 核心整合逻辑
def generate_pro_master_report():
    # 1. 扫描所有推荐文件
    files = glob.glob(os.path.join(PROJECT_ROOT, 'data', 'records', "明日推荐_*.xlsx"))
    files.sort()

    if not files:
        print("Error: No daily recommendation files found.")
        return

    all_data = []

    for file in files:
        # 从文件名提取 T-1 日期 (例如: 20260320)
        filename = os.path.basename(file)
        date_str = "".join([c for c in filename if c.isdigit()])
        # 格式化为 YYYY-MM-DD
        t_minus_1_date = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}"

        try:
            df = pd.read_excel(file)
            
            # --- 关键：等效列名替换 ---
            # 先重命名所有已知的同义词
            df = df.rename(columns=COLUMN_MAPPING)
            
            # 只保留标准化的核心列，过滤掉由于多次运行产生的重复列（如同时存在 Success_Prob 和 晋级概率）
            standard_cols = ['Stock_Code', 'Stock_Name', 'Alpha_Score', 'Board_Count', 'Sealing_Ratio', 'Industry']
            # 找出当前 DF 中存在的标准列
            available_cols = [c for c in standard_cols if c in df.columns]
            df = df[available_cols]
            
            # 插入复盘日期 (T-1) 到第一列
            df.insert(0, 'Signal_Date', t_minus_1_date)
            
            all_data.append(df)
        except Exception as e:
            print(f"Skipping {filename} due to error: {e}")

    if all_data:
        # 2. 合并数据
        master_df = pd.concat(all_data, ignore_index=True)
        
        # 3. 数据清洗
        # 强制转换代码格式（补全 6 位 0）
        master_df['Stock_Code'] = master_df['Stock_Code'].astype(str).str.zfill(6)
        # 去重：防止重复读入同一个信号
        master_df = master_df.drop_duplicates(subset=['Signal_Date', 'Stock_Code'])

        # 4. 排序：按日期降序，评分降序
        master_df = master_df.sort_values(by=['Signal_Date', 'Alpha_Score'], ascending=[False, False])

        # 5. 最终翻译为客户表头
        final_report = master_df.rename(columns=CLIENT_HEADERS)

        # 6. 导出
        output_name = os.path.join(PROJECT_ROOT, 'output', f"Alpha_Strategy_Records_v{datetime.now().strftime('%m%d')}.xlsx")
        os.makedirs(os.path.dirname(output_name), exist_ok=True)
        final_report.to_excel(output_name, index=False)
        
        print("\n" + "="*50)
        print(f"🎉 SUCCESS: Unified {len(files)} files into one report.")
        print(f"Signal Date is correctly marked as T-1 (Review Date).")
        print(f"Saved as: {output_name}")
        print("="*50)
        
        return final_report

# %% [4] 执行
if __name__ == "__main__":
    report = generate_pro_master_report()
    if report is not None:
        # 打印前 10 行确认列名是否整洁
        print(report.head(10))