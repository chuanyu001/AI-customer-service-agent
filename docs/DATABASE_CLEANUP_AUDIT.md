# 数据库清理审计

审计日期: 2026-06-25
更新日期: 2026-06-26

## 执行范围

本次先完成只读审计和非破坏性代码依赖收缩，后续已按确认执行 `operational_device` 物理删除:

- 查询当前 MySQL 表、行数、外键和孤儿数据。
- 扫描 `backend/app`、`scripts`、`tests` 中的 ORM 类名和表名引用。
- 已执行 `DROP TABLE IF EXISTS operational_device`；执行前 0 行，执行后表不存在。
- 除 `operational_device` 外，未执行其他 `DROP TABLE`、`DELETE`、`TRUNCATE`。
- 已把后台 KB 统计从旧 `faq_card` 改为四业务 FAQ 表汇总。
- 已移除 `OperationalDevice` ORM、`brand_service` MCU 验证分支和 `mcu_verify_rule` ORM 字段。

## 一致性检查结论

### 四业务知识库

| 表 | 行数 | 结论 |
|---|---:|---|
| `dashcam_knowledge` | 144 | 主知识表，保留 |
| `wifi_knowledge` | 9 | 主知识表，保留 |
| `data_knowledge` | 11 | 主知识表，保留 |
| `refueling_knowledge` | 8 | 主知识表，保留 |

向量表覆盖完整:

| business_area | source_table | 向量数 |
|---|---|---:|
| dashcam | `dashcam_knowledge` | 144 |
| wifi | `wifi_knowledge` | 9 |
| data | `data_knowledge` | 11 |
| refueling | `refueling_knowledge` | 8 |

`knowledge_answer` 与 `dashcam_knowledge` 当前按 `knowledge_code` 完全一致:

```text
knowledge_answer: 144
dashcam_knowledge: 144
legacy_not_in_dashcam: 0
dashcam_not_in_legacy: 0
```

### 外键/孤儿数据

以下子表孤儿数据均为 0:

```text
dashcam_variant / dashcam_keyword / dashcam_attachment / dashcam_faq_card
wifi_variant / wifi_keyword / wifi_faq_card
data_variant / data_keyword / data_faq_card
refueling_variant / refueling_keyword / refueling_faq_card
knowledge_question_variant / knowledge_keyword / knowledge_attachment / faq_card
knowledge_embedding
```

## 表分层

### 必须保留: 当前主链路依赖

| 表组 | 表 | 原因 |
|---|---|---|
| 会话运行 | `conversation`, `message`, `answer_feedback`, `handoff_ticket` | 会话、消息、评价、转人工工单 |
| 四业务知识 | `dashcam_knowledge`, `wifi_knowledge`, `data_knowledge`, `refueling_knowledge` | 当前知识检索主表 |
| 问法变体 | `dashcam_variant`, `wifi_variant`, `data_variant`, `refueling_variant` | 精确匹配/导入/向量文本构建 |
| 知识关键词 | `dashcam_keyword`, `wifi_keyword`, `data_keyword`, `refueling_keyword` | 不做普通答案兜底，但用于向量文本构建、导入和诊断 |
| FAQ | `dashcam_faq_card`, `wifi_faq_card`, `data_faq_card`, `refueling_faq_card` | 当前 FAQ 卡片 |
| 向量 | `business_knowledge_embedding` | 当前向量检索主表 |
| 规则 | `keyword_rule` | 启动加载规则关键词 |
| 品牌/运营 | `brand_info`, `brand_mapping`, `operational_data`, `youwei_device` | 品牌识别和 VIN/终端号辅助识别 |

### 暂时保留: 兼容或后续功能依赖

| 表 | 行数 | 当前情况 | 建议 |
|---|---:|---|---|
| `knowledge_answer` | 144 | 旧行车记录仪知识主表，已被四业务分表替代；部分旧脚本/LangGraph 节点仍引用 | 暂存为 legacy，后续迁移脚本和节点后再归档 |
| `knowledge_question_variant` | 415 | 旧问法变体 | 同上 |
| `knowledge_keyword` | 914 | 旧知识关键词 | 同上 |
| `knowledge_attachment` | 5 | 旧附件 | 同上 |
| `faq_card` | 10 | 旧 FAQ 卡片；后台统计已改为四业务 FAQ 汇总 | 后续迁移完管理接口/脚本后归档 |
| `query_intent_config` | 13 | LangGraph 查询节点仍支持从该表加载槽位配置；当前 `chat.py` 主链路不用 | LangGraph 迁移前先保留 |
| `system_config` | 15 | 管理配置/节点兼容 | 保留 |
| `data_dictionary` | 38 | 字典/导入脚本使用 | 保留 |
| `field_dictionary` | 22 | 运营字段字典，平台查询节点/接口兼容 | 保留 |
| `optimization_sample` | 0 | 管理后台样本池接口依赖 | 保留，除非关闭该功能 |
| `event_log` | 0 | 模型保留，当前未写入 | 可作为后续埋点表保留 |

### 已物理删除: 已确认执行

| 表 | 删除前行数 | 执行结果 | 替代/保留数据 |
|---|---:|---|---|
| `operational_device` | 0 | 2026-06-26 已执行 `DROP TABLE IF EXISTS operational_device`，执行后表不存在 | 本地运营平台数据继续保留在 `operational_data`，当前 26696 行 |

### 可删除候选: 需要二次确认后执行

| 表 | 行数 | 代码依赖 | 处理建议 |
|---|---:|---|---|
| `knowledge_embedding` | 0 | 无 ORM 模型；仅在新向量模型注释中提到 | 最安全的删除候选。备份后可 DROP |
| `device_vehicle_relation` | 0 | 仅 ORM 模型注册，无运行时代码查询 | 若短期不用设备-车辆-SIM关系，可删除；否则保留为空表 |
| `knowledge_version` | 0 | 仅 ORM 模型注册，无运行时代码查询 | 如果不做知识版本历史，可删除；否则保留 |

## 删除前必须完成的代码动作

### 删除 `knowledge_embedding`

无需业务代码改动，但建议先执行:

```sql
SELECT COUNT(*) FROM knowledge_embedding;
```

确认仍为 0 后，备份再删除。

### 删除旧知识表组

涉及表:

```text
knowledge_answer
knowledge_question_variant
knowledge_keyword
knowledge_attachment
faq_card
knowledge_version
```

删除前必须完成:

1. 确认 `backend/app/nodes/response_generation.py` 不再使用旧 `KnowledgeAnswer`。
2. 确认 `scripts/import_kb.py`、`scripts/import_videos.py`、`scripts/build_polished_answers.py`、`scripts/sync_kb_from_excel.py` 等脚本迁移到四业务表。
3. 确认管理接口、导入导出接口不再引用旧表。
4. 备份旧表数据到 SQL 或归档库。

### 删除 `operational_device`

已完成。代码依赖清理内容:

1. `backend/app/services/brand_service.py` 不再从 `OperationalDevice` 做 MCU 验证。
2. `backend/app/models/business.py` 不再注册 `OperationalDevice` ORM。
3. `backend/app/integrations/platform_client.py` 只返回本地运营字段名，不依赖旧模型。

数据库物理清理结果: 删除前 `operational_device` 为 0 行；执行 `DROP TABLE IF EXISTS operational_device` 后，表已不存在。当前本地运营平台数据继续保留在 `operational_data`，行数为 26696。

## 建议执行顺序

1. 保留当前所有主链路表。
2. 将旧知识表组标记为 legacy，不再新增业务依赖。
3. `operational_device` 已清理；下一步可优先清理 `knowledge_embedding` 空表。
4. 再评估 `device_vehicle_relation`、`knowledge_version` 是否确实没有近期规划。
5. 最后处理旧知识表组，前提是所有脚本和 LangGraph 兼容节点迁移完毕。

## 推荐 SQL 草案

以下 SQL 只保留尚未执行的后续手动草案；`operational_device` 已执行删除:

```sql
-- 最安全候选: 空旧向量表
DROP TABLE IF EXISTS knowledge_embedding;

-- 已执行: DROP TABLE IF EXISTS operational_device;

-- 品牌表旧 MCU 验证字段: 代码已不再使用
ALTER TABLE brand_info DROP COLUMN mcu_verify_rule;

-- 需要确认无近期规划后再执行
-- DROP TABLE IF EXISTS device_vehicle_relation;
-- DROP TABLE IF EXISTS knowledge_version;
```
