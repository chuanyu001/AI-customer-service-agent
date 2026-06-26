# 待办：响应慢优化

## 问题描述
用户发一条消息，后端响应需要 7-13 秒（极端情况 60-100 秒），体验卡顿。

## 原根因
旧链路每条消息**串行调用 2 次火山方舟大模型**：

| 步骤 | 调用 | 耗时 |
|------|------|------|
| 1. 意图分类 | 豆包 API（classify） | ~2-3秒 |
| 2. 知识检索 | 豆包 API（retrieve，144条知识全塞prompt） | ~5-10秒 |
| 3. 品牌追问/返回答案 | 本地 SQL | <0.1秒 |

最慢的是第2步——把 144 条知识（约 3000 token）全部塞进 prompt 让大模型选，每次查询都重新发送这 3000 token。

## 已实施方案

### 1. 意图识别改为规则优先

- 新增 `backend/app/services/rule_service.py`
- `keyword_rule` 启动加载到内存，缺失或加载失败时回退代码默认规则
- 正常主路径不再每条消息调用大模型做意图分类
- 明确区分:
  - 教程/规则类问题 → `knowledge_query`
  - 本人设备数据查询 → `live_query`
  - 转人工/高风险/超权限 → 转人工

### 2. 知识库向量化

- 本地模型: `models/bge-small-zh-v1.5`
- 向量表: `business_knowledge_embedding`
- 当前覆盖四业务 172 条:
  - dashcam 144
  - wifi 9
  - data 11
  - refueling 8

### 3. 检索链路调整

当前顺序:

```text
精确匹配
→ 本地向量检索
→ 低置信 LLM 候选重排
→ 追问/兜底
```

普通答案不再使用知识关键词表兜底，避免关键词噪声干扰。

### 4. 回归验证

```powershell
python -m pytest
python tests\regression\run_100_regression.py
```

最近一次 100 条回归结果:

```text
Total cases: 100
Passed: 100
Failed: 0
```

## 后续可选优化方案

### 方案A：规则表配置化
- 已新增 `keyword_rule` 表。
- 已接入 `scripts/init_db.py` 默认规则补齐。
- 已接入服务启动时加载规则表，失败时回退内置规则。
- 不会每次请求实时查表。

### 方案B：向量检索继续提速

- 当前首次加载模型会慢，启动时已有预热。
- 后续可以做常驻服务/批量预热/更轻量 embedding 模型评估。

### 方案C：只调参数
- 大模型调用加超时限制（避免 60 秒极端情况）
- 降低 max_tokens
- 开启流式输出（用户能更快看到首字）
- **效果**：缓解极端慢，但平均 7-13 秒降不下来

### 方案D：LangGraph 主链路迁移

- 当前暂不切换。
- 后续单独开分支，用 shadow mode 对比 `chat.py` 与 LangGraph 输出。

## 当前状态

- 响应慢的核心问题已处理: 规则意图 + 本地向量检索已接入主链路，规则表启动加载。
- 大模型只做低置信候选重排/润色兜底，不在正常主路径里承担分类和全库检索。
- LangGraph 暂不接主入口。

## 相关文件
- `backend/app/services/rule_service.py` — 规则、意图、转人工
- `backend/app/services/knowledge_service.py` — 知识检索流程
- `backend/app/services/embedding_service.py` — 本地向量编码/内存检索
- `backend/app/api/chat.py` — 当前消息处理主流程
