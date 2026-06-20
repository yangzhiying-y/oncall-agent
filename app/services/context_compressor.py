"""上下文自动压缩服务

当对话消息的 token 数超过上下文窗口的指定阈值（默认 70%）时，
自动用 LLM 将早期对话压缩为一段摘要，用摘要替换原文，
从而在有限的上下文窗口中保留更多有效信息。

工作原理（用学生能懂的话说）：
1. 统计当前所有消息用了多少 tokens
2. 如果超过窗口的 70%，就把"旧消息"压成一段摘要
3. 摘要 + 最近几轮对话 → 拼成新的消息列表
4. 返回给 Agent 继续对话

与简单截断（trim_messages）的区别：
- 截断：直接删除旧消息，信息永久丢失
- 压缩：把旧消息总结为摘要，关键信息保留
"""

from typing import List, Optional, Tuple

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langchain_qwq import ChatQwen
from loguru import logger

from app.config import config


class ContextCompressor:
    """上下文压缩器

    在对话 token 数达到阈值时，用 LLM 将早期对话压缩为摘要。

    使用方式：
        compressor = ContextCompressor()
        compressed_messages = compressor.compress_if_needed(messages)

    配置（在 config.py / .env 中）：
        - context_compression_enabled: 开关
        - context_window_tokens: 模型上下文窗口大小
        - compression_threshold: 触发压缩的阈值比例
        - compression_keep_recent: 保留最近的 N 条消息原文
        - compression_summary_max_tokens: 摘要最大 token 数
    """

    # 压缩提示词模板
    COMPRESSION_SYSTEM_PROMPT = """你是一个对话摘要专家。你需要把一段对话历史压缩成简洁的摘要。

要求：
1. 保留所有关键事实、数字、日期、决策和结论
2. 保留用户的偏好和需求
3. 保留重要的上下文信息（如正在讨论的话题、待解决的问题）
4. 省略闲聊、重复内容和无关细节
5. 用第三人称叙述（例如"用户询问了..."、"助手回答了..."）
6. 摘要长度控制在 {max_tokens} tokens 以内
7. 只输出摘要内容，不要加"以下是摘要："之类的前缀"""

    def __init__(
        self,
        model: Optional[str] = None,
        enabled: Optional[bool] = None,
        window_tokens: Optional[int] = None,
        threshold: Optional[float] = None,
        keep_recent: Optional[int] = None,
        summary_max_tokens: Optional[int] = None,
    ):
        """初始化上下文压缩器

        Args:
            model: 用于压缩的 LLM 模型名，默认从 config 读取
            enabled: 是否启用，默认从 config 读取
            window_tokens: 上下文窗口大小，默认从 config 读取
            threshold: 触发阈值，默认从 config 读取
            keep_recent: 保留最近 N 条消息，默认从 config 读取
            summary_max_tokens: 摘要最大 token 数，默认从 config 读取
        """
        self.enabled = enabled if enabled is not None else config.context_compression_enabled
        self.window_tokens = window_tokens or config.context_window_tokens
        self.threshold = threshold if threshold is not None else config.compression_threshold
        self.keep_recent = keep_recent or config.compression_keep_recent
        self.summary_max_tokens = summary_max_tokens or config.compression_summary_max_tokens

        # 触发压缩的 token 数
        self.trigger_tokens = int(self.window_tokens * self.threshold)
        # 压缩后的目标 token 数（给新对话留 30% 空间）
        self.target_tokens = int(self.window_tokens * 0.5)

        # 延迟初始化压缩模型（避免模块导入时的循环依赖）
        self._compress_model: Optional[ChatQwen] = None
        self._model_name = model or config.rag_model

        # 延迟初始化 token 计数器
        self._tokenizer = None
        self._tokenizer_available = None  # None 表示未检测

        logger.info(
            f"ContextCompressor 初始化完成 - "
            f"启用: {self.enabled}, "
            f"窗口: {self.window_tokens} tokens, "
            f"触发阈值: {self.threshold*100:.0f}% ({self.trigger_tokens} tokens), "
            f"保留最近: {self.keep_recent} 条消息, "
            f"摘要限制: {self.summary_max_tokens} tokens"
        )

    # ── Token 计数 ────────────────────────────────────────────

    def _get_token_counter(self):
        """延迟初始化 token 计数器

        优先级：
        1. tiktoken (o200k_base - 最接近 qwen 系列)
        2. tiktoken (cl100k_base - 通用备选)
        3. 字符估算（4 字符 ≈ 1 token）
        """
        if self._tokenizer_available is not None:
            return self._tokenizer

        # 尝试 tiktoken
        try:
            import tiktoken

            # qwen-max 使用类似 o200k_base 的编码
            for enc_name in ["o200k_base", "cl100k_base"]:
                try:
                    self._tokenizer = tiktoken.get_encoding(enc_name)
                    self._tokenizer_available = True
                    logger.info(f"Token 计数器: tiktoken/{enc_name}")
                    return self._tokenizer
                except Exception:
                    continue

        except ImportError:
            logger.debug("tiktoken 未安装")

        # 回退：字符估算
        logger.warning("未找到 tiktoken，使用字符估算（4字符≈1token），建议安装 tiktoken")
        self._tokenizer_available = False
        self._tokenizer = "approximate"
        return self._tokenizer

    def count_tokens(self, messages: List[BaseMessage]) -> int:
        """计算消息列表的 token 数

        Args:
            messages: 消息列表

        Returns:
            int: 总 token 数
        """
        tokenizer = self._get_token_counter()

        if tokenizer == "approximate":
            # 粗略估算：4 字符 ≈ 1 token（对中文约 1.5 字符 ≈ 1 token）
            total_chars = sum(len(str(msg.content)) for msg in messages)
            return total_chars // 3  # 对中文稍保守

        # tiktoken 精确计数
        total = 0
        for msg in messages:
            content = str(msg.content) if msg.content else ""
            total += len(tokenizer.encode(content))
            # 每条消息额外加 4 tokens（角色标记等开销）
            total += 4
        return total

    def get_usage_ratio(self, messages: List[BaseMessage]) -> float:
        """获取上下文窗口使用率

        Args:
            messages: 消息列表

        Returns:
            float: 0.0 ~ 1.0 的使用率
        """
        tokens = self.count_tokens(messages)
        return tokens / self.window_tokens

    # ── 压缩逻辑 ──────────────────────────────────────────────

    def needs_compression(self, messages: List[BaseMessage]) -> bool:
        """判断是否需要压缩

        Args:
            messages: 消息列表

        Returns:
            bool: True 表示需要压缩
        """
        if not self.enabled:
            return False

        if len(messages) <= self.keep_recent:
            return False

        tokens = self.count_tokens(messages)
        needs = tokens > self.trigger_tokens

        if needs:
            usage_pct = (tokens / self.window_tokens) * 100
            logger.info(
                f"检测到上下文使用率 {usage_pct:.1f}% "
                f"({tokens}/{self.window_tokens} tokens)，"
                f"超过阈值 {self.threshold*100:.0f}%，触发压缩"
            )

        return needs

    def _get_compress_model(self) -> ChatQwen:
        """延迟初始化压缩模型"""
        if self._compress_model is None:
            self._compress_model = ChatQwen(
                model=self._model_name,
                api_key=config.dashscope_api_key,
                temperature=0.3,  # 摘要需要准确，用低温度
                streaming=False,
            )
        return self._compress_model

    def _split_messages(
        self, messages: List[BaseMessage]
    ) -> Tuple[List[BaseMessage], List[BaseMessage]]:
        """将消息拆分为 [待压缩的旧消息] + [保留的新消息]

        策略：
        1. 保留最近 keep_recent 条消息原文
        2. 其余消息交给 LLM 压缩
        3. 第一条 SystemMessage 始终保留（系统提示词不应被压缩）

        Args:
            messages: 完整消息列表

        Returns:
            (old_messages, recent_messages): 旧消息和最近消息
        """
        if len(messages) <= self.keep_recent:
            return [], list(messages)

        # 找到第一条 SystemMessage
        system_msg = None
        other_messages = []
        for msg in messages:
            if system_msg is None and isinstance(msg, SystemMessage):
                system_msg = msg
            else:
                other_messages.append(msg)

        if len(other_messages) <= self.keep_recent:
            # 消息不够多，不需要压缩
            recent = [system_msg] + other_messages if system_msg else other_messages
            return [], recent

        # 拆分：旧消息 + 最近 N 条
        old = other_messages[:-self.keep_recent]
        recent = other_messages[-self.keep_recent:]

        # SystemMessage 放入保留区（不能被压缩）
        if system_msg:
            recent = [system_msg] + recent

        return old, recent

    def _build_compression_prompt(
        self, messages: List[BaseMessage]
    ) -> str:
        """构建压缩提示词

        把待压缩的消息格式化为一段文本，让 LLM 阅读并总结。

        Args:
            messages: 待压缩的消息列表

        Returns:
            str: 压缩提示词
        """
        prompt = self.COMPRESSION_SYSTEM_PROMPT.format(
            max_tokens=self.summary_max_tokens
        )
        prompt += "\n\n--- 以下是需要总结的对话历史 ---\n\n"

        for i, msg in enumerate(messages, 1):
            role = "用户" if isinstance(msg, HumanMessage) else "助手"
            content = str(msg.content) if msg.content else ""
            # 截断过长的单条消息
            if len(content) > 2000:
                content = content[:2000] + "...(已截断)"
            prompt += f"[{role}]: {content}\n\n"

        prompt += "--- 对话历史结束 ---\n\n请输出摘要："
        return prompt

    def compress(self, messages: List[BaseMessage]) -> List[BaseMessage]:
        """对消息列表进行压缩

        步骤：
        1. 拆分为旧消息 + 最近消息
        2. 调用 LLM 把旧消息总结为摘要
        3. 用 [摘要 SystemMessage] + [最近消息] 组合返回

        Args:
            messages: 完整消息列表

        Returns:
            List[BaseMessage]: 压缩后的消息列表

        Raises:
            RuntimeError: 压缩失败时抛出
        """
        if not messages:
            return []

        old, recent = self._split_messages(messages)

        if not old:
            logger.debug("消息数不足，无需压缩")
            return messages

        logger.info(f"开始压缩: {len(old)} 条旧消息 → 摘要 + {len(recent)} 条保留消息")

        try:
            # 调用 LLM 生成摘要
            compress_model = self._get_compress_model()
            compress_prompt = self._build_compression_prompt(old)

            response = compress_model.invoke([HumanMessage(content=compress_prompt)])
            summary_text = str(response.content).strip()

            if not summary_text:
                raise RuntimeError("LLM 返回空摘要")

            summary_tokens = self.count_tokens([HumanMessage(content=summary_text)])
            logger.info(
                f"压缩完成: {len(old)} 条消息 ({self.count_tokens(old)} tokens) "
                f"→ 摘要 ({summary_tokens} tokens)"
            )

            # 构建压缩后的消息列表
            summary_msg = SystemMessage(
                content=f"[对话历史摘要] {summary_text}\n\n"
                f"（以上是之前对话的摘要，以下是最近的对话内容）"
            )

            compressed = [summary_msg] + list(recent)
            new_tokens = self.count_tokens(compressed)
            usage_pct = (new_tokens / self.window_tokens) * 100

            logger.info(
                f"压缩后上下文使用率: {usage_pct:.1f}% "
                f"({new_tokens}/{self.window_tokens} tokens)"
            )

            return compressed

        except Exception as e:
            logger.error(f"上下文压缩失败: {e}")
            raise RuntimeError(f"上下文压缩失败: {e}") from e

    def compress_if_needed(self, messages: List[BaseMessage]) -> List[BaseMessage]:
        """如果需要则压缩，否则原样返回

        这是对外的便捷方法，组合了 needs_compression() 和 compress()。

        Args:
            messages: 消息列表

        Returns:
            List[BaseMessage]: 压缩后（或原样）的消息列表
        """
        if not self.needs_compression(messages):
            return messages

        return self.compress(messages)


# 全局单例
context_compressor = ContextCompressor()
