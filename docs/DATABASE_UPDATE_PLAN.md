# 数据库表更新方案

更新日期: 2026-06-25

## 当前结论

本轮代码已经新增 ORM:

```text
backend/app/models/rules.py
KeywordRule → keyword_rule
```

`keyword_rule` 表已接入初始化和启动加载:

```text
scripts/init_db.py
→ 创建表
→ 补齐默认规则数据
→ 加载 active 规则到 rule_service 内存配置

backend/app/main.py lifespan
→ 启动时补齐默认规则
→ 加载 active 规则到内存
→ 失败时回退代码默认规则
```

运行时不会每条消息查询 `keyword_rule`，避免增加响应延迟。

## 推荐更新原则

1. 不改已有知识主表结构，避免影响当前可用链路。
2. 新增规则表只作为配置承载，先做“启动加载/后台维护”，不要每条消息实时查表。
3. 向量表继续使用 `business_knowledge_embedding`，保持 MySQL 存向量 + 启动加载内存检索。
4. 知识关键词表继续保留，但不再参与普通答案兜底，只用于后台分析/导入/诊断。

## 表结构更新

### 1. 新增规则关键词表

如果目标数据库还没有 `keyword_rule`，执行:

```sql
CREATE TABLE IF NOT EXISTS keyword_rule (
  id INT NOT NULL AUTO_INCREMENT,
  rule_type VARCHAR(64) NOT NULL COMMENT '规则类型',
  keyword VARCHAR(128) NOT NULL COMMENT '关键词/短语',
  business_area VARCHAR(32) NULL COMMENT '适用业务域, 空表示全局',
  target VARCHAR(128) NULL COMMENT '目标值, 如业务域/意图/QRY编码/品牌名',
  action VARCHAR(64) NULL COMMENT '动作, 如 route/transfer/ask_slot',
  priority INT DEFAULT 0 COMMENT '优先级, 大者优先',
  is_active BOOLEAN DEFAULT TRUE,
  metadata JSON NULL COMMENT '扩展配置',
  description TEXT NULL COMMENT '规则说明',
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  INDEX ix_keyword_rule_rule_type (rule_type),
  INDEX ix_keyword_rule_keyword (keyword),
  INDEX ix_keyword_rule_priority (priority),
  INDEX ix_keyword_rule_is_active (is_active),
  INDEX idx_keyword_rule_type_keyword (rule_type, keyword),
  INDEX idx_keyword_rule_area_type (business_area, rule_type)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

### 2. 规则数据现状

默认规则数据由 `backend/app/services/rule_service.py` 生成，运行:

```powershell
python scripts\init_db.py
```

会把缺失的默认规则插入 `keyword_rule`。已存在规则不会被覆盖，便于后续后台调整。

建议 `rule_type`:

| rule_type | target/action | 用途 |
|---|---|---|
| `business_route` | target=`dashcam/wifi/data/refueling` | 业务域识别 |
| `transfer` | action=`transfer` | 显式转人工 |
| `high_risk` | action=`transfer`, target=`risk` | 投诉/12315/曝光等 |
| `unsupported_operation` | action=`transfer`, target=`out_of_scope` | 解绑/换绑/激活等 |
| `intent_hint` | target=`personal_query/instructional` | 本人查询/教程问法提示词 |
| `query_intent` | target=`QRY001...QRY013`, action=`regex` | 查询类型编码 |
| `brand_alias` | target=`标准品牌名` | 品牌别名 |
| `ambiguous_brand` | action=`ask_vin_or_terminal` | 鱼快等需二次确认品牌 |

示例:

```sql
INSERT INTO keyword_rule
  (rule_type, keyword, business_area, target, action, priority, is_active, description)
VALUES
  ('business_route', 'WiFi', 'wifi', 'wifi', 'route', 100, TRUE, 'WiFi业务路由'),
  ('business_route', '基础流量', 'data', 'data', 'route', 100, TRUE, '流量业务强路由'),
  ('business_route', '加油券', 'refueling', 'refueling', 'route', 100, TRUE, '加油业务强路由'),
  ('transfer', '转人工', NULL, 'user_request', 'transfer', 100, TRUE, '用户显式要求人工'),
  ('high_risk', '投诉', NULL, 'risk', 'transfer', 100, TRUE, '高风险投诉'),
  ('unsupported_operation', '解绑', 'dashcam', 'out_of_scope', 'transfer', 100, TRUE, '超出AI操作权限'),
  ('intent_hint', '帮我查', NULL, 'personal_query', 'classify', 55, TRUE, '本人数据查询提示'),
  ('query_intent', '(sim|卡号|iccid)', NULL, 'QRY001', 'regex', 65, TRUE, 'SIM/ICCID查询类型'),
  ('brand_alias', '极目单北斗', 'dashcam', '极目单北斗(DBD)', 'match_brand', 100, TRUE, '品牌长词优先'),
  ('ambiguous_brand', '鱼快', 'dashcam', NULL, 'ask_vin_or_terminal', 100, TRUE, '需二级识别');
```

## 向量表检查方案

当前使用:

```text
business_knowledge_embedding
```

建议每次导入或修改知识后执行:

```powershell
python scripts\build_embeddings.py --force
```

上线前核对四业务向量覆盖:

```sql
SELECT business_area, COUNT(*) AS cnt
FROM business_knowledge_embedding
WHERE status = 'published'
GROUP BY business_area;
```

期望当前数据:

```text
dashcam   144
wifi        9
data       11
refueling   8
```

## 迁移流程

### 开发环境

```powershell
python scripts\init_db.py
python scripts\build_embeddings.py --force
python tests\regression\run_100_regression.py
python -m pytest
```

### 测试/生产环境

1. 备份数据库。
2. 执行 `python scripts\init_db.py`，只补齐缺失表和默认规则，不删除、不改已有业务表。
3. 新增人工配置规则时先保持 `is_active=FALSE`。
4. 后台核对后再逐步启用。
5. 每次规则启用后重启服务或重新加载规则，并跑 500 条回归和真实样本回放。

## 回滚方案

规则表是新增表，不影响原数据。

回滚代码即可恢复内置规则逻辑。数据库层无需删除 `keyword_rule`；当前代码在规则加载失败时也会自动回退内置规则。

如果必须停用表内规则:

```sql
UPDATE keyword_rule SET is_active = FALSE;
```

## 不建议现在做的事

- 不建议把知识关键词表删除；它们仍有导入、诊断和后台分析价值。
- 不建议把所有规则改成每次请求实时查表；会增加延迟。
- 不建议直接把主链路切到 LangGraph；应另开分支 shadow mode 对比后再切。
