# AI智能客服Agent

覆盖**行车记录仪、WiFi、流量、加油**四大业务领域的 AI 智能客服 Agent 系统。当前主链路基于 FastAPI + 规则服务 + 本地向量检索；LangGraph 节点已保留并复用规则服务，但暂未接管 `/chat/message` 主入口。

## ✨ 核心特性

- **本地向量语义检索**：BAAI/bge-small-zh-v1.5 模型，四业务172条知识向量化，启动加载内存后余弦召回
- **规则化意图识别**：`keyword_rule` 启动加载到内存，区分教程类 vs 个人数据查询，不再每条消息调大模型分类
- **品牌识别双因子**：VIN+终端号(行车记录仪ID)联合识别，终端号规则优先，VIN交叉验证
- **VIN主动品牌识别**：用户直接发纯VIN时，dashcam业务主动查品牌返回，不依赖多轮上下文
- **品牌识别追问**：命中需品牌的知识时主动追问，多轮上下文衔接，选品牌后返回该品牌详细答案
- **是否对客转人工**：每条知识标记对客/转人工，转人工类命中先追问收集信息（VIN/ICCID/车型）再转人工，工单携带完整对话上下文给坐席
- **确定性转人工**：6种触发条件（连续失败/高风险词/用户请求/超出范围/敏感问题/知识非对客），不依赖大模型
- **运营平台接口实时查询**：调 batchVehicleInfo 接口按 VIN 查设备信息（车牌/设备号/到期），不落库
- **可控回答**：正常主路径不调用大模型生成答案，回答优先使用知识库标准答案/预润色答案
- **H5聊天界面**：FAQ卡片、对话、追问、评价、图片上传，后端托管

## 🛠 技术栈

| 层 | 技术 |
|---|---|
| 后端 | Python 3.13 / FastAPI |
| 数据库 | MySQL 8.0 (异步 SQLAlchemy + aiomysql) |
| LangGraph | 已保留 workflow/nodes，暂未接主入口 |
| 大模型 | 可选，低置信候选重排/润色兜底 |
| Embedding | 本地 BAAI/bge-small-zh-v1.5 (512维, 192MB) |
| 知识检索 | 精确匹配 → 向量余弦召回 → 低置信 LLM 候选重排，普通答案不走关键词兜底 |
| 前端 | 原生 HTML/CSS/JS (移动端H5) |

## 🏗 架构

```
小程序3入口 → H5统一页面 → FastAPI后端 → chat.py主链路
                                          │
                    ┌─────────────────────┼──────────────────────┐
                    ▼                     ▼                      ▼
              本地向量模型           MySQL数据库            转人工工单
          (查询向量/内存召回)   (知识库/向量/会话/规则)      (待接七鱼)
```

### 对话处理流程

```
用户消息
  ├─ ① 多轮上下文检查 (上一轮追问品牌/转人工收集信息→衔接)
  ├─ ② 规则快速通道 (转人工/高风险/问候语, 不调大模型)
  ├─ ③ VIN主动品牌识别 (dashcam+纯VIN→双因子查品牌→返回+存pending)
  ├─ ④ 意图识别 (规则优先: 教程走知识库 / 个人数据走接口查询)
  ├─ ⑤ 知识检索 (L1精确→L2向量召回→L3低置信LLM候选重排)
  ├─ ⑥ 品牌感知 (need_brand=1→追问品牌; 已指定→返该品牌)
  ├─ ⑦ 是否对客判断 (auto_reply=True→自动答; =False→追问收集信息→转人工)
  ├─ ⑧ 查询意图 (live_query→提取VIN→调运营平台接口→返回)
  └─ ⑨ 转人工判断 (6种触发, 生成工单带完整对话上下文)
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

# 建表
python scripts/init_db.py

# 迁移到四业务分表 + 导入四业务知识库 (dashcam 144/wifi 9/data 11/refueling 8)
python scripts/migrate_to_multi_table.py

# 导入/更新四业务知识库 + 有为设备明细 (全量替换策略)
python scripts/import_multi_business.py

# 导入种子数据 + 构建向量索引
python scripts/seed_data.py
python scripts/build_embeddings.py
```

### 3. 配置大模型（可选）

在 `.env` 中配置（火山方舟控制台获取）：
```env
LLM_PROVIDER=doubao
LLM_BASE_URL=https://ark.cn-beijing.volces.com/api/v3
LLM_API_KEY=你的API Key
LLM_MODEL=你的推理接入点ID (ep-xxx)
```

> 当前正常主路径不依赖大模型分类。规则关键词从 `keyword_rule` 启动加载到内存，表缺失或加载失败时回退代码默认规则。

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
│   ├── models/              # ORM模型
│   ├── schemas/             # Pydantic模型
│   ├── graph/               # LangGraph工作流定义 (暂未接主入口)
│   ├── nodes/               # LangGraph节点，复用规则服务
│   ├── services/            # 规则/知识检索/品牌识别/会话/LLM/Embedding
│   └── integrations/        # 七鱼/运营平台对接
├── frontend/h5-chat/        # H5聊天页面
├── scripts/                 # 建表/导入/种子/知识库合并脚本
├── tests/                   # 单元测试/集成测试/回归脚本
├── docs/                    # 当前架构和数据库更新方案
├── AI智能客服Agent产品实施方案.md  # 详细方案
└── .env.example             # 配置模板
```

## 🗄 数据库设计 (当前MySQL 41张表)

| 表组 | 表 | 说明 |
|------|------|------|
| 四业务知识分表 | dashcam_/wifi_/data_/refueling_ knowledge+variant+keyword+(attachment)+faq_card | 运行时主检索用 knowledge/variant；keyword 表保留兼容和诊断，不做普通答案兜底 |
| 知识向量 | business_knowledge_embedding(172) | 四业务知识向量存储，启动加载内存 |
| 知识数据(旧) | knowledge_answer, question_variant, keyword, attachment, version, faq_card, query_intent_config | 迁移前备份+查询意图配置 |
| 业务事实 | brand_info, brand_mapping, field_dictionary, operational_data(26696), youwei_device(10010), device_vehicle_relation | 品牌双因子识别/本地运营数据/字段字典/有为设备明细/设备关系；`operational_device` 旧空表已删除 |
| 运行数据 | conversation, message, answer_feedback, handoff_ticket, optimization_sample | 会话/消息/评价/工单(带完整上下文)/样本 |
| 系统配置/规则 | system_config, data_dictionary, event_log, keyword_rule | 配置/字典/日志/规则关键词 |

**是否对客转人工相关字段**（四张 knowledge 表）：`auto_reply`（True=对客自动答 / False=转人工）、`transfer_prompt`（转人工类追问语）。`handoff_ticket.summary` 存转人工时完整对话上下文（不做摘要）。

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

- ✅ 行车记录仪业务全链路跑通
- ✅ 本地向量语义检索（BAAI/bge-small-zh-v1.5，172条全量向量化，< 50ms）
- ✅ 规则化意图识别（`keyword_rule` 启动加载，代码默认规则兜底，不再每条消息调LLM分类）
- ✅ 检索策略升级（精确→向量→低置信LLM候选重排，普通答案不再走关键词兜底）
- ✅ 品牌识别双因子（VIN+终端号联合识别）
- ✅ VIN主动品牌识别（纯VIN消息主动查品牌）
- ✅ 四业务知识库全量导入（dashcam 144/wifi 9/data 11/refueling 8）
- ✅ 有为设备10010台明细导入
- ✅ 「是否对客」转人工机制（转人工前追问 + 工单带完整上下文）
- ✅ 运营平台接口实时查询
- ✅ 火山方舟大模型接入
- ✅ H5前端页面
- ✅ 多业务路由/意图/转人工/品牌/检索 500 条回归通过
- ✅ 数据库清理：`operational_device` 代码依赖移除并物理删除，`operational_data` 保留26696行
- ⏳ 运营平台接口扩展（在线状态/SIM/套餐）
- ⏳ 七鱼工单对接

详见 [AI智能客服Agent产品实施方案.md](AI智能客服Agent产品实施方案.md)
当前实现细节见 [docs/CURRENT_STATUS.md](docs/CURRENT_STATUS.md)，数据库更新方案见 [docs/DATABASE_UPDATE_PLAN.md](docs/DATABASE_UPDATE_PLAN.md)，数据库清理审计见 [docs/DATABASE_CLEANUP_AUDIT.md](docs/DATABASE_CLEANUP_AUDIT.md)。

## 🎯 KPI 目标

- 人工转接率 ≤ 30%
- AI问题收敛率 ≥ 70%
- 用户满意度 ≥ 90%
- 7×24小时自动应答

## 📝 License

MIT
