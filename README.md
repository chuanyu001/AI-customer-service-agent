# AI智能客服Agent

覆盖**行车记录仪、WiFi、流量、加油**四大业务领域的 AI 智能客服 Agent 系统。基于 FastAPI + LangGraph + 火山方舟大模型，支持知识问答、品牌识别追问、转人工分流。

## ✨ 核心特性

- **大模型驱动的语义检索**：火山方舟豆包做意图分类 + 知识检索，理解口语化提问
- **品牌识别追问**：命中需品牌的知识时主动追问，多轮上下文衔接，选品牌后返回该品牌详细答案
- **确定性转人工**：5种触发条件（连续失败/高风险词/用户请求/超出范围/敏感问题），不依赖大模型
- **可控回答**：大模型只做理解不做生成，回答用知识库标准答案，不胡说
- **H5聊天界面**：FAQ卡片、对话、追问、评价、图片上传，后端托管

## 🛠 技术栈

| 层 | 技术 |
|---|---|
| 后端 | Python 3.13 / FastAPI / LangGraph |
| 数据库 | MySQL 8.0 (异步 SQLAlchemy + aiomysql) |
| 大模型 | 火山方舟豆包 (OpenAI兼容接口) |
| 知识检索 | jieba分词 + 大模型全量检索 + SQL精确匹配 |
| 前端 | 原生 HTML/CSS/JS (移动端H5) |

## 🏗 架构

```
小程序3入口 → H5统一页面 → FastAPI后端 → 对话处理流程
                                          │
                    ┌─────────────────────┼──────────────────────┐
                    ▼                     ▼                      ▼
              火山方舟大模型          MySQL数据库            转人工工单
         (意图分类/知识检索)     (知识库/会话/运营数据)      (待接七鱼)
```

### 对话处理流程

```
用户消息
  ├─ ① 多轮上下文检查 (上一轮追问品牌→直接返回该品牌知识)
  ├─ ② 快速通道 (转人工/高风险/问候语, 不调大模型)
  ├─ ③ 意图分类 (大模型: knowledge_query/live_query/unknown)
  ├─ ④ 知识检索 (L1精确→L3大模型全量→L2关键词兜底)
  ├─ ⑤ 品牌感知 (need_brand=1→追问品牌; 已指定→返该品牌)
  └─ ⑥ 转人工判断 (5种触发条件)
```

## 🚀 快速开始

### 1. 环境准备

```bash
# 创建虚拟环境
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 安装依赖
pip install -r requirements.txt

# 复制配置文件
cp .env.example .env
# 编辑 .env, 填入 MySQL密码 / 火山方舟API Key / 推理接入点ID
```

### 2. 数据库准备

```bash
# 创建MySQL数据库
mysql -u root -p -e "CREATE DATABASE kefu_agent DEFAULT CHARACTER SET utf8mb4;"

# 建表 (21张表)
python scripts/init_db.py

# 导入知识库 (行车记录仪144条)
python scripts/import_kb.py

# 导入种子数据 (FAQ卡片/系统配置/数据字典)
python scripts/seed_data.py
```

### 3. 配置火山方舟大模型

在 `.env` 中配置（火山方舟控制台获取）：
```env
LLM_PROVIDER=doubao
LLM_BASE_URL=https://ark.cn-beijing.volces.com/api/v3
LLM_API_KEY=你的API Key
LLM_MODEL=你的推理接入点ID (ep-xxx)
```

> 也可设 `LLM_PROVIDER=mock` 用规则兜底，不依赖大模型验证链路。

### 4. 启动服务

```bash
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --app-dir backend
```

访问：
- 🎯 **聊天界面**：http://localhost:8000/
- 📚 **API文档**：http://localhost:8000/docs
- ❤️ **健康检查**：http://localhost:8000/health

## 📂 项目结构

```
AI customer service agent/
├── backend/app/
│   ├── main.py              # FastAPI入口 (托管前端)
│   ├── api/                 # 26个API端点 (chat/knowledge/admin/evaluation)
│   ├── core/                # config/database/redis
│   ├── models/              # 21张表ORM
│   ├── schemas/             # Pydantic模型
│   ├── graph/               # LangGraph工作流 (state/workflow)
│   ├── nodes/               # 7个工作流节点
│   ├── services/            # LLM/知识检索/品牌识别/会话/Embedding
│   └── integrations/        # 七鱼/运营平台对接
├── frontend/h5-chat/        # H5聊天页面
├── scripts/                 # 建表/导入/种子/知识库合并脚本
├── tests/                   # 单元测试+集成测试
├── AI智能客服Agent产品实施方案.md  # 详细方案
└── .env.example             # 配置模板
```

## 🗄 数据库设计 (21张表)

| 表组 | 表 | 说明 |
|------|------|------|
| 知识数据 | knowledge_answer, question_variant, keyword, attachment, version, faq_card, query_intent_config | 知识库核心 |
| 业务事实 | brand_info, brand_mapping, field_dictionary, operational_device, device_vehicle_relation | 品牌/查询配置/运营数据 |
| 运行数据 | conversation, message, answer_feedback, handoff_ticket, optimization_sample | 会话/消息/评价/工单/样本 |
| 系统配置 | system_config, data_dictionary, event_log | 配置/字典/日志 |

## 📡 API 接口 (26个)

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v1/chat/sessions` | 创建会话 |
| POST | `/api/v1/chat/message` | 发送消息 (核心) |
| GET | `/api/v1/knowledge/faq-cards` | FAQ卡片 |
| POST/GET/PUT/DELETE | `/api/v1/knowledge/entries` | 知识CRUD |
| POST | `/api/v1/knowledge/import` | 导入知识库 |
| POST | `/api/v1/evaluation/feedback` | 提交评价 |
| GET | `/api/v1/admin/dashboard/stats` | 仪表盘 |

完整接口见 http://localhost:8000/docs

## 📊 当前进度

- ✅ 行车记录仪业务全链路跑通（知识问答/品牌追问/转人工）
- ✅ 火山方舟大模型接入
- ✅ H5前端页面
- ⏳ WiFi/流量/加油三业务待导入（知识库已合并整理）
- ⏳ 运营平台36万数据待导入
- ⏳ 七鱼工单对接

详见 [AI智能客服Agent产品实施方案.md](AI智能客服Agent产品实施方案.md)

## 🎯 KPI 目标

- 人工转接率 ≤ 30%
- AI问题收敛率 ≥ 70%
- 用户满意度 ≥ 90%
- 7×24小时自动应答

## 📝 License

MIT
