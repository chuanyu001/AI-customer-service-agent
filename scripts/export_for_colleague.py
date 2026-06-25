# 同事入职数据导出脚本
# 导出数据库 + 列出需手动复制的文件清单
# 用法: python scripts/export_for_colleague.py

import sys
import os
import subprocess
import shutil
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
from app.core.config import settings

# 输出目录
OUT_DIR = Path(__file__).parent.parent / "colleague_package"
OUT_DIR.mkdir(exist_ok=True)

print("=" * 60)
print("同事入职数据包导出")
print(f"输出目录: {OUT_DIR}")
print("=" * 60)

# ============================================
# 1. 导出数据库 (通过临时配置文件避免密码泄露)
# ============================================
print("\n[1/2] 导出MySQL数据库...")

mysql_cnf = OUT_DIR / ".mysql_tmp.cnf"
mysql_cnf.write_text(f"""[client]
user={settings.MYSQL_USER}
password={settings.MYSQL_PASSWORD}
host={settings.MYSQL_HOST}
port={settings.MYSQL_PORT}
""")

sql_file = OUT_DIR / "kefu_agent_full.sql"
try:
    subprocess.run([
        "mysqldump",
        f"--defaults-extra-file={mysql_cnf}",
        "--single-transaction",
        "--routines",
        "--triggers",
        settings.MYSQL_DATABASE,
    ], stdout=open(sql_file, "w", encoding="utf-8"), check=True)
    size_mb = sql_file.stat().st_size / (1024 * 1024)
    print(f"  [OK] 数据库导出: {sql_file.name} ({size_mb:.1f}MB)")
except subprocess.CalledProcessError as e:
    print(f"  [FAIL] mysqldump 失败: {e}")
finally:
    mysql_cnf.unlink()  # 删除临时密码文件

# ============================================
# 2. 列出同事需要的文件
# ============================================
print("\n[2/2] 文件清单:")

FILES_TO_COPY = {
    # 视频文件 (前端播放)
    "视频": {
        "source_dir": r"D:\wuchu\Desktop\personalfiles\实习\AI customer service agent\frontend\h5-chat\videos",
        "dest_dir": OUT_DIR / "videos",
        "files": [
            "hangtian-sim.mp4",
            "hangtian-video-export.mp4",
            "jimu-sim.mp4",
            "yaxun-sim.mp4",
            "yaxun-video-export.mp4",
        ],
    },
}

KB_DIR = r"D:\wuchu\Desktop\personalfiles\实习\kefu-agent\agent知识库汇总版"

# 知识库Excel和运营数据
EXCEL_FILES = {
    "知识库-记录仪": "记录仪知识库确认版6.24.xlsx",
    "知识库-WiFi": "WiFi套餐知识库确认版6.24.xlsx",
    "知识库-流量": "基础流量处理知识库确认版6.24.xlsx",
    "知识库-加油": "折扣加油知识库确认版6.24.xlsx",
    "有为设备明细": "有为设备10010台明细.xlsx",
    "运营平台数据": "运营平台数据.xlsx",
}

total_files = 0
total_size = 0

# 复制视频
for category, info in FILES_TO_COPY.items():
    print(f"\n  [{category}]")
    os.makedirs(info["dest_dir"], exist_ok=True)
    for fname in info["files"]:
        src = Path(info["source_dir"]) / fname
        if src.exists():
            shutil.copy2(src, info["dest_dir"] / fname)
            size = src.stat().st_size
            print(f"    {fname} ({size/1024/1024:.1f}MB)")
            total_files += 1
            total_size += size
        else:
            print(f"    [MISSING] {fname}")

# 列出Excel (不复制, 太大)
print(f"\n  [知识库Excel - 从共享目录手动复制]")
print(f"  共享目录: {KB_DIR}")
for label, fname in EXCEL_FILES.items():
    src = Path(KB_DIR) / fname
    if src.exists():
        size = src.stat().st_size
        print(f"    {label}: {fname} ({size/1024/1024:.1f}MB)")
    else:
        print(f"    [MISSING] {label}: {fname}")

# ============================================
# 汇总
# ============================================
sql_size = sql_file.stat().st_size if sql_file.exists() else 0
total_size += sql_size

print(f"\n{'=' * 60}")
print(f"导出完成!")
print(f"  SQL文件: {sql_file.name} ({sql_size/1024/1024:.1f}MB)")
print(f"  视频文件: {total_files} 个")
print(f"  总大小: {total_size/1024/1024:.1f}MB")
print(f"\n同事需要做的事:")
print(f"  1. 把 {OUT_DIR} 整个目录拷贝给他")
print(f"  2. 把 {KB_DIR} 下的6个Excel也拷贝过去")
print(f"  3. 他执行:")
print(f"     mysql -u root -p -e \"CREATE DATABASE kefu_agent DEFAULT CHARACTER SET utf8mb4;\"")
print(f"     mysql -u root -p kefu_agent < kefu_agent_full.sql")
print(f"     python scripts/init_db.py   # 确保表结构")
print(f"     # Excel和视频放对应位置后跑导入脚本")
print(f"  4. pip install -r requirements.txt")
print(f"  5. cp .env.example .env  # 编辑填入配置")
print(f"  6. python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --app-dir backend")
print(f"{'=' * 60}")
