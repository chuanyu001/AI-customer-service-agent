// 聊天核心逻辑

const chat = {
    sessionId: null,
    businessArea: 'dashcam',
    lastMessageId: null,
    sending: false,

    /**
     * 初始化
     */
    async init() {
        // 从URL参数获取业务领域
        const params = new URLSearchParams(window.location.search);
        this.businessArea = params.get('business_area') || 'dashcam';

        // 创建会话
        try {
            const res = await api.createSession(this.businessArea);
            if (res.code === 0 && res.data) {
                this.sessionId = res.data.session_id;
                this.renderFaqCards(res.data.faq_cards || []);
            }
        } catch (e) {
            console.error('创建会话失败:', e);
        }

        this.bindEvents();
    },

    /**
     * 绑定事件
     */
    bindEvents() {
        const input = document.getElementById('messageInput');
        const sendBtn = document.getElementById('sendBtn');
        const uploadBtn = document.getElementById('uploadBtn');
        const imageInput = document.getElementById('imageInput');

        sendBtn.addEventListener('click', () => this.sendMessage());
        input.addEventListener('keypress', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                this.sendMessage();
            }
        });

        uploadBtn.addEventListener('click', () => imageInput.click());
        imageInput.addEventListener('change', (e) => this.handleImageUpload(e));

        // 评价按钮
        document.getElementById('evaluation').addEventListener('click', (e) => {
            if (e.target.classList.contains('eval-btn')) {
                this.handleEvaluation(e.target);
            }
        });
    },

    /**
     * 发送消息
     */
    async sendMessage(text) {
        if (this.sending) return;

        const input = document.getElementById('messageInput');
        const content = text || input.value.trim();
        if (!content) return;

        this.sending = true;
        input.value = '';
        this.hideFollowUp();
        this.hideEvaluation();

        // 渲染用户消息
        this.appendMessage('user', content);

        // 显示加载动画
        const loadingId = this.appendLoading();

        try {
            const res = await api.sendMessage({
                session_id: this.sessionId,
                business_area: this.businessArea,
                content: content,
                content_type: 'text',
            });

            this.removeLoading(loadingId);

            if (res.code === 0 && res.data) {
                this.sessionId = res.data.session_id;
                this.lastMessageId = res.data.message_id;
                this.appendAssistantMessage(res.data);
            } else {
                this.appendMessage('assistant', '抱歉, 服务暂时异常, 请稍后重试。');
            }
        } catch (e) {
            this.removeLoading(loadingId);
            this.appendMessage('assistant', '网络错误, 请检查网络后重试。');
            console.error(e);
        } finally {
            this.sending = false;
        }
    },

    /**
     * 渲染AI回复
     */
    appendAssistantMessage(data) {
        // 转人工特殊处理
        if (data.should_transfer || data.response_type === 'transfer') {
            this.appendTransferNotice(data.content);
            return;
        }

        this.appendMessage('assistant', data.content, data.attachments || []);

        // 追问建议
        if (data.follow_up_questions && data.follow_up_questions.length > 0) {
            this.renderFollowUp(data.follow_up_questions);
        }

        // 评价引导
        if (data.evaluation_prompt) {
            this.showEvaluation();
        }
    },

    /**
     * 添加消息
     */
    appendMessage(role, content, attachments = []) {
        const container = document.getElementById('chatContainer');
        const div = document.createElement('div');
        div.className = `message ${role}`;

        let attachmentsHtml = '';
        if (attachments && attachments.length > 0) {
            attachmentsHtml = attachments.map(att => {
                if (att.type === 'video') {
                    return `<div class="attachment"><video src="${att.url}" controls></video></div>`;
                } else if (att.type === 'image') {
                    return `<div class="attachment"><img src="${att.url}" alt="${att.name}"></div>`;
                }
                return `<div class="attachment"><a href="${att.url}" target="_blank">${att.name || '查看附件'}</a></div>`;
            }).join('');
        }

        const avatarClass = role === 'user' ? 'user-avatar' : 'ai-avatar';
        const avatarText = role === 'user' ? '我' : 'AI';

        div.innerHTML = `
            <div class="avatar ${avatarClass}">${avatarText}</div>
            <div class="bubble">
                <div class="bubble-content">${this.escapeHtml(content)}</div>
                ${attachmentsHtml}
            </div>
        `;
        container.appendChild(div);
        this.scrollToBottom();
        return div;
    },

    /**
     * 添加加载动画
     */
    appendLoading() {
        const container = document.getElementById('chatContainer');
        const div = document.createElement('div');
        div.className = 'message assistant';
        div.id = 'loading-' + Date.now();
        div.innerHTML = `
            <div class="avatar ai-avatar">AI</div>
            <div class="bubble">
                <div class="loading-dots"><span></span><span></span><span></span></div>
            </div>
        `;
        container.appendChild(div);
        this.scrollToBottom();
        return div.id;
    },

    removeLoading(id) {
        const el = document.getElementById(id);
        if (el) el.remove();
    },

    /**
     * 渲染FAQ卡片
     */
    renderFaqCards(cards) {
        const container = document.getElementById('faqCards');
        if (!cards || cards.length === 0) return;

        container.innerHTML = cards.map(card => `
            <div class="faq-card" data-title="${this.escapeHtml(card.title)}">${this.escapeHtml(card.title)}</div>
        `).join('');

        container.querySelectorAll('.faq-card').forEach(card => {
            card.addEventListener('click', () => {
                this.sendMessage(card.dataset.title);
            });
        });
    },

    /**
     * 渲染追问建议
     */
    renderFollowUp(questions) {
        const container = document.getElementById('followUpList');
        container.innerHTML = questions.map(q => `
            <div class="follow-up-item">${this.escapeHtml(q)}</div>
        `).join('');

        container.querySelectorAll('.follow-up-item').forEach(item => {
            item.addEventListener('click', () => {
                this.sendMessage(item.textContent);
            });
        });

        document.getElementById('followUp').style.display = 'block';
    },

    hideFollowUp() {
        document.getElementById('followUp').style.display = 'none';
    },

    showEvaluation() {
        document.getElementById('evaluation').style.display = 'flex';
    },

    hideEvaluation() {
        document.getElementById('evaluation').style.display = 'none';
        document.querySelectorAll('.eval-btn').forEach(b => b.classList.remove('active'));
    },

    /**
     * 处理评价
     */
    async handleEvaluation(btn) {
        const isHelpful = btn.dataset.helpful === 'true';
        document.querySelectorAll('.eval-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');

        try {
            await api.submitFeedback(this.sessionId, this.lastMessageId, isHelpful);
            setTimeout(() => this.hideEvaluation(), 1500);
        } catch (e) {
            console.error('评价失败:', e);
        }
    },

    /**
     * 转人工提示
     */
    appendTransferNotice(text) {
        const container = document.getElementById('chatContainer');
        const div = document.createElement('div');
        div.className = 'transfer-notice';
        div.textContent = text || '正在为您转接人工客服, 请稍候...';
        container.appendChild(div);
        this.scrollToBottom();
    },

    /**
     * 图片上传
     */
    async handleImageUpload(e) {
        const file = e.target.files[0];
        if (!file) return;

        try {
            const res = await api.uploadImage(file);
            if (res.code === 0 && res.data) {
                const vin = res.data.recognized_vin;
                if (vin) {
                    this.appendMessage('user', `[已识别VIN: ${vin}]`);
                    this.sendMessage(`我的车架号是 ${vin}, 帮我查询设备信息`);
                } else {
                    this.appendMessage('assistant', '未能识别行驶证上的VIN码, 请手动输入车架号。');
                }
            }
        } catch (err) {
            this.appendMessage('assistant', '图片上传失败, 请重试。');
        } finally {
            e.target.value = '';
        }
    },

    /**
     * 渲染FAQ卡片区域
     */
    renderFaqCards(cards) {
        const container = document.getElementById('faqCards');
        if (!cards || cards.length === 0) {
            document.getElementById('faqSection').style.display = 'none';
            return;
        }

        container.innerHTML = cards.map(card => `
            <div class="faq-card" data-title="${this.escapeHtml(card.title)}">${this.escapeHtml(card.title)}</div>
        `).join('');

        container.querySelectorAll('.faq-card').forEach(card => {
            card.addEventListener('click', () => {
                this.sendMessage(card.dataset.title);
            });
        });
    },

    scrollToBottom() {
        const container = document.getElementById('chatContainer');
        setTimeout(() => {
            container.scrollTop = container.scrollHeight;
        }, 50);
    },

    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text || '';
        return div.innerHTML;
    },
};

// 启动
window.addEventListener('DOMContentLoaded', () => chat.init());
