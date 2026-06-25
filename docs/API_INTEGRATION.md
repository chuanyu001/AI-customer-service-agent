# 小程序 API 对接文档

> 版本：1.0 | 更新：2026-06-26

## 服务地址

```
生产环境：待定（同事部署后提供）
测试环境：http://localhost:8000
```

## 接口列表

小程序只需对接 **2 个接口**。

---

### 1. 创建会话

```
POST /api/v1/chat/sessions
```

**请求**（可选，不传则全部用默认值）：

```json
{
  "user_id": "用户的openid",
  "business_area": "dashcam",
  "entry_point": "1"
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| user_id | string | 否 | 用户标识（openid） |
| business_area | string | 否 | 业务入口，默认 `dashcam` |
| entry_point | string | 否 | 入口来源：`1`=首页模块 / `2`=AI助手 / `3`=个人中心 |

**`business_area` 取值**：

| 值 | 对应业务 |
|----|----------|
| `dashcam` | 行车记录仪 |
| `wifi` | WiFi 套餐 |
| `data` | 基础流量 |
| `refueling` | 折扣加油 |

> 即使不传 `business_area`，后端也会根据用户消息内容自动识别业务域。建议小程序端根据用户点击的入口传入对应值。

**响应**：

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "session_id": "e7bd3f8e-6629-4915-8070-c3ce49d06b0b",
    "welcome_message": "您好! 我是AI客服助手, 请问有什么可以帮您的?",
    "faq_cards": [
      {"id": 1, "card_code": "DASHCAM_FAQ_001", "title": "设备离线怎么办？", "category": "4G离线排查"}
    ]
  }
}
```

**拿到 `session_id` 后，后续消息都带上它。**

---

### 2. 发送消息（核心）

```
POST /api/v1/chat/message
```

**请求**：

```json
{
  "session_id": "e7bd3f8e-6629-4915-8070-c3ce49d06b0b",
  "content": "设备离线怎么办",
  "business_area": "dashcam",
  "content_type": "text",
  "media_url": null
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| session_id | string | 首次为空，后续必传 | 会话 ID |
| content | string | **必填** | 用户消息，1-2000 字符 |
| business_area | string | 否 | 默认 `dashcam` |
| content_type | string | 否 | `text` / `image` / `voice` |
| media_url | string | 否 | 图片/语音 URL |

**响应**：

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "session_id": "e7bd3f8e-6629-4915-8070-c3ce49d06b0b",
    "message_id": "84fe3dae-cad3-4c3e-b5bc-ac7e82573323",
    "seq": 2,
    "role": "assistant",
    "content": "您可以按照以下路径操作重启设备：菜单--设备操作管理--主机设备重启",
    "response_type": "knowledge_answer",
    "knowledge_code": "JL0020",
    "attachments": [],
    "follow_up_questions": ["SIM卡怎么拔插？", "设备不定位怎么处理？"],
    "should_transfer": false,
    "need_more_info": false,
    "ask_slot_prompt": null,
    "evaluation_prompt": "这个回答有帮助吗？"
  }
}
```

---

## response_type 含义（小程序必须处理）

| 值 | 含义 | 小程序表现 |
|----|------|-----------|
| `greeting` | 欢迎语 | 展示 `content` + `faq_cards` |
| `knowledge_answer` | 知识库答案 | 展示 `content`，可附带 `attachments`（视频/图片）和 `follow_up_questions` |
| `ask_slot` | 追问用户补充信息 | 展示 `content` + `ask_slot_prompt`，引导用户输入 |
| `transfer` | 转人工 | `should_transfer=true`，展示 `content`，结束 AI 会话 |
| `query_result` | 运营平台查询结果 | 展示 `content`（设备信息等） |
| `fallback` | 兜底回复 | 展示 `content`，建议用户换个方式描述或转人工 |

---

## 关键字段速查

| 字段 | 类型 | 说明 |
|------|------|------|
| session_id | string | 会话 ID，同一次对话保持不变 |
| content | string | 回复正文，直接展示给用户 |
| response_type | string | 回复类型，决定交互方式 |
| knowledge_code | string | 命中的知识编码（可忽略） |
| attachments | array | 附件列表，`{"type":"video","url":"/videos/xxx.mp4","name":"标题"}` |
| follow_up_questions | array | 建议追问，展示为快捷按钮 |
| should_transfer | bool | `true` 时结束 AI 对话，切换人工 |
| need_more_info | bool | `true` 时引导用户继续输入 |
| ask_slot_prompt | string | 追问提示语 |
| evaluation_prompt | string | 评价引导，展示为"有帮助/无帮助"按钮 |

---

## 完整调用流程

```
1. 用户进入客服页
   → POST /api/v1/chat/sessions?business_area=dashcam
   → 拿到 session_id + welcome_message + faq_cards

2. 用户点 FAQ 或输入文字
   → POST /api/v1/chat/message
      {"session_id":"xxx", "content":"设备离线怎么办", "business_area":"dashcam"}
   → response_type="knowledge_answer" → 展示答案

3. 系统追问品牌
   → response_type="ask_slot", need_more_info=true
   → 展示追问语 + 品牌选项

4. 用户选择品牌
   → POST /api/v1/chat/message {"session_id":"xxx", "content":"雅迅"}
   → response_type="knowledge_answer" → 展示该品牌答案

5. 转人工
   → response_type="transfer", should_transfer=true
   → 结束 AI 会话，展示转接提示
```

---

## 注意事项

1. **session_id 贯穿全程**：同一通对话用同一个 session_id
2. **business_area 前端可选**：不传后端也会自动识别，但传了更准确
3. **附件 URL 是相对路径**：视频 `/videos/xxx.mp4` 需拼上服务地址
4. **超时**：正常响应 < 1 秒（LLM 降级时），首次请求可能需要等 embedding 模型预热（约 7 秒）
5. **错误**：HTTP 200 + `response_type="fallback"` 表示没匹配到，不会返回 500
