# 项目启动入口 (便捷脚本)
# 用法:
#   python run.py init       # 初始化数据库 + 导入知识库 + 种子数据
#   python run.py server     # 启动API服务
#   python run.py import     # 仅导入知识库
#   python run.py test       # 运行测试

import sys
import os
import subprocess

ROOT = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.join(ROOT, "backend")
SCRIPTS = os.path.join(ROOT, "scripts")


def run(cmd, cwd=ROOT):
    """运行命令"""
    print(f"\n▶ {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=cwd)
    return result.returncode == 0


def init():
    """初始化: 建表 + 导入知识库 + 种子数据"""
    print("=" * 50)
    print("🔧 初始化 AI客服Agent")
    print("=" * 50)

    steps = [
        (["python", os.path.join(SCRIPTS, "init_db.py")], "创建数据库表"),
        (["python", os.path.join(SCRIPTS, "seed_data.py")], "导入种子数据"),
        (["python", os.path.join(SCRIPTS, "import_kb.py")], "导入知识库"),
    ]

    for cmd, desc in steps:
        print(f"\n📋 {desc}...")
        if not run(cmd):
            print(f"❌ {desc}失败")
            return False

    print("\n✅ 初始化完成!")
    return True


def server():
    """启动API服务"""
    print("=" * 50)
    print("🚀 启动 AI客服Agent API服务")
    print("=" * 50)
    print(f"   API文档: http://localhost:8000/docs")
    print(f"   健康检查: http://localhost:8000/health")
    print()
    run(["python", "-m", "uvicorn", "app.main:app", "--reload", "--host", "0.0.0.0", "--port", "8000"], cwd=BACKEND)


def import_kb():
    """仅导入知识库"""
    run(["python", os.path.join(SCRIPTS, "import_kb.py")])


def test():
    """运行测试"""
    run(["python", "-m", "pytest", "tests/", "-v"], cwd=ROOT)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python run.py [init|server|import|test]")
        sys.exit(1)

    action = sys.argv[1]
    actions = {
        "init": init,
        "server": server,
        "import": import_kb,
        "test": test,
    }

    if action not in actions:
        print(f"未知命令: {action}")
        print(f"可用: {list(actions.keys())}")
        sys.exit(1)

    actions[action]()
