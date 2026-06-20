"""文档分割服务模块 - 基于 LangChain 的智能文档分割"""

from pathlib import Path
from typing import List

from langchain_core.documents import Document
from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter
from loguru import logger

from app.config import config


class DocumentSplitterService:
    """文档分割服务 - 使用 LangChain 的分割器"""

    def __init__(self):
        """初始化文档分割服务"""
        self.chunk_size = config.chunk_max_size
        self.chunk_overlap = config.chunk_overlap

        # Markdown 标题分割器 (只按一级和二级标题分割，减少分片数)
        self.markdown_splitter = MarkdownHeaderTextSplitter(
            headers_to_split_on=[
                ("#", "h1"),
                ("##", "h2"),
                # 不再按三级标题分割，避免过度碎片化
            ],
            strip_headers=False,  # 保留标题在内容中
        )

        # 递归字符分割器 (用于二次分割，使用更大的chunk_size)
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.chunk_size * 2,  # 加倍chunk_size，减少分片数
            chunk_overlap=self.chunk_overlap,
            length_function=len,
            is_separator_regex=False,
        )

        logger.info(
            f"文档分割服务初始化完成, chunk_size={self.chunk_size}, "
            f"secondary_chunk_size={self.chunk_size * 2}, "
            f"overlap={self.chunk_overlap}"
        )

    def split_markdown(self, content: str, file_path: str = "") -> List[Document]:
        """
        分割 Markdown 文档 (两阶段分割 + 合并小片段)

        Args:
            content: Markdown 内容
            file_path: 文件路径 (用于元数据)

        Returns:
            List[Document]: 文档分片列表
        """
        if not content or not content.strip():
            logger.warning(f"Markdown 文档内容为空: {file_path}")
            return []

        try:
            # 第一阶段: 按标题分割
            md_docs = self.markdown_splitter.split_text(content)

            # 第二阶段: 按大小进一步分割
            docs_after_split = self.text_splitter.split_documents(md_docs)

            # 第三阶段: 合并太小的分片 (< 300字符)
            final_docs = self._merge_small_chunks(docs_after_split, min_size=300)

            # 添加文件路径元数据
            for doc in final_docs:
                doc.metadata["_source"] = file_path
                doc.metadata["_extension"] = ".md"
                doc.metadata["_file_name"] = Path(file_path).name

            logger.info(f"Markdown 分割完成: {file_path} -> {len(final_docs)} 个分片")
            return final_docs

        except Exception as e:
            logger.error(f"Markdown 分割失败: {file_path}, 错误: {e}")
            raise

    def split_text(self, content: str, file_path: str = "") -> List[Document]:
        """
        分割普通文本文档

        Args:
            content: 文本内容
            file_path: 文件路径 (用于元数据)

        Returns:
            List[Document]: 文档分片列表
        """
        if not content or not content.strip():
            logger.warning(f"文本文档内容为空: {file_path}")
            return []

        try:
            # 直接使用递归字符分割器
            docs = self.text_splitter.create_documents(
                texts=[content],
                metadatas=[
                    {
                        "_source": file_path,
                        "_extension": Path(file_path).suffix,
                        "_file_name": Path(file_path).name,
                    }
                ],
            )

            logger.info(f"文本分割完成: {file_path} -> {len(docs)} 个分片")
            return docs

        except Exception as e:
            logger.error(f"文本分割失败: {file_path}, 错误: {e}")
            raise

    def split_pdf(self, content: str, file_path: str = "") -> List[Document]:
        """
        分割 PDF 文档

        策略：
        1. 直接使用 RecursiveCharacterTextSplitter 按大小分割
        2. 分隔符优先在段落/句子边界切分
        3. 合并小于 200 字符的碎片（PDF 提取文本容易产生碎片）

        Args:
            content: PDF 提取的纯文本
            file_path: 文件路径

        Returns:
            List[Document]: 文档分片列表
        """
        if not content or not content.strip():
            logger.warning(f"PDF 文档内容为空: {file_path}")
            return []

        try:
            # 使用递归字符分割器，优先在自然边界切分
            docs = self.text_splitter.create_documents(
                texts=[content],
                metadatas=[
                    {
                        "_source": file_path,
                        "_extension": ".pdf",
                        "_file_name": Path(file_path).name,
                    }
                ],
            )

            # 合并过小的碎片（PDF 提取文本时常见）
            final_docs = self._merge_small_chunks(docs, min_size=200)

            logger.info(f"PDF 分割完成: {file_path} -> {len(final_docs)} 个分片")
            return final_docs

        except Exception as e:
            logger.error(f"PDF 分割失败: {file_path}, 错误: {e}")
            raise

    def split_docx(self, content: str, file_path: str = "") -> List[Document]:
        """
        分割 Word 文档（.docx）

        策略：
        1. 直接使用 RecursiveCharacterTextSplitter 按大小分割
        2. Word 文档通常有较好的段落结构，分隔符会优先在段落边界切分
        3. 合并小于 200 字符的碎片

        Args:
            content: docx 提取的纯文本
            file_path: 文件路径

        Returns:
            List[Document]: 文档分片列表
        """
        if not content or not content.strip():
            logger.warning(f"Word 文档内容为空: {file_path}")
            return []

        try:
            docs = self.text_splitter.create_documents(
                texts=[content],
                metadatas=[
                    {
                        "_source": file_path,
                        "_extension": ".docx",
                        "_file_name": Path(file_path).name,
                    }
                ],
            )

            # 合并过小的碎片
            final_docs = self._merge_small_chunks(docs, min_size=200)

            logger.info(f"Word 文档分割完成: {file_path} -> {len(final_docs)} 个分片")
            return final_docs

        except Exception as e:
            logger.error(f"Word 文档分割失败: {file_path}, 错误: {e}")
            raise

    def split_document(self, content: str, file_path: str = "") -> List[Document]:
        """
        智能分割文档 (根据文件扩展名选择最佳分割策略)

        分发规则：
        - .md   → split_markdown（标题层级 + 递归字符）
        - .pdf  → split_pdf（递归字符 + 碎片合并）
        - .docx → split_docx（递归字符 + 碎片合并）
        - .doc  → split_docx（同上）
        - 其他  → split_text（通用文本分割）

        Args:
            content: 文档内容
            file_path: 文件路径（用于判断扩展名）

        Returns:
            List[Document]: 文档分片列表
        """
        ext = Path(file_path).suffix.lower()

        if ext == ".md":
            return self.split_markdown(content, file_path)
        elif ext == ".pdf":
            return self.split_pdf(content, file_path)
        elif ext in (".docx", ".doc"):
            return self.split_docx(content, file_path)
        else:
            return self.split_text(content, file_path)

    def _merge_small_chunks(
        self, documents: List[Document], min_size: int = 300
    ) -> List[Document]:
        """
        合并太小的分片

        Args:
            documents: 文档列表
            min_size: 最小分片大小 (字符数)

        Returns:
            List[Document]: 合并后的文档列表
        """
        if not documents:
            return []

        merged_docs = []
        current_doc = None

        for doc in documents:
            doc_size = len(doc.page_content)

            if current_doc is None:
                # 第一个文档
                current_doc = doc
            elif doc_size < min_size and len(current_doc.page_content) < self.chunk_size * 2:
                # 当前文档太小且合并后不会太大，则合并
                current_doc.page_content += "\n\n" + doc.page_content
                # 保留主文档的元数据
            else:
                # 保存当前文档，开始新文档
                merged_docs.append(current_doc)
                current_doc = doc

        # 添加最后一个文档
        if current_doc is not None:
            merged_docs.append(current_doc)

        return merged_docs


# 全局单例
document_splitter_service = DocumentSplitterService()
