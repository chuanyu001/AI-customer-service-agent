# 知识库合并脚本
# 把 WiFi/流量/加油/行车记录仪 四项业务知识库合并成一个 Excel
# 列名统一成行车记录仪 01 表的 13 列风格
#
# 用法: python scripts/merge_knowledge_base.py

import os
import pandas as pd

SRC_DIR = r"D:\wuchu\Desktop\personalfiles\实习\kefu-agent\agent知识库汇总版6.22"
OUT_PATH = r"D:\wuchu\Desktop\personalfiles\实习\kefu-agent\agent知识库汇总版6.22\知识库汇总版6.22.xlsx"

# 行车记录仪 01 表的标准列名 (13列)
DASHCAM_COLS = [
    "知识编号", "产品模块", "厂家", "知识类型", "标准问题", "常见问法",
    "标准答案", "是否需要识别品牌", "是否需要附件", "关联查询编号",
    "转人工条件", "状态", "来源备注",
]

# 前3个业务 01 表列名 → 行车记录仪标准列名 的映射
# 注: "功能分类"和"知识标题"在 normalize_knowledge_df 里手动合并为"知识类型", 不在此映射
COL_MAP = {
    "知识编号": "知识编号",
    "产品模块": "产品模块",
    "标准问法": "标准问题",            # 标准问法 → 标准问题
    "标准答案": "标准答案",
    "相似问法": "常见问法",            # 相似问法 → 常见问法
    "是否需要识别类型": "是否需要识别品牌",  # 是否需要识别类型 → 是否需要识别品牌
    "转人工规则": "转人工条件",        # 转人工规则 → 转人工条件
    "状态": "状态",
    "来源备注": "来源备注",
    "参考链接": "_备注_参考链接",      # 行车记录仪无此列, 单独保留
    "备注1": "_备注_备注1",
    "是否需要查询": "_备注_是否需要查询",
    "关联查询规则": "_备注_关联查询规则",
}

# 业务文件配置
BUSINESS_FILES = [
    ("01_行车记录仪知识问答库", "行车记录仪Agent知识库_更新版622.xlsx", "01_知识问答库", "dashcam", True),
    ("02_WiFi套餐知识问答库", "WiFi套餐_Agent知识库.xlsx", "01_知识问答库", "wifi", False),
    ("03_基础流量知识问答库", "基础流量处理_Agent知识库.xlsx", "01_知识问答库", "data", False),
    ("04_折扣加油知识问答库", "折扣加油_Agent知识库.xlsx", "01_知识问答库", "refueling", False),
]

# 行车记录仪专有 sheet (原样保留)
DASHCAM_EXTRA_SHEETS = [
    ("05_记录仪查询问题库", "行车记录仪Agent知识库_更新版622.xlsx", "02_查询问题库"),
    ("06_记录仪品牌识别规则", "行车记录仪Agent知识库_更新版622.xlsx", "03_品牌识别规则"),
    ("07_记录仪运营字段字典", "行车记录仪Agent知识库_更新版622.xlsx", "04_运营字段字典"),
]


def normalize_knowledge_df(df: pd.DataFrame, business_area: str, is_dashcam: bool) -> pd.DataFrame:
    """把 01 知识问答表规整为行车记录仪的13列标准结构"""
    if is_dashcam:
        # 行车记录仪已是标准列名, 直接补齐缺失列
        for col in DASHCAM_COLS:
            if col not in df.columns:
                df[col] = ""
        return df[DASHCAM_COLS]

    # 前3个业务: 做列名映射
    # 先把"功能分类"和"知识标题"合并成"知识类型" (两者都映射到知识类型)
    work = df.copy()
    func_cat = work.get("功能分类", pd.Series(dtype=str)).fillna("").astype(str)
    title = work.get("知识标题", pd.Series(dtype=str)).fillna("").astype(str)
    # 功能分类优先, 为空时用知识标题
    work["知识类型"] = func_cat.where(func_cat != "", title)
    work = work.drop(columns=["功能分类", "知识标题"], errors="ignore")

    renamed = {}
    extra_cols = {}
    for src_col in work.columns:
        target = COL_MAP.get(src_col)
        if target is None:
            # 知识类型已手动处理, 跳过
            if src_col == "知识类型":
                continue
            continue
        if target.startswith("_备注_"):
            extra_cols[target] = work[src_col]
        else:
            renamed[src_col] = target

    new_df = work.rename(columns=renamed).copy()

    # 合并非标准列到"来源备注"
    if extra_cols:
        extra_text = pd.DataFrame(extra_cols).apply(
            lambda row: " | ".join([f"{k.replace('_备注_','')}={v}" for k, v in row.items() if pd.notna(v) and str(v).strip()]),
            axis=1,
        )
        # 追加到来源备注
        if "来源备注" not in new_df.columns:
            new_df["来源备注"] = ""
        new_df["来源备注"] = new_df["来源备注"].fillna("").astype(str)
        for i in range(len(new_df)):
            extra = extra_text.iloc[i] if i < len(extra_text) else ""
            if extra:
                new_df.iloc[i, new_df.columns.get_loc("来源备注")] = (
                    (new_df.iloc[i, new_df.columns.get_loc("来源备注")] + " | " + extra).strip(" |")
                )

    # 补齐标准13列中缺失的列
    for col in DASHCAM_COLS:
        if col not in new_df.columns:
            new_df[col] = ""
        else:
            new_df[col] = new_df[col].fillna("")

    # 前3个业务没有"厂家"概念, 统一填"通用"
    if "厂家" in new_df.columns:
        new_df["厂家"] = new_df["厂家"].replace("", "通用").fillna("通用")

    # 前3个业务没有附件, 填"否"
    if "是否需要附件" in new_df.columns:
        new_df["是否需要附件"] = new_df["是否需要附件"].replace("", "否").fillna("否")

    # 前3个业务没有关联查询编号, 留空
    if "关联查询编号" in new_df.columns:
        new_df["关联查询编号"] = new_df["关联查询编号"].fillna("")

    return new_df[DASHCAM_COLS]


def build_usage_sheet() -> pd.DataFrame:
    """汇总4个业务的使用说明"""
    rows = []
    files = [
        ("行车记录仪", "行车记录仪Agent知识库_更新版622.xlsx"),
        ("WiFi套餐", "WiFi套餐_Agent知识库.xlsx"),
        ("基础流量处理", "基础流量处理_Agent知识库.xlsx"),
        ("折扣加油", "折扣加油_Agent知识库.xlsx"),
    ]
    for biz, fname in files:
        path = os.path.join(SRC_DIR, fname)
        try:
            df = pd.read_excel(path, sheet_name="00_使用说明")
            for _, row in df.iterrows():
                # 把每行内容拼成 "列名: 值"
                parts = [f"{c}: {row[c]}" for c in df.columns if pd.notna(row[c]) and str(row[c]).strip()]
                if parts:
                    rows.append({"业务": biz, "使用说明": " | ".join(parts)})
        except Exception as e:
            rows.append({"业务": biz, "使用说明": f"读取失败: {e}"})

    # 追加汇总说明
    rows.append({"业务": "汇总", "使用说明": "本表由 merge_knowledge_base.py 自动生成, 合并4项业务知识库"})
    rows.append({"业务": "汇总", "使用说明": "Sheet结构: 00使用说明 + 01-04四业务知识问答 + 05-07记录仪查询/品牌/字典"})
    rows.append({"业务": "汇总", "使用说明": "列名统一为行车记录仪13列标准: 知识编号/产品模块/厂家/知识类型/标准问题/常见问法/标准答案/是否需要识别品牌/是否需要附件/关联查询编号/转人工条件/状态/来源备注"})
    rows.append({"业务": "汇总", "使用说明": "前3个业务(WiFi/流量/加油)无厂家概念, 厂家列填'通用'; 无附件, 是否需要附件填'否'"})

    return pd.DataFrame(rows)


def main():
    print(f"📂 源目录: {SRC_DIR}")
    print(f"📤 输出文件: {OUT_PATH}\n")

    sheets = {}

    # 1. 使用说明 (汇总)
    print("📝 构建使用说明 sheet...")
    sheets["00_使用说明"] = build_usage_sheet()
    print(f"   ✅ {len(sheets['00_使用说明'])} 行")

    # 2. 四业务知识问答
    for sheet_name, fname, src_sheet, biz, is_dashcam in BUSINESS_FILES:
        print(f"📝 处理 {sheet_name} ({biz})...")
        path = os.path.join(SRC_DIR, fname)
        df = pd.read_excel(path, sheet_name=src_sheet)
        normalized = normalize_knowledge_df(df, biz, is_dashcam)
        sheets[sheet_name] = normalized
        print(f"   ✅ {len(normalized)} 条, 列数: {len(normalized.columns)}")

    # 3. 行车记录仪专有 sheet (原样保留)
    for sheet_name, fname, src_sheet in DASHCAM_EXTRA_SHEETS:
        print(f"📝 复制 {sheet_name}...")
        path = os.path.join(SRC_DIR, fname)
        df = pd.read_excel(path, sheet_name=src_sheet)
        sheets[sheet_name] = df
        print(f"   ✅ {len(df)} 条")

    # 写入 Excel
    print(f"\n💾 写入 {OUT_PATH}...")
    with pd.ExcelWriter(OUT_PATH, engine="openpyxl") as writer:
        for sheet_name, df in sheets.items():
            df.to_excel(writer, sheet_name=sheet_name, index=False)

    print(f"\n✅ 合并完成!")
    print(f"   共 {len(sheets)} 个 sheet:")
    for name, df in sheets.items():
        print(f"   • {name}: {len(df)} 行 × {len(df.columns)} 列")


if __name__ == "__main__":
    main()
