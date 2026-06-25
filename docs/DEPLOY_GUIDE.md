# Agent 后端部署指南

> 给部署 Agent 服务的同事。部署完成后告诉小程序开发者你的服务地址。

## 前置条件

- Python 3.13
- MySQL 8.0
- Git
- 从飞书/网盘下载 `agent_deploy_package.zip`（约 163MB）

## 1. 克隆代码

```bash
git clone https://github.com/chuanyu001/AI-customer-service-agent.git
cd AI-customer-service-agent
```

## 2. 解压部署包

把 `agent_deploy_package.zip` 解压到**项目根目录**，解压后结构：

```
AI customer service agent/
├── kefu_agent_full.sql       ← 数据库
├── models/
│   └── bge-small-zh-v1.5/    ← Embedding 模型
└── frontend/h5-chat/videos/  ← 视频文件
    ├── jimu-sim.mp4
    ├── hangtian-sim.mp4
    ├── yaxun-sim.mp4
    ├── hangtian-video-export.mp4
    └── yaxun-video-export.mp4
```

## 3. 创建虚拟环境

```bash
python -m venv venv

# Windows
venv\Scripts\activate

# macOS / Linux
source venv/bin/activate

pip install -r requirements.txt
```

## 4. 配置 .env

```bash
cp .env.example .env
```

编辑 `.env`，填入以下内容：

```env
# 必填
MYSQL_PASSWORD=你的MySQL密码

# 火山方舟（找 chuanyu 要）
LLM_PROVIDER=doubao
LLM_BASE_URL=https://ark.cn-beijing.volces.com/api/v3
LLM_API_KEY=找chuanyu要
LLM_MODEL=找chuanyu要

# Embedding 模型路径（指向解压后的 models 目录）
EMBEDDING_PROVIDER=local
EMBEDDING_LOCAL_PATH=models/bge-small-zh-v1.5
EMBEDDING_DEVICE=cpu
```

> 其余配置保持 `.env.example` 默认值即可。

## 5. 导入数据库

```bash
mysql -u root -p -e "CREATE DATABASE kefu_agent DEFAULT CHARACTER SET utf8mb4;"
mysql -u root -p kefu_agent < kefu_agent_full.sql
```

> SQL 文件已包含全部表结构 + 数据，不需要跑任何 Python 导入脚本。

## 6. 启动服务

```bash
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --app-dir backend
```

启动日志关键行：

```
✅ 数据库初始化完成
✅ 规则关键词加载完成
Embedding 模型预热完成          ← 首次启动等 7 秒
✅ 知识向量缓存加载完成: 172 条
Application startup complete.
```

## 7. 验证

```bash
# 健康检查
curl http://localhost:8000/health
# → {"status":"ok","service":"AI-Customer-Service-Agent","version":"1.0.0"}

# 测试问答
curl -X POST http://localhost:8000/api/v1/chat/message \
  -H "Content-Type: application/json" \
  -d '{"content":"设备离线怎么办","business_area":"dashcam"}'
# → 返回 JSON，response_type 应为 knowledge_answer 或 ask_slot
```

## 8. 告诉小程序开发者

部署完成后，把你的服务地址发给小程序团队，同时发给他们 `docs/API_INTEGRATION.md`。

如果你是在本机部署，小程序需要能访问到你的 IP。如果是在服务器上部署，给服务器的 IP:8000。

---

## 常见问题

**Q: 启动报错 `ModuleNotFoundError`？**
```bash
pip install -r requirements.txt   # 确保依赖装全
```

**Q: 数据库连接失败？**
检查 `.env` 中 `MYSQL_HOST`、`MYSQL_PORT`、`MYSQL_PASSWORD` 是否正确。

**Q: Embedding 模型加载失败？**
确认 `models/bge-small-zh-v1.5/` 目录存在且有 27 个文件。

**Q: 端口被占用？**
```bash
# Windows
netstat -ano | findstr :8000
taskkill /PID <PID> /F

# macOS / Linux
lsof -i :8000
kill -9 <PID>
```
