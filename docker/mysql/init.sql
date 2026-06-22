-- AI客服Agent 数据库初始化脚本 (自动生成)
-- 包含20张表, 由 SQLAlchemy ORM 模型生成

SET NAMES utf8mb4;
SET FOREIGN_KEY_CHECKS = 0;


CREATE TABLE answer_feedback (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	conversation_id INTEGER NOT NULL, 
	message_id INTEGER NOT NULL, 
	rating INTEGER COMMENT '评分: 1-5', 
	is_helpful BOOL COMMENT '是否有帮助', 
	feedback_type VARCHAR(32) COMMENT 'positive/negative/neutral', 
	comment TEXT COMMENT '文字反馈', 
	created_at DATETIME DEFAULT now(), 
	PRIMARY KEY (id), 
	FOREIGN KEY(conversation_id) REFERENCES conversation (id) ON DELETE CASCADE, 
	UNIQUE (message_id), 
	FOREIGN KEY(message_id) REFERENCES message (id) ON DELETE CASCADE
)

;


CREATE TABLE brand_info (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	brand_code VARCHAR(32) NOT NULL COMMENT '品牌编码', 
	brand_name VARCHAR(64) NOT NULL COMMENT '品牌名称 (极目(GPS+BD))', 
	short_name VARCHAR(32) COMMENT '简称', 
	aliases JSON COMMENT '别名列表 ["极目","鱼快"]', 
	business_area VARCHAR(32) COMMENT '业务领域', 
	priority INTEGER COMMENT '识别优先级 (1-7)', 
	id_format_rules JSON COMMENT 'ID格式正则规则', 
	mcu_verify_rule VARCHAR(256) COMMENT 'MCU验证规则', 
	contact_phone VARCHAR(32) COMMENT '厂家电话', 
	is_active BOOL, 
	created_at DATETIME DEFAULT now(), 
	updated_at DATETIME DEFAULT now(), 
	PRIMARY KEY (id), 
	UNIQUE (brand_code)
)

;


CREATE TABLE brand_mapping (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	brand_id INTEGER NOT NULL, 
	match_type VARCHAR(32) NOT NULL COMMENT '匹配类型: vin_prefix/terminal_prefix/device_model', 
	match_value VARCHAR(128) NOT NULL COMMENT '匹配值', 
	description VARCHAR(256) COMMENT '描述', 
	created_at DATETIME DEFAULT now(), 
	PRIMARY KEY (id), 
	FOREIGN KEY(brand_id) REFERENCES brand_info (id) ON DELETE CASCADE
)

;


CREATE TABLE conversation (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	session_id VARCHAR(128) NOT NULL COMMENT '会话UUID', 
	user_id VARCHAR(128) COMMENT '用户ID (openid)', 
	user_type VARCHAR(32) COMMENT '用户类型: guest/registered', 
	channel VARCHAR(32) COMMENT '渠道: miniprogram/web', 
	entry_point VARCHAR(64) COMMENT '入口: 1_module/2_assistant/3_personal', 
	business_area VARCHAR(32) COMMENT '业务领域', 
	status VARCHAR(32) COMMENT '状态: active/transferred/resolved/closed', 
	ai_resolved BOOL COMMENT 'AI是否解决', 
	transfer_count INTEGER COMMENT '累计转人工次数', 
	message_count INTEGER COMMENT '消息总数', 
	consecutive_fail INTEGER COMMENT '连续未解决轮次', 
	started_at DATETIME DEFAULT now(), 
	ended_at DATETIME COMMENT '结束时间', 
	metadata JSON COMMENT '扩展数据', 
	created_at DATETIME DEFAULT now(), 
	updated_at DATETIME DEFAULT now(), 
	PRIMARY KEY (id)
)

;


CREATE TABLE data_dictionary (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	dict_type VARCHAR(64) NOT NULL COMMENT '字典类型', 
	dict_code VARCHAR(64) NOT NULL COMMENT '字典编码', 
	dict_value VARCHAR(256) NOT NULL COMMENT '字典值', 
	display_order INTEGER COMMENT '排序', 
	is_active BOOL COMMENT '是否启用', 
	created_at DATETIME DEFAULT now(), 
	PRIMARY KEY (id), 
	CONSTRAINT uq_dict_type_code UNIQUE (dict_type, dict_code)
)

;


CREATE TABLE device_vehicle_relation (
	id BIGINT NOT NULL AUTO_INCREMENT, 
	device_id BIGINT COMMENT '设备ID', 
	vehicle_id VARCHAR(64) COMMENT '车辆标识', 
	sim_iccid VARCHAR(32) COMMENT 'SIM卡号', 
	relation_type VARCHAR(32) COMMENT 'current/history', 
	effective_time DATETIME COMMENT '生效时间', 
	expire_time DATETIME COMMENT '失效时间', 
	created_at DATETIME DEFAULT now(), 
	PRIMARY KEY (id)
)

;


CREATE TABLE event_log (
	id BIGINT NOT NULL AUTO_INCREMENT, 
	event_type VARCHAR(64) NOT NULL COMMENT '事件类型: workflow_node/llm_call/api_call/error', 
	event_name VARCHAR(128) NOT NULL COMMENT '事件名称', 
	event_data JSON COMMENT '事件数据', 
	conversation_id INTEGER COMMENT '关联会话ID', 
	user_id VARCHAR(128) COMMENT '用户ID', 
	duration_ms INTEGER COMMENT '耗时(毫秒)', 
	created_at DATETIME DEFAULT now(), 
	PRIMARY KEY (id)
)

;


CREATE TABLE faq_card (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	card_code VARCHAR(64) NOT NULL COMMENT '卡片编码', 
	business_area VARCHAR(32) NOT NULL COMMENT '业务领域', 
	title VARCHAR(256) NOT NULL COMMENT '卡片标题', 
	knowledge_id INTEGER COMMENT '关联知识ID', 
	category VARCHAR(64) COMMENT '分类', 
	display_order INTEGER COMMENT '显示顺序', 
	icon_url VARCHAR(512) COMMENT '图标URL', 
	is_active BOOL COMMENT '是否启用', 
	click_count INTEGER COMMENT '点击量', 
	created_at DATETIME DEFAULT now(), 
	updated_at DATETIME DEFAULT now(), 
	PRIMARY KEY (id), 
	FOREIGN KEY(knowledge_id) REFERENCES knowledge_answer (id) ON DELETE SET NULL
)

;


CREATE TABLE field_dictionary (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	backend_field VARCHAR(128) NOT NULL COMMENT '后端字段名', 
	display_name VARCHAR(128) NOT NULL COMMENT '驾驶员友好名称', 
	business_area VARCHAR(32) COMMENT '业务领域', 
	field_type VARCHAR(32) COMMENT '字段类型: string/int/datetime', 
	can_show_customer BOOL COMMENT '是否可展示给客户', 
	description VARCHAR(256) COMMENT '使用说明', 
	created_at DATETIME DEFAULT now(), 
	PRIMARY KEY (id)
)

;


CREATE TABLE handoff_ticket (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	ticket_id VARCHAR(64) NOT NULL COMMENT '工单UUID', 
	conversation_id INTEGER NOT NULL, 
	reason_type VARCHAR(64) NOT NULL COMMENT '原因类型: consecutive_fail/keyword/user_request/out_of_scope/risk', 
	reason_detail VARCHAR(256) COMMENT '转人工详细原因', 
	summary TEXT COMMENT 'AI对话摘要', 
	collected_info JSON COMMENT '已收集信息 (品牌/VIN/终端号)', 
	business_context TEXT COMMENT '业务上下文 (运营数据查询结果)', 
	priority VARCHAR(16) COMMENT '优先级: low/normal/high/urgent', 
	status VARCHAR(32) COMMENT '状态: pending/assigned/processing/resolved/closed', 
	qiyu_session_id VARCHAR(128) COMMENT '七鱼会话ID', 
	assigned_to VARCHAR(64) COMMENT '分配客服', 
	contact_info JSON COMMENT '联系方式 (非工作时间)', 
	created_at DATETIME DEFAULT now(), 
	updated_at DATETIME DEFAULT now(), 
	PRIMARY KEY (id), 
	FOREIGN KEY(conversation_id) REFERENCES conversation (id) ON DELETE CASCADE
)

;


CREATE TABLE knowledge_answer (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	knowledge_code VARCHAR(64) NOT NULL COMMENT '知识唯一编码', 
	business_area VARCHAR(32) NOT NULL COMMENT '业务领域: dashcam/wifi/data/refueling', 
	category_l1 VARCHAR(64) COMMENT '一级分类 (故障排查/设备信息/操作指引...)', 
	category_l2 VARCHAR(64) COMMENT '二级分类 (4G离线/查询SIM/按键重启...)', 
	manufacturer VARCHAR(128) COMMENT '适用厂商 (通用/极目/航天/雅迅/启明/有为)', 
	standard_question VARCHAR(512) NOT NULL COMMENT '标准问题', 
	standard_answer TEXT NOT NULL COMMENT '标准回答', 
	answer_type VARCHAR(32) COMMENT '回答类型: text/video/image/mixed', 
	need_brand BOOL COMMENT '是否需要品牌识别 (123/144=1)', 
	need_attachment BOOL COMMENT '是否需要附件 (15/144=1)', 
	risk_level VARCHAR(16) COMMENT '风险等级: low/medium/high', 
	auto_reply BOOL COMMENT '是否允许自动回复', 
	transfer_condition TEXT COMMENT '转人工条件描述', 
	status VARCHAR(32) COMMENT '状态: draft/reviewing/published/offline', 
	version INTEGER COMMENT '版本号', 
	source_file VARCHAR(256) COMMENT '来源文件', 
	reviewed_by VARCHAR(64) COMMENT '审核人', 
	created_at DATETIME DEFAULT now(), 
	updated_at DATETIME DEFAULT now(), 
	PRIMARY KEY (id)
)

;


CREATE TABLE knowledge_attachment (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	knowledge_id INTEGER NOT NULL, 
	file_name VARCHAR(256) NOT NULL COMMENT '文件名', 
	file_type VARCHAR(32) COMMENT '文件类型: image/video/document/link', 
	file_url VARCHAR(512) NOT NULL COMMENT '文件URL', 
	file_size INTEGER COMMENT '文件大小(字节)', 
	display_order INTEGER COMMENT '显示顺序', 
	created_at DATETIME DEFAULT now(), 
	PRIMARY KEY (id), 
	FOREIGN KEY(knowledge_id) REFERENCES knowledge_answer (id) ON DELETE CASCADE
)

;


CREATE TABLE knowledge_keyword (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	knowledge_id INTEGER NOT NULL, 
	keyword VARCHAR(128) NOT NULL COMMENT '关键词', 
	keyword_type VARCHAR(32) COMMENT '类型: normal/synonym/business_term', 
	weight INTEGER COMMENT '权重', 
	created_at DATETIME DEFAULT now(), 
	PRIMARY KEY (id), 
	FOREIGN KEY(knowledge_id) REFERENCES knowledge_answer (id) ON DELETE CASCADE
)

;


CREATE TABLE knowledge_question_variant (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	knowledge_id INTEGER NOT NULL, 
	variant_text VARCHAR(512) NOT NULL COMMENT '用户问法变体', 
	source VARCHAR(32) COMMENT '来源: manual/import/real_conversation', 
	is_active BOOL, 
	created_at DATETIME DEFAULT now(), 
	PRIMARY KEY (id), 
	FOREIGN KEY(knowledge_id) REFERENCES knowledge_answer (id) ON DELETE CASCADE
)

;


CREATE TABLE knowledge_version (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	knowledge_id INTEGER NOT NULL, 
	version INTEGER NOT NULL COMMENT '版本号', 
	snapshot JSON NOT NULL COMMENT '知识快照(完整JSON)', 
	change_type VARCHAR(32) COMMENT '变更类型: create/update/publish/offline', 
	change_note TEXT COMMENT '变更说明', 
	changed_by VARCHAR(64) COMMENT '变更人', 
	created_at DATETIME DEFAULT now(), 
	PRIMARY KEY (id), 
	FOREIGN KEY(knowledge_id) REFERENCES knowledge_answer (id) ON DELETE CASCADE
)

;


CREATE TABLE message (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	conversation_id INTEGER NOT NULL, 
	message_id VARCHAR(128) NOT NULL COMMENT '消息UUID', 
	seq INTEGER NOT NULL COMMENT '会话内序号', 
	`role` VARCHAR(16) NOT NULL COMMENT '角色: user/assistant/system', 
	content TEXT NOT NULL COMMENT '消息内容', 
	content_type VARCHAR(32) COMMENT 'text/image/voice/video/card', 
	media_url VARCHAR(512) COMMENT '媒体URL', 
	action VARCHAR(32) COMMENT '动作: auto_reply/ask_info/query_result/transfer', 
	reply_type VARCHAR(32) COMMENT '回复类型: knowledge_answer/slot_collection/query_result/handoff/greeting/fallback', 
	knowledge_id INTEGER COMMENT '关联知识ID', 
	knowledge_code VARCHAR(64) COMMENT '关联知识编码', 
	query_type_code VARCHAR(64) COMMENT '查询类型编码', 
	query_data JSON COMMENT '查询数据', 
	intent_result JSON COMMENT '意图识别结果', 
	metadata JSON COMMENT '扩展数据', 
	created_at DATETIME DEFAULT now(), 
	PRIMARY KEY (id), 
	FOREIGN KEY(conversation_id) REFERENCES conversation (id) ON DELETE CASCADE
)

;


CREATE TABLE operational_device (
	id BIGINT NOT NULL AUTO_INCREMENT, 
	business_area VARCHAR(32) COMMENT '业务领域', 
	vin VARCHAR(32) COMMENT '车架号', 
	plate_number VARCHAR(16) COMMENT '车牌号', 
	terminal_id VARCHAR(64) COMMENT '终端号', 
	sim_iccid VARCHAR(32) COMMENT 'SIM卡ICCID', 
	brand_id INTEGER COMMENT '品牌ID', 
	device_model VARCHAR(64) COMMENT '设备型号', 
	online_status VARCHAR(16) COMMENT '在线状态', 
	gps_status VARCHAR(16) COMMENT '定位状态', 
	service_provider VARCHAR(64) COMMENT '服务商', 
	service_expiry DATETIME COMMENT '服务到期日', 
	firmware_version VARCHAR(32) COMMENT '固件版本', 
	mcu_version VARCHAR(32) COMMENT 'MCU版本', 
	last_online_time DATETIME COMMENT '最后在线时间', 
	metadata JSON COMMENT '扩展字段', 
	created_at DATETIME DEFAULT now(), 
	updated_at DATETIME DEFAULT now(), 
	PRIMARY KEY (id)
)

;


CREATE TABLE optimization_sample (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	sample_type VARCHAR(64) NOT NULL COMMENT '类型: no_match/low_confidence/bad_answer/user_complaint', 
	user_query TEXT NOT NULL COMMENT '用户原始问题', 
	intent_result JSON COMMENT '意图识别结果', 
	actual_intent VARCHAR(64) COMMENT '人工标注实际意图', 
	suggested_knowledge_id INTEGER COMMENT '建议关联知识ID', 
	correct_answer TEXT COMMENT '正确答案', 
	notes TEXT COMMENT '备注', 
	status VARCHAR(32) COMMENT '状态: pending/reviewing/annotated/applied', 
	conversation_id INTEGER COMMENT '关联会话ID', 
	message_id INTEGER COMMENT '关联消息ID', 
	reviewed_by VARCHAR(64) COMMENT '审核人', 
	reviewed_at DATETIME COMMENT '审核时间', 
	created_at DATETIME DEFAULT now(), 
	updated_at DATETIME DEFAULT now(), 
	PRIMARY KEY (id)
)

;


CREATE TABLE query_intent_config (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	query_type_code VARCHAR(64) NOT NULL COMMENT '查询类型编码 (QRY001-QRY013)', 
	display_name VARCHAR(128) NOT NULL COMMENT '查询意图名称', 
	business_area VARCHAR(32) COMMENT '业务领域', 
	required_slots JSON COMMENT '必填槽位配置 [{field, display, type, collect_prompt}]', 
	data_source VARCHAR(64) COMMENT '数据源: operational_db', 
	match_conditions JSON COMMENT '匹配条件 [{"field":"vin","op":"eq"}]', 
	return_fields JSON COMMENT '返回字段 [{"backend":"vin","display":"车架号"}]', 
	reply_template_normal TEXT COMMENT '正常结果回复模板 ({{}}占位)', 
	reply_template_empty TEXT COMMENT '空结果回复模板', 
	escalation_rule JSON COMMENT '升级规则 {"max_retry":2,"empty_transfer":true}', 
	auto_reply BOOL COMMENT '是否允许自动回复', 
	is_active BOOL COMMENT '是否启用', 
	created_at DATETIME DEFAULT now(), 
	updated_at DATETIME DEFAULT now(), 
	PRIMARY KEY (id)
)

;


CREATE TABLE system_config (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	config_key VARCHAR(64) NOT NULL COMMENT '配置键', 
	config_value TEXT COMMENT '配置值', 
	config_type VARCHAR(32) COMMENT '类型: string/int/float/bool/json', 
	description VARCHAR(256) COMMENT '说明', 
	is_editable BOOL COMMENT '是否可编辑', 
	created_at DATETIME DEFAULT now(), 
	updated_at DATETIME DEFAULT now(), 
	PRIMARY KEY (id)
)

;

SET FOREIGN_KEY_CHECKS = 1;
