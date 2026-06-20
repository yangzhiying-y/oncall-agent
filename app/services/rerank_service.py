"""重排服务模块 - 基于阿里云百炼 DashScope Rerank API

使用 qwen3-rerank 模型对检索到的文档进行精排，提升 RAG 召回质量。

API 参考: https://help.aliyun.com/zh/model-studio/rerank
SDK 参考: https://pypi.org/project/dashscope/
"""

from typing import List

from dashscope import TextReRank
from langchain_core.documents import Document
from loguru import logger

from app.config import config


class RerankService:
    """重排服务 - 使用阿里云百炼 qwen3-rerank 模型对文档进行语义重排

    两阶段检索模式:
    1. 粗筛（向量检索）: 从 Milvus 检索 Top-K 候选文档（rerank_retrieval_k=10）
    2. 精排（重排模型）: 用 qwen3-rerank 重新排序，返回 Top-N（rerank_top_n=3）

    不降级：重排失败直接抛异常，不兜底使用原始检索结果。
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
    ):
        """初始化重排服务

        Args:
            api_key: DashScope API Key，默认从 config 读取
            model: 重排模型名称，默认 qwen3-rerank
        """
        self.api_key = api_key or config.dashscope_api_key
        if not self.api_key:
            raise ValueError("DASHSCOPE_API_KEY 未配置，重排服务需要 API Key")

        self.model = model or config.rerank_model
        self.top_n = config.rerank_top_n

        logger.info(
            f"RerankService 初始化完成 - "
            f"模型: {self.model}, "
            f"粗筛数量: {config.rerank_retrieval_k}, "
            f"精排数量: {self.top_n}"
        )

    def rerank(
        self,
        query: str,
        documents: List[Document],
        top_n: int | None = None,
    ) -> List[Document]:
        """对文档列表进行重排，返回按相关性降序排列的文档

        使用阿里云百炼 DashScope TextReRank API:
        - 模型: qwen3-rerank
        - 输入: query + documents（文本列表）
        - 输出: 按 relevance_score 降序排列的结果

        Args:
            query: 用户查询文本
            documents: 待重排的文档列表（来自向量检索粗筛结果）
            top_n: 返回的最相关文档数，默认使用 config.rerank_top_n

        Returns:
            List[Document]: 按 relevance_score 降序排列的文档列表，
            每个文档的 metadata 中增加了 rerank_score 和 rerank_model 字段

        Raises:
            RuntimeError: 重排失败时直接抛出（不降级，不使用原始结果兜底）
        """
        if not documents:
            logger.warning("重排收到空文档列表，跳过")
            return []

        if not query or not query.strip():
            raise ValueError("查询文本不能为空")

        top_n = top_n or self.top_n

        # 如果文档数已经 ≤ top_n，无需重排，直接返回
        if len(documents) <= top_n:
            logger.info(
                f"文档数({len(documents)}) ≤ 目标数({top_n})，跳过多余的重排调用"
            )
            return documents

        try:
            logger.info(
                f"开始重排 - 查询: {query[:80]}..., "
                f"候选文档: {len(documents)}, 目标返回: {top_n}"
            )

            # 1. 提取文档文本（截断过长文档，qwen3-rerank 单文档最大约 4000 tokens）
            doc_texts: List[str] = []
            for i, doc in enumerate(documents):
                text = doc.page_content
                if len(text) > 4000:
                    text = text[:4000]
                    logger.debug(f"文档[{i}] 过长已截断: {len(doc.page_content)} → 4000")
                doc_texts.append(text)

            # 2. 调用 DashScope TextReRank API
            response = TextReRank.call(
                model=self.model,
                query=query,
                documents=doc_texts,
                top_n=top_n,
                api_key=self.api_key,
            )

            # 3. 检查响应
            if response.status_code != 200:
                error_msg = (
                    f"重排 API 返回错误 (HTTP {response.status_code}): "
                    f"code={response.code}, message={response.message}"
                )
                logger.error(error_msg)
                raise RuntimeError(error_msg)

            if response.output is None or "results" not in response.output:
                error_msg = (
                    f"重排 API 返回格式异常，期望 'results' 字段，"
                    f"实际 output: {response.output}"
                )
                logger.error(error_msg)
                raise RuntimeError(error_msg)

            rerank_results = response.output["results"]

            # 4. 按 relevance_score 重新排序文档（API 已按分数降序返回）
            reranked_docs: List[Document] = []
            seen_indices: set[int] = set()
            for item in rerank_results:
                idx: int = item.get("index", 0)
                score: float = item.get("relevance_score", 0.0)

                # 防止重复
                if idx in seen_indices:
                    logger.warning(f"重排结果包含重复索引 {idx}，跳过")
                    continue
                seen_indices.add(idx)

                if 0 <= idx < len(documents):
                    doc = documents[idx]
                    # 将重排分数写入文档元数据
                    doc.metadata["rerank_score"] = round(score, 4)
                    doc.metadata["rerank_model"] = self.model
                    reranked_docs.append(doc)
                else:
                    logger.warning(f"重排返回无效索引 {idx}，文档总数 {len(documents)}")

            logger.info(
                f"重排完成 - 返回 {len(reranked_docs)} 个文档, "
                f"分数范围: "
                f"{reranked_docs[0].metadata.get('rerank_score', '?') if reranked_docs else 'N/A'} ~ "
                f"{reranked_docs[-1].metadata.get('rerank_score', '?') if reranked_docs else 'N/A'}"
            )

            return reranked_docs

        except RuntimeError:
            # 已经是格式化的错误，直接抛出
            raise
        except Exception as e:
            # 不降级：直接抛异常，不使用原始检索结果兜底
            logger.error(f"重排失败（不降级）: {e}")
            raise RuntimeError(
                f"文档重排失败: {e}\n"
                f"模型: {self.model}, 候选文档数: {len(documents)}"
            ) from e


# 全局单例
rerank_service = RerankService()
