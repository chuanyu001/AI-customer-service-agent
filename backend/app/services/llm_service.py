# LLM 服务抽象层
# 支持 local (Ollama) / doubao (豆包) / mock 三种provider

from abc import ABC, abstractmethod
from typing import List, Dict, Optional
import json
import logging
from app.core.config import settings

logger = logging.getLogger(__name__)


class LLMProvider(ABC):
    """LLM 提供者抽象基类"""

    @abstractmethod
    async def chat(self, messages: List[Dict], **kwargs) -> str:
        """通用对话"""
        pass

    @abstractmethod
    async def classify(self, text: str, labels: List[str], context: str = "") -> Dict:
        """意图分类 → {label, confidence}"""
        pass

    @abstractmethod
    async def summarize(self, text: str, max_length: int = 200) -> str:
        """文本摘要"""
        pass

    @abstractmethod
    async def rewrite(self, query: str, history: List[str]) -> str:
        """问题改写 (指代消解+上下文补全)"""
        pass

    @abstractmethod
    async def retrieve(self, query: str, candidates: List[Dict], top_k: int = 5) -> List[int]:
        """从知识库候选中选出最相关的 (大模型全量检索/rerank)

        Args:
            query: 用户问题
            candidates: [{"id": 知识ID, "question": "标准问题"}, ...]
            top_k: 返回数量上限

        Returns:
            按相关度降序的 knowledge_id 列表 (最多top_k条)
        """
        pass

    @abstractmethod
    async def polish(self, query: str, answer: str) -> str:
        """对知识库标准答案做受限润色 (只调格式/语气, 不改内容)

        Args:
            query: 用户问题
            answer: 知识库标准答案原文

        Returns:
            润色后的回复。严禁修改/删减原文的步骤、参数、数值、条件、转人工提示。
        """
        pass

    @staticmethod
    def _parse_json_response(response: str, default: Dict) -> Dict:
        """安全解析JSON响应 (基类共享, 子类通用)"""
        try:
            response = response.strip()
            if "```json" in response:
                response = response.split("```json")[1].split("```")[0]
            elif "```" in response:
                response = response.split("```")[1].split("```")[0]
            return json.loads(response)
        except (json.JSONDecodeError, IndexError):
            return default


class LocalLLMProvider(LLMProvider):
    """本地 LLM (Ollama + Qwen2.5)"""

    def __init__(self):
        from openai import AsyncOpenAI
        self.client = AsyncOpenAI(
            base_url=settings.LLM_BASE_URL,
            api_key="ollama",  # Ollama不需要真实key
        )
        self.model = settings.LLM_MODEL
        self.temperature = settings.LLM_TEMPERATURE
        self.max_tokens = settings.LLM_MAX_TOKENS

    async def chat(self, messages: List[Dict], **kwargs) -> str:
        response = await self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=kwargs.get("temperature", self.temperature),
            max_tokens=kwargs.get("max_tokens", self.max_tokens),
        )
        return response.choices[0].message.content.strip()

    async def classify(self, text: str, labels: List[str], context: str = "") -> Dict:
        """意图分类 - Few-shot prompt"""
        label_str = ", ".join(labels)
        system_prompt = (
            f"你是一个客服意图分类器。将用户消息分类到以下意图之一: {label_str}。\n"
            "只返回JSON格式: {\"label\": \"意图名\", \"confidence\": 0.0-1.0}\n"
            "不要返回任何其他内容。"
        )

        user_content = text
        if context:
            user_content = f"对话历史: {context}\n当前消息: {text}"

        response = await self.chat([
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ])

        return self._parse_json_response(response, {"label": "unknown", "confidence": 0.0})

    async def summarize(self, text: str, max_length: int = 200) -> str:
        response = await self.chat([
            {"role": "system", "content": f"将以下对话内容总结为不超过{max_length}字的摘要。只返回摘要文本。"},
            {"role": "user", "content": text},
        ])
        return response[:max_length]

    async def rewrite(self, query: str, history: List[str]) -> str:
        """问题改写: 补全省略 + 指代消解"""
        if not history:
            return query

        history_text = "\n".join(history[-3:])  # 最近3轮
        response = await self.chat([
            {"role": "system", "content": (
                "你是一个问题改写助手。根据对话历史, 将用户当前的问题补全为完整问题。\n"
                "规则:\n"
                "1. 将指代词(它/这个/那个)替换为具体实体\n"
                "2. 将省略的成分补全\n"
                "3. 如果问题已经完整, 直接返回原问题\n"
                "只返回改写后的问题, 不要解释。"
            )},
            {"role": "user", "content": f"对话历史:\n{history_text}\n\n当前问题: {query}\n\n改写后的问题:"},
        ])
        return response.strip() or query

    async def retrieve(self, query: str, candidates: List[Dict], top_k: int = 5) -> List[int]:
        """大模型从知识库候选中选最相关的 top_k (逻辑同DoubaoProvider)"""
        if not candidates:
            return []
        cand_text = "\n".join(f"[{c['id']}] {c['question']}" for c in candidates)
        system_prompt = (
            "你是客服知识库检索助手。从下面的知识库标准问题列表中, "
            f"选出与用户问题最相关的最多{top_k}条, 按相关度从高到低排序。\n"
            "判断依据: 语义相关 (不要求字面相同)。\n"
            "如果没有任何相关的, 返回空列表。\n"
            '只返回JSON: {"ids": [id1, id2, ...]}, 不要任何解释。'
        )
        user_content = f"用户问题: {query}\n\n知识库标准问题列表:\n{cand_text}"
        response = await self.chat([
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ])
        parsed = self._parse_json_response(response, {"ids": []})
        ids = parsed.get("ids", [])
        valid_ids = {c["id"] for c in candidates}
        return [i for i in ids if i in valid_ids][:top_k]

    async def polish(self, query: str, answer: str) -> str:
        """受限润色 (逻辑同DoubaoProvider)"""
        if not answer or not answer.strip():
            return answer
        system_prompt = (
            "你是客服回复润色助手。把知识库标准答案润色成更友好易读的客服回复。\n"
            "严禁修改/删减/增加任何步骤、参数、数值、条件、转人工提示。\n"
            "菜单路径、按键操作、规格参数必须原样保留。不得凭空补充信息。\n"
            "允许: 调整语气、加项目符号、分段。只返回润色后回复。"
        )
        try:
            response = await self.chat([
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"用户问题: {query}\n\n标准答案:\n{answer}\n\n润色后回复:"},
            ])
            if response and len(response.strip()) < len(answer.strip()) * 0.5:
                return answer
            return response.strip() or answer
        except Exception:
            return answer

    @staticmethod
    def _parse_json_response(response: str, default: Dict) -> Dict:
        """安全解析JSON响应 (LocalLLMProvider 本地保留, 逻辑同基类)"""
        try:
            response = response.strip()
            if "```json" in response:
                response = response.split("```json")[1].split("```")[0]
            elif "```" in response:
                response = response.split("```")[1].split("```")[0]
            return json.loads(response)
        except (json.JSONDecodeError, IndexError):
            return default


class DoubaoProvider(LLMProvider):
    """火山方舟 / 豆包 API (OpenAI 兼容)

    配置 (.env):
        LLM_PROVIDER=doubao
        LLM_BASE_URL=https://ark.cn-beijing.volces.com/api/v3
        LLM_API_KEY=<火山方舟控制台获取的 API Key>
        LLM_MODEL=<推理接入点 ID, 如 ep-2024xxxx-xxxxx>
    """

    def __init__(self):
        from openai import AsyncOpenAI
        import httpx
        if not settings.LLM_API_KEY:
            raise ValueError(
                "DoubaoProvider 需要 LLM_API_KEY, 请在 .env 中配置火山方舟 API Key"
            )
        # 显式禁用代理: 避免httpx读取Windows系统代理(科学上网工具开启时会导致连不上火山方舟)
        self.client = AsyncOpenAI(
            base_url=settings.LLM_BASE_URL,
            api_key=settings.LLM_API_KEY,
            http_client=httpx.AsyncClient(proxy=None, timeout=settings.LLM_TIMEOUT),
        )
        self.model = settings.LLM_MODEL

    async def chat(self, messages: List[Dict], **kwargs) -> str:
        response = await self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=kwargs.get("temperature", 0.3),
            max_tokens=kwargs.get("max_tokens", 2048),
        )
        return response.choices[0].message.content.strip()

    async def classify(self, text: str, labels: List[str], context: str = "") -> Dict:
        """意图分类 — 客服场景优化版prompt

        策略: 默认归 knowledge_query (客服场景大部分是咨询),
        只有明确特征才分到其他类。
        """
        system_prompt = (
            "你是行车记录仪客服意图分类器。将用户消息分到以下意图之一:\n"
            "- knowledge_query: 咨询设备使用/故障/操作/参数等问题 (默认类别)\n"
            "- live_query: 需要查询用户自己的设备数据 (查SIM卡号/终端号/在线状态/套餐/到期等)\n"
            "- transfer_request: 明确要求转人工/找客服/找真人\n"
            "- greeting: 问候/寒暄 (你好/在吗)\n"
            "- unknown: 完全无法理解且不属于以上任何类\n\n"
            "重要规则:\n"
            "1. 模糊的故障描述 (如'设备没法用了''开不了机''不工作') 都归 knowledge_query\n"
            "2. 只有当消息明确要求查询'我的/这个设备的'具体数据时才归 live_query\n"
            "3. 尽量避免用 unknown, 实在判断不了再用\n"
            "只返回JSON: {\"label\": \"...\", \"confidence\": 0.0-1.0}"
        )
        user_content = f"对话历史: {context}\n当前消息: {text}" if context else text
        response = await self.chat([
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ])
        return LocalLLMProvider._parse_json_response(response, {"label": "unknown", "confidence": 0.0})

    async def summarize(self, text: str, max_length: int = 200) -> str:
        response = await self.chat([
            {"role": "system", "content": f"总结以下对话为不超过{max_length}字的摘要。"},
            {"role": "user", "content": text},
        ])
        return response[:max_length]

    async def rewrite(self, query: str, history: List[str]) -> str:
        if not history:
            return query
        history_text = "\n".join(history[-3:])
        response = await self.chat([
            {"role": "system", "content": "根据对话历史, 将用户问题补全为完整问题。只返回改写后的问题。"},
            {"role": "user", "content": f"对话历史:\n{history_text}\n\n当前问题: {query}"},
        ])
        return response.strip() or query

    async def retrieve(self, query: str, candidates: List[Dict], top_k: int = 5) -> List[int]:
        """大模型从知识库候选中选最相关的 top_k

        prompt 里把所有候选(主题标签+标准问题)列出来, 让大模型返回最相关的ID列表。
        主题标签帮助大模型理解知识分组, 例如同主题下有6个品牌的对应知识。
        """
        if not candidates:
            return []

        # 拼接候选文本: [ID] [主题] 标准问题
        # 主题为空时不显示标签
        def _fmt(c):
            cat = c.get("category", "")
            if cat:
                return f"[{c['id']}] [{cat}] {c['question']}"
            return f"[{c['id']}] {c['question']}"

        cand_text = "\n".join(_fmt(c) for c in candidates)
        system_prompt = (
            "你是客服知识库检索助手。从下面的知识库条目列表中, "
            f"选出与用户问题最相关的最多{top_k}条, 按相关度从高到低排序。\n"
            "每条格式: [ID] [主题分类] 标准问题。方括号中的主题分类是知识归属类别, "
            "同一主题下通常有多个品牌对应的同类知识。\n"
            "判断依据: 语义相关 (不要求字面相同), 优先匹配主题分类。\n"
            "示例:\n"
            "  用户问'设备离线了怎么办' → 优先选主题为'4G离线排查方法'的条目\n"
            "  用户问'设备没法用了' → 优先选主题为'4G离线排查方法'的条目\n"
            "  用户问'怎么查SIM卡号' → 优先选主题为'查询SIM/ID方法'的条目\n"
            "  用户问'设备怎么重启' → 优先选主题为'按键重启方法'的条目\n"
            "重要: 宁可多选也不要漏选。同主题下多个品牌的知识可一起返回。\n"
            "如果确实完全无关, 返回空列表。\n"
            '只返回JSON: {"ids": [id1, id2, ...]}, 不要任何解释。'
        )
        user_content = f"用户问题: {query}\n\n知识库条目列表:\n{cand_text}"

        response = await self.chat([
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ])

        parsed = self._parse_json_response(response, {"ids": []})
        ids = parsed.get("ids", [])
        valid_ids = {c["id"] for c in candidates}
        return [i for i in ids if i in valid_ids][:top_k]

    async def polish(self, query: str, answer: str) -> str:
        """对知识库标准答案做受限润色

        约束: 只能调整语气/格式/排版, 严禁修改或删减原文的
        步骤、参数、数值、条件、转人工提示等任何实质内容。
        """
        if not answer or not answer.strip():
            return answer

        system_prompt = (
            "你是客服回复润色助手。把知识库的标准答案润色成更友好、易读的客服回复。\n"
            "【严格约束 - 必须遵守】\n"
            "1. 严禁修改、删减、增加任何步骤、操作、参数、数值、条件\n"
            "2. 严禁改动原文的转人工提示、注意事项\n"
            "3. 原文里的菜单路径(如 菜单--设备信息)、按键操作、规格参数必须原样保留\n"
            "4. 不得凭空补充原文没有的信息\n"
            "【允许的润色】\n"
            "- 调整语气更友好(如开头加'您可以这样操作:')\n"
            "- 用项目符号/编号让步骤更清晰\n"
            "- 适当分段\n"
            "- 修正明显的标点/错别字\n"
            "只返回润色后的回复, 不要任何解释。"
        )
        user_content = f"用户问题: {query}\n\n知识库标准答案:\n{answer}\n\n润色后的回复:"

        try:
            response = await self.chat([
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ])
            # 安全兜底: 若润色结果明显比原文短很多, 可能丢了内容, 回退原文
            if response and len(response.strip()) < len(answer.strip()) * 0.5:
                logger.warning("润色结果过短, 疑似丢内容, 回退原文")
                return answer
            return response.strip() or answer
        except Exception as e:
            logger.warning(f"润色失败, 返回原文: {e}")
            return answer


class MockProvider(LLMProvider):
    """Mock 提供者 (开发/测试用, 不依赖外部LLM)"""

    async def chat(self, messages: List[Dict], **kwargs) -> str:
        last_msg = messages[-1]["content"] if messages else ""
        return f"[Mock] 这是对 '{last_msg[:50]}...' 的回复"

    async def classify(self, text: str, labels: List[str], context: str = "") -> Dict:
        # 简单关键词匹配
        text_lower = text.lower()
        if any(kw in text_lower for kw in ["转人工", "人工客服", "找人工", "真人"]):
            return {"label": "transfer_request", "confidence": 0.95}
        if any(kw in text_lower for kw in ["你好", "在吗", "hi", "hello"]):
            return {"label": "greeting", "confidence": 0.9}
        if any(kw in text_lower for kw in ["查询", "查一下", "帮我查", "是多少", "状态"]):
            return {"label": "live_query", "confidence": 0.7}
        # 默认为知识问答
        return {"label": "knowledge_query", "confidence": 0.5}

    async def summarize(self, text: str, max_length: int = 200) -> str:
        return text[:max_length] + "..." if len(text) > max_length else text

    async def rewrite(self, query: str, history: List[str]) -> str:
        return query

    async def retrieve(self, query: str, candidates: List[Dict], top_k: int = 5) -> List[int]:
        """Mock检索: 用字符重叠度排序 (开发兜底, 不调大模型)"""
        if not candidates:
            return []
        query_chars = set(query)
        scored = []
        for c in candidates:
            q = c.get("question", "")
            overlap = len(query_chars & set(q))
            scored.append((c["id"], overlap))
        scored.sort(key=lambda x: x[1], reverse=True)
        return [i for i, _ in scored[:top_k] if _ > 0]

    async def polish(self, query: str, answer: str) -> str:
        """Mock润色: 不调大模型, 原样返回 (开发兜底)"""
        return answer


# ============================================
# LLM 工厂
# ============================================

_llm_provider: Optional[LLMProvider] = None


def get_llm() -> LLMProvider:
    """获取LLM提供者 (单例)

    若配置的 provider 初始化失败 (如 doubao 缺 API_KEY, local 未启动 Ollama),
    自动降级为 MockProvider, 保证服务可用。
    """
    global _llm_provider
    if _llm_provider is None:
        provider_map = {
            "local": LocalLLMProvider,
            "doubao": DoubaoProvider,
            "mock": MockProvider,
        }
        provider_cls = provider_map.get(settings.LLM_PROVIDER, MockProvider)
        try:
            _llm_provider = provider_cls()
            logger.info(f"LLM Provider: {settings.LLM_PROVIDER} ({settings.LLM_MODEL})")
        except Exception as e:
            logger.warning(f"LLM Provider '{settings.LLM_PROVIDER}' 初始化失败, 降级为 mock: {e}")
            _llm_provider = MockProvider()
    return _llm_provider


def set_llm(provider: LLMProvider):
    """手动设置LLM提供者 (测试用)"""
    global _llm_provider
    _llm_provider = provider
