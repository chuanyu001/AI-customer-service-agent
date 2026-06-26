# 当前项目状态

更新日期: 2026-06-26

## 主链路现状

当前 `/api/v1/chat/message` 的真实主链路仍在 `backend/app/api/chat.py`，没有切换到 LangGraph runtime。

实际流程:

```text
用户消息
→ chat.py 保存会话消息
→ 强规则拦截转人工/高风险/超权限/问候
→ LLM理解: 最近6条消息 + pending + memory → intent/business/slots/rewritten_query
→ live_query: 收集 VIN 后查运营平台
→ knowledge_query: 原问题精确 → 改写问题精确 → 改写问题向量检索 → 低置信 LLM 重排
→ 品牌追问: 用户说出品牌→直接返回品牌知识；未说品牌→清除pending交由LLM理解
→ 删除了 `_is_unknown_brand_response` 硬编码关键词，不再把"查一下"误判为"不知道品牌"
→ 更新当前 session memory
```

LangGraph 文件仍保留:

```text
backend/app/graph/workflow.py
backend/app/nodes/*.py
```

这些节点已复用新的规则服务，但主入口暂不调用 `agent_workflow.ainvoke()`。后续如要迁移，建议单独开分支。

## 当前策略

### 业务域识别

规则入口: `backend/app/services/rule_service.py`

规则来源:

```text
keyword_rule active 数据
→ 启动时加载到内存
→ 缺失类别使用代码默认规则兜底
```

`scripts/init_db.py` 会补齐默认 `keyword_rule` 数据；服务启动也会补齐并加载一次。运行时不每条消息查规则表。

当前业务域:

- `dashcam`: 行车记录仪/设备/终端/VIN/SIM/卡号等。
- `wifi`: WiFi、热点、无线网络等。
- `data`: 基础流量、流量包、流量充值、流量套餐、青岛/长春流量等。
- `refueling`: 加油、油券、油价、油卡、汽油、柴油、燃油等。

泛词 `套餐/充值/续费/发票` 不单独决定业务域，避免把 `设备怎么续费` 错路由到流量。

### LLM理解与意图识别

正常主路径优先调用豆包做理解，不让大模型自由生成答案。

```text
强规则安全拦截
→ 豆包输出 intent_type/business_area/query_type_code/rewritten_query/slots
→ 豆包失败或非法JSON时 rule_service 降级
```

当前会话记忆保存在 `conversation.metadata.memory`，只在本次 session 内使用，不做跨会话长期画像。

### 知识检索

入口: `backend/app/services/knowledge_service.py`

当前顺序:

```text
原问题精确标准问/问法变体
→ 改写问题精确标准问/问法变体
→ 改写问题本地向量检索
→ 低置信时可选 LLM 候选重排
→ 追问/兜底
```

四业务知识关键词表不再作为普通答案兜底，避免通用词噪声覆盖向量结果。`_keyword_match()` 保留用于诊断或后台分析；真正影响规则判断的关键词已迁移到 `keyword_rule`。

### 转人工

入口: `backend/app/services/rule_service.py`

主要触发:

- 用户明确要求人工。
- 投诉、12315、起诉、曝光、维权、赔偿、欺诈等高风险。
- 解绑、换绑、修改绑定、激活设备、修改套餐等超权限操作。
- 连续失败。
- 命中 `auto_reply=False` 的非对客知识。

`加油券怎么退款` 这类规则咨询不直接转人工；短句 `退款`、`我要退款`、`不给退` 等仍进入高风险/人工处理。

## 文件夹约定

```text
backend/app/services/       业务服务: 规则、检索、品牌、会话、LLM、向量
backend/app/api/            FastAPI 路由，当前 chat.py 是主链路
backend/app/nodes/          LangGraph 节点，暂作为可复用逻辑准备
backend/app/graph/          LangGraph workflow 定义，暂不接主入口
backend/app/models/         ORM 模型
scripts/                    数据库初始化、导入、向量构建、数据包导出脚本
tests/unit/                 pytest 单元测试
tests/integration/          集成测试
tests/regression/           不依赖 pytest 的回归脚本
docs/                       架构、数据库、迁移说明
models/                     本地 embedding 模型，已在 .gitignore 中忽略
```

## 测试

安装依赖后可直接运行:

```powershell
python -m pytest
```

当前 `pytest.ini` 已配置:

- `pythonpath = backend`
- 关闭 pytest cacheprovider，避免当前 Windows 目录权限导致缓存写入失败。

回归脚本:

```powershell
python tests\regression\run_100_regression.py
python tests\regression\run_500_regression.py
```

最近一次结果:

```text
Total cases: 500
Passed: 500
Failed: 0
Groups:
  brand: 50/50
  business: 70/70
  database: 9/9
  intent: 100/100
  llm_understanding: 10/10
  retrieval_exact: 172/172
  retrieval_semantic: 12/12
  transfer: 60/60
  utility: 17/17
```

## LangGraph 迁移建议

暂不切换当前主链路。后续建议新建分支:

```text
codex/langgraph-mainline
```

建议迁移顺序:

1. 给 LangGraph 节点注入数据库会话，不再依赖 `state["db"]` 这种临时方式。
2. 先用 shadow mode 跑 `chat.py` 与 LangGraph 双链路，对比 intent/retrieval/response。
3. 通过 500 条回归和真实会话样本后，再切 `/chat/message` 主入口。
4. 保留一键回退到 `chat.py` 手写链路的配置开关。
