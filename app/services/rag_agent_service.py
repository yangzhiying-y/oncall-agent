"""RAG Agent 服务 - 基于 LangGraph 的智能代理

使用 langchain_qwq 的 ChatQwen 原生集成，
支持真正的流式输出和更好的模型适配。
"""

from typing import Annotated, Any, AsyncGenerator, Dict, Sequence

from langchain.agents import create_agent
from langchain_core.messages import (
    BaseMessage,
    HumanMessage,
    RemoveMessage,
    SystemMessage,
)
from langgraph.graph.message import REMOVE_ALL_MESSAGES, add_messages
from loguru import logger
from typing_extensions import TypedDict
from langchain_qwq import ChatQwen

from app.config import config
from app.core.checkpoint_store import checkpoint_store
from app.services.context_compressor import context_compressor
from app.tools import DEFAULT_LOCAL_AGENT_TOOLS
from app.agent.mcp_client import (
    get_mcp_client_with_retry,
    load_mcp_tools_safe,
    format_exception_chain,
    suggest_mcp_transport,
)

# 阿里千问大模型和langchain集成参考： https://docs.langchain.com/oss/python/integrations/chat/qwen
# 注意：需要配置环境变量 DASHSCOPE_API_BASE=https://dashscope.aliyuncs.com/compatible-mode/v1 否则默认访问的是新加坡站点
# 同时也需要配置环境变量 DASHSCOPE_API_KEY=your_api_key


class AgentState(TypedDict):
    """Agent 状态"""
    messages: Annotated[Sequence[BaseMessage], add_messages]


def trim_messages_middleware(state: AgentState) -> dict[str, Any] | None:
    """
    修剪消息历史，只保留最近的几条消息以适应上下文窗口

    策略：
    - 保留第一条系统消息（System Message）
    - 保留最近的 6 条消息（3 轮对话）
    - 当消息少于等于 7 条时，不做修剪

    Args:
        state: Agent 状态

    Returns:
        包含修剪后消息的字典，如果无需修剪则返回 None
    """
    messages = state["messages"]

    # 如果消息数量较少，无需修剪
    if len(messages) <= 7:
        return None

    # 提取第一条系统消息
    first_msg = messages[0]

    # 保留最近的 6 条消息（确保包含完整的对话轮次）
    recent_messages = messages[-6:] if len(messages) % 2 == 0 else messages[-7:]

    # 构建新的消息列表
    new_messages = [first_msg] + list(recent_messages)

    logger.debug(f"修剪消息历史: {len(messages)} -> {len(new_messages)} 条")

    return {
        "messages": [
            RemoveMessage(id=REMOVE_ALL_MESSAGES),
            *new_messages
        ]
    }


class RagAgentService:
    """RAG Agent 服务 - 使用 LangGraph + ChatQwen 原生集成"""

    def __init__(self, streaming: bool = True):
        """初始化 RAG Agent 服务

        Args:
            streaming: 是否启用流式输出，默认为 True
        """
        self.model_name = config.rag_model
        self.streaming = streaming
        self.system_prompt = self._build_system_prompt()


        self.model = ChatQwen(
            model=self.model_name,
            api_key=config.dashscope_api_key,
            temperature=0.7,
            streaming=streaming,
        )

        # 定义基础工具（与 AIOps Planner/Executor 使用同一套默认本地工具）
        self.tools = list(DEFAULT_LOCAL_AGENT_TOOLS)

        # MCP 客户端（延迟初始化，使用全局管理）
        self.mcp_tools: list = []

        # SQLite 持久化检查点（延迟解析，因为在模块导入时 checkpoint_store 尚未连接）
        self._checkpointer = None

        # Agent 初始化（会在异步方法中完成）
        self.agent = None
        self._agent_initialized = False

        logger.info(f"RAG Agent 服务初始化完成 (ChatQwen), model={self.model_name}, streaming={streaming}")

    @property
    def checkpointer(self):
        """延迟解析 SQLite 检查点保存器

        模块导入时 checkpoint_store 尚未连接，
        因此延迟到首次访问时才获取 saver 引用。
        """
        if self._checkpointer is None:
            self._checkpointer = checkpoint_store.saver
        return self._checkpointer

    async def _initialize_agent(self):
        """异步初始化 Agent（包括 MCP 工具）"""
        if self._agent_initialized:
            return

        for name, server in config.mcp_servers.items():
            hint = suggest_mcp_transport(
                str(server.get("url", "")),
                str(server.get("transport", "")),
            )
            if hint:
                logger.warning(f"MCP 配置 [{name}]: {hint}")

        mcp_client = await get_mcp_client_with_retry()
        mcp_tools, mcp_err = await load_mcp_tools_safe(mcp_client)
        if mcp_err:
            logger.warning(
                f"MCP 工具加载失败，将仅使用本地工具继续运行:\n{mcp_err}"
            )
            self.mcp_tools = []
        else:
            self.mcp_tools = mcp_tools
            logger.info(f"成功加载 {len(mcp_tools)} 个 MCP 工具")

        all_tools = self.tools + self.mcp_tools

        self.agent = create_agent(
            self.model,
            tools=all_tools,
            checkpointer=self.checkpointer,
        )

        self._agent_initialized = True


        if all_tools:
            tool_names = [tool.name if hasattr(tool, "name") else str(tool) for tool in all_tools]
            logger.info(f"可用工具列表: {', '.join(tool_names)}")

    def _build_system_prompt(self) -> str:
        """
        构建系统提示词

        注意：LangChain 框架会自动将工具信息传递给 LLM，
        因此系统提示词中无需列举具体的工具列表。

        Returns:
            str: 系统提示词
        """
        from textwrap import dedent

        return dedent("""
            你是一个专业的AI助手，能够使用多种工具来帮助用户解决问题。

            工作原则:
            1. 理解用户需求，选择合适的工具来完成任务
            2. 当需要获取实时信息或专业知识时，主动使用相关工具
            3. 基于工具返回的结果提供准确、专业的回答
            4. 如果工具无法提供足够信息，请诚实地告知用户

            回答要求:
            - 保持友好、专业的语气
            - 回答简洁明了，重点突出
            - 基于事实，不编造信息
            - 如有不确定的地方，明确说明

            请根据用户的问题，灵活使用可用工具，提供高质量的帮助。
        """).strip()

    @staticmethod
    def _format_source_appendix(messages: Sequence[BaseMessage]) -> str:
        """Build a compact source list from retrieve_knowledge tool artifacts."""
        references: list[str] = []
        seen: set[tuple[str, str]] = set()

        for message in messages:
            artifact = getattr(message, "artifact", None)
            if not isinstance(artifact, list):
                continue

            for document in artifact:
                metadata = getattr(document, "metadata", {}) or {}
                source = str(metadata.get("_file_name") or metadata.get("source") or "未知来源")
                headings = [str(metadata[key]) for key in ("h1", "h2", "h3") if metadata.get(key)]
                location = " > ".join(headings)
                key = (source, location)
                if key not in seen:
                    seen.add(key)
                    references.append(f"- `{source}`" + (f" · {location}" if location else ""))

        if not references:
            return ""
        return "**参考资料**\n" + "\n".join(references[:5])

    @staticmethod
    def compress_messages_middleware(state: AgentState) -> dict[str, Any] | None:
        """上下文压缩中间件

        由 LangGraph Agent 在每次调用模型前自动执行。
        当消息 token 数超过窗口的 70% 时，用 LLM 将早期对话压缩为摘要。

        与 trim_messages_middleware 的区别：
        - trim: 直接删除旧消息（信息丢失）
        - compress: 总结旧消息为摘要（信息保留）

        执行顺序：trim 先执行（去掉过长的尾巴），compress 后执行（压缩头部）。
        """
        try:
            messages = list(state.get("messages", []))
            if len(messages) <= context_compressor.keep_recent:
                return None

            if not context_compressor.needs_compression(messages):
                return None

            logger.info(
                f"上下文使用率 {context_compressor.get_usage_ratio(messages)*100:.1f}%，"
                f"触发自动压缩..."
            )

            compressed = context_compressor.compress(messages)

            # 用 RemoveMessage + 压缩结果替换所有消息
            return {
                "messages": [
                    RemoveMessage(id=REMOVE_ALL_MESSAGES),
                    *compressed,
                ]
            }

        except Exception as e:
            logger.error(f"上下文压缩中间件失败: {e}", exc_info=True)
            # 压缩失败不影响对话，返回 None 让对话继续
            return None

    async def _build_agent_input(
        self, question: str, session_id: str
    ) -> dict:
        """构建 Agent 输入，在构建前检查并压缩上下文

        工作流程：
        1. 从 checkpointer 读取当前会话的已有消息
        2. 如果 token 数超过窗口 70%，用 LLM 压缩早期消息
        3. 如果压缩了，用 RemoveMessage 清空旧消息再写入压缩结果
        4. 最后附上新的系统提示词和用户问题

        Args:
            question: 用户问题
            session_id: 会话 ID

        Returns:
            dict: Agent 输入 {"messages": [...]}
        """
        messages = [
            SystemMessage(content=self.system_prompt),
            HumanMessage(content=question),
        ]

        # 尝试压缩上下文
        try:
            config_dict = {"configurable": {"thread_id": session_id}}
            checkpoint = self.checkpointer.get(config_dict)

            if checkpoint is not None:
                # 提取已有消息
                if hasattr(checkpoint, "checkpoint"):
                    checkpoint_data = checkpoint.checkpoint
                else:
                    checkpoint_data = (
                        checkpoint[0]
                        if isinstance(checkpoint, tuple)
                        else checkpoint
                    )

                channel_values = (
                    checkpoint_data.get("channel_values", {})
                    if isinstance(checkpoint_data, dict)
                    else getattr(checkpoint_data, "channel_values", {})
                )
                existing = list(channel_values.get("messages", []))

                if existing and context_compressor.needs_compression(existing):
                    logger.info(
                        f"[会话 {session_id}] 上下文使用率 "
                        f"{context_compressor.get_usage_ratio(existing)*100:.1f}%，"
                        f"触发自动压缩"
                    )
                    compressed = context_compressor.compress(existing)
                    # 清空旧消息，替换为压缩结果 + 新的系统提示和用户问题
                    messages = [
                        RemoveMessage(id=REMOVE_ALL_MESSAGES),
                        *compressed,
                        SystemMessage(content=self.system_prompt),
                        HumanMessage(content=question),
                    ]
                    logger.info(
                        f"[会话 {session_id}] 压缩完成: "
                        f"{len(existing)} → {len(compressed)} 条消息"
                    )

        except Exception as e:
            logger.error(
                f"[会话 {session_id}] 上下文压缩检查失败: {e}",
                exc_info=True,
            )

        return {"messages": messages}

    async def query(
        self,
        question: str,
        session_id: str,
    ) -> str:
        """
        非流式处理用户问题（一次性返回完整答案）

        Args:
            question: 用户问题
            session_id: 会话ID（作为 thread_id）

        Returns:
            str: 完整答案
        """
        try:
            await self._initialize_agent()

            # 压缩上下文（如果需要）
            agent_input = await self._build_agent_input(question, session_id)

            logger.info(f"[会话 {session_id}] RAG Agent 收到查询（非流式）: {question}")

            # 配置 thread_id（用于会话持久化）
            config_dict = {
                "configurable": {
                    "thread_id": session_id
                }
            }

            result = await self.agent.ainvoke(
                input=agent_input,
                config=config_dict,
            )

            # 提取最终答案
            messages_result = result.get("messages", [])
            if messages_result:
                last_message = messages_result[-1]
                answer = last_message.content if hasattr(last_message, 'content') else str(last_message)
                if not isinstance(answer, str):
                    answer = str(answer)

                source_appendix = self._format_source_appendix(messages_result)
                if source_appendix:
                    answer = f"{answer.rstrip()}\n\n---\n{source_appendix}"

                # 记录工具调用
                if hasattr(last_message, "tool_calls") and last_message.tool_calls:
                    tool_names = [tc.get("name", "unknown") for tc in last_message.tool_calls]
                    logger.info(f"[会话 {session_id}] Agent 调用了工具: {tool_names}")

                logger.info(f"[会话 {session_id}] RAG Agent 查询完成（非流式）")
                return answer

            logger.warning(f"[会话 {session_id}] Agent 返回结果为空")
            return ""

        except Exception as e:
            logger.error(
                f"[会话 {session_id}] RAG Agent 查询失败（非流式）: "
                f"{format_exception_chain(e)}"
            )
            raise

    async def query_stream(
        self,
        question: str,
        session_id: str,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        流式处理用户问题（逐步返回答案片段）

        Args:
            question: 用户问题
            session_id: 会话ID（作为 thread_id）

        Yields:
            Dict[str, Any]: 包含流式数据的字典
                - type: "content" | "tool_call" | "complete" | "error"
                - data: 具体内容
        """
        try:
            await self._initialize_agent()

            # 压缩上下文（如果需要）
            agent_input = await self._build_agent_input(question, session_id)

            logger.info(f"[会话 {session_id}] RAG Agent 收到查询（流式）: {question}")

            # 配置 thread_id（用于会话持久化）
            config_dict = {
                "configurable": {
                    "thread_id": session_id
                }
            }

            async for token, metadata in self.agent.astream(
                input=agent_input,
                config=config_dict,
                stream_mode="messages",
            ):
                node_name = metadata.get('langgraph_node', 'unknown') if isinstance(metadata, dict) else 'unknown'
                message_type = type(token).__name__

                # 处理 ToolMessage — 工具调用完成
                if message_type == "ToolMessage":
                    tool_name = getattr(token, 'name', 'unknown')
                    logger.info(f"[会话 {session_id}] 工具调用完成: {tool_name}")
                    yield {
                        "type": "tool_call",
                        "data": {
                            "tool": tool_name,
                            "status": "end",
                            "node": node_name,
                        },
                    }
                    # 检查是否是知识检索工具，提取检索结果摘要
                    if tool_name == "retrieve_knowledge":
                        artifact = getattr(token, 'artifact', None)
                        if artifact and isinstance(artifact, list):
                            yield {
                                "type": "search_results",
                                "data": {
                                    "tool": tool_name,
                                    "count": len(artifact),
                                    "sources": [
                                        getattr(d, 'metadata', {}).get('_file_name', '未知')
                                        for d in artifact[:3]
                                    ],
                                },
                            }

                # 处理 AIMessage — 可能包含 tool_calls 和 content
                elif message_type in ("AIMessage", "AIMessageChunk"):
                    # 检测 tool_calls（工具调用开始）
                    tool_calls = getattr(token, 'tool_calls', None)
                    if tool_calls:
                        for tc in tool_calls:
                            tc_name = tc.get('name', 'unknown') if isinstance(tc, dict) else getattr(tc, 'name', 'unknown')
                            tc_args = tc.get('args', {}) if isinstance(tc, dict) else getattr(tc, 'args', {})
                            # 简化参数显示（太长会撑爆前端）
                            args_preview = {}
                            for k, v in (tc_args or {}).items():
                                if isinstance(v, str) and len(v) > 80:
                                    args_preview[k] = v[:80] + "..."
                                else:
                                    args_preview[k] = v
                            logger.info(f"[会话 {session_id}] 工具调用开始: {tc_name}")
                            yield {
                                "type": "tool_call",
                                "data": {
                                    "tool": tc_name,
                                    "status": "start",
                                    "input": args_preview,
                                    "node": node_name,
                                },
                            }

                    # 流式文本内容
                    content_blocks = getattr(token, 'content_blocks', None)
                    if content_blocks and isinstance(content_blocks, list):
                        for block in content_blocks:
                            if isinstance(block, dict) and block.get('type') == 'text':
                                text_content = block.get('text', '')
                                if text_content:
                                    yield {
                                        "type": "content",
                                        "data": text_content,
                                        "node": node_name
                                    }
                    # 处理纯文本内容（无 content_blocks 时）
                    elif not tool_calls:
                        content = getattr(token, 'content', '')
                        if content and isinstance(content, str):
                            yield {
                                "type": "content",
                                "data": content,
                                "node": node_name,
                            }

            logger.info(f"[会话 {session_id}] RAG Agent 查询完成（流式）")
            yield {"type": "complete"}

        except Exception as e:
            detail = format_exception_chain(e)
            logger.error(
                f"[会话 {session_id}] RAG Agent 查询失败（流式）: {detail}"
            )
            yield {"type": "error", "data": detail}

    def get_session_history(self, session_id: str) -> list:
        """
        获取会话历史（从 MemorySaver checkpointer 中读取）

        Args:
            session_id: 会话ID（即 thread_id）

        Returns:
            list: 消息历史列表 [{"role": "user|assistant", "content": "...", "timestamp": "..."}]
        """
        try:
            # 使用 checkpointer 的 get 方法获取最新的检查点
            config = {"configurable": {"thread_id": session_id}}
            
            # 获取该 thread 的最新检查点
            checkpoint_tuple = self.checkpointer.get(config)
            
            if not checkpoint_tuple:
                logger.info(f"获取会话历史: {session_id}, 消息数量: 0")
                return []
            
            # checkpoint_tuple 可能是命名元组或普通元组，安全地提取 checkpoint
            # 通常第一个元素是 checkpoint 数据
            if hasattr(checkpoint_tuple, 'checkpoint'):
                checkpoint_data = checkpoint_tuple.checkpoint  # type: ignore
            else:
                # 如果是普通元组，第一个元素是 checkpoint
                checkpoint_data = checkpoint_tuple[0] if checkpoint_tuple else {}
            
            # 从检查点中提取消息
            messages = checkpoint_data.get("channel_values", {}).get("messages", [])
            
            # 转换为前端需要的格式
            history = []
            for msg in messages:
                # 跳过系统消息
                if isinstance(msg, SystemMessage):
                    continue
                    
                role = "user" if isinstance(msg, HumanMessage) else "assistant"
                content = msg.content if hasattr(msg, 'content') else str(msg)
                
                # 提取时间戳（如果有的话）
                timestamp = getattr(msg, 'timestamp', None)
                if timestamp:
                    history.append({
                        "role": role,
                        "content": content,
                        "timestamp": timestamp
                    })
                else:
                    from datetime import datetime
                    history.append({
                        "role": role,
                        "content": content,
                        "timestamp": datetime.now().isoformat()
                    })
            
            logger.info(f"获取会话历史: {session_id}, 消息数量: {len(history)}")
            return history
            
        except Exception as e:
            logger.error(f"获取会话历史失败: {session_id}, 错误: {e}")
            return []

    def clear_session(self, session_id: str) -> bool:
        """
        清空会话历史（从 MemorySaver checkpointer 中删除）

        Args:
            session_id: 会话ID（即 thread_id）

        Returns:
            bool: 是否成功
        """
        try:
            # 使用 checkpointer 的 delete_thread 方法删除该 thread 的所有检查点
            self.checkpointer.delete_thread(session_id)
            
            logger.info(f"已清除会话历史: {session_id}")
            return True
            
        except Exception as e:
            logger.error(f"清空会话历史失败: {session_id}, 错误: {e}")
            return False

    async def cleanup(self):
        """清理资源"""
        try:
            logger.info("清理 RAG Agent 服务资源...")
            # MCP 客户端由全局管理器统一管理，无需手动清理
            logger.info("RAG Agent 服务资源已清理")
        except Exception as e:
            logger.error(f"清理资源失败: {e}")


# 全局单例 - 启用流式输出
rag_agent_service = RagAgentService(streaming=True)
