// API 请求封装
// 后端 API 与前端同源托管 (FastAPI 挂载前端 + 提供 /api/v1)
const API_BASE = window.location.origin + '/api/v1';

const api = {
    /**
     * 创建会话
     */
    async createSession(businessArea = 'dashcam') {
        const url = `${API_BASE}/chat/sessions?business_area=${businessArea}`;
        const res = await fetch(url, { method: 'POST' });
        return res.json();
    },

    /**
     * 发送消息 (核心接口)
     */
    async sendMessage(data) {
        const res = await fetch(`${API_BASE}/chat/message`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data),
        });
        return res.json();
    },

    /**
     * 获取会话历史
     */
    async getSession(sessionId) {
        const res = await fetch(`${API_BASE}/chat/sessions/${sessionId}`);
        return res.json();
    },

    /**
     * 提交评价
     */
    async submitFeedback(sessionId, messageId, isHelpful, rating = null) {
        const res = await fetch(`${API_BASE}/evaluation/feedback`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                session_id: sessionId,
                message_id: messageId,
                is_helpful: isHelpful,
                rating: rating,
                feedback_type: isHelpful ? 'positive' : 'negative',
            }),
        });
        return res.json();
    },

    /**
     * 获取FAQ卡片
     */
    async getFaqCards(businessArea = 'dashcam') {
        const res = await fetch(`${API_BASE}/knowledge/faq-cards?business_area=${businessArea}`);
        return res.json();
    },

    /**
     * 上传图片
     */
    async uploadImage(file) {
        const formData = new FormData();
        formData.append('file', file);
        const res = await fetch(`${API_BASE}/chat/upload`, {
            method: 'POST',
            body: formData,
        });
        return res.json();
    },
};
