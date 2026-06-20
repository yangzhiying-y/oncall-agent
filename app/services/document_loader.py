"""文档加载器模块 - 多文件类型支持

根据文件扩展名自动匹配对应的加载器，将不同格式的文件统一提取为纯文本。

支持的文件类型：
- .md / .txt   — 直接读取（UTF-8）
- .pdf          — pypdf 库提取文本（按页加载，页间保留分隔符）
- .docx / .doc  — docx2txt 库提取文本（保留段落结构）

架构模式：
- BaseDocumentLoader（抽象基类）：定义 load() + supported_extensions() 接口
- 四个具体实现：MarkdownLoader / TextLoader / PDFLoader / DocxLoader
- DocumentLoaderFactory：自动根据扩展名匹配处理器

添加新格式只需：
1. 继承 BaseDocumentLoader，实现 load() 和 supported_extensions()
2. 在 _register_all() 中注册即可
"""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict, List

from loguru import logger


# ════════════════════════════════════════════════════════════════
# 抽象基类
# ════════════════════════════════════════════════════════════════

class BaseDocumentLoader(ABC):
    """文件类型处理器的抽象基类

    每个具体的文件类型（PDF/Word/Markdown/Text）都继承此类，
    实现自己的文本提取逻辑。
    """

    @abstractmethod
    def load(self, file_path: Path) -> str:
        """从文件中提取纯文本

        Args:
            file_path: 文件的绝对路径

        Returns:
            str: 提取出的纯文本内容
        """
        ...

    @abstractmethod
    def supported_extensions(self) -> List[str]:
        """返回该处理器支持的文件扩展名列表

        Returns:
            List[str]: 扩展名列表（不含点），如 ['pdf']
        """
        ...

    @property
    def name(self) -> str:
        """处理器名称（用于日志）"""
        return self.__class__.__name__


# ════════════════════════════════════════════════════════════════
# 具体实现：Markdown
# ════════════════════════════════════════════════════════════════

class MarkdownLoader(BaseDocumentLoader):
    """Markdown 文件加载器

    分片策略（由 DocumentSplitterService.split_markdown 完成）：
    1. 按 # / ## 标题层级分割（保留标题在内容中）
    2. 超过 chunk_size 的片段用 RecursiveCharacterTextSplitter 二次分割
    3. 合并小于 300 字符的碎片
    """

    def load(self, file_path: Path) -> str:
        """直接读取 Markdown 文件的原始文本"""
        return file_path.read_text(encoding="utf-8")

    def supported_extensions(self) -> List[str]:
        return ["md"]


# ════════════════════════════════════════════════════════════════
# 具体实现：Plain Text
# ════════════════════════════════════════════════════════════════

class TextLoader(BaseDocumentLoader):
    """纯文本文件加载器

    分片策略（由 DocumentSplitterService.split_text 完成）：
    1. 直接用 RecursiveCharacterTextSplitter 按大小分割
    2. 分隔符优先级：\\n\\n → \\n → . → 。 → 空格 → 无
    """

    def load(self, file_path: Path) -> str:
        """直接读取纯文本文件的原始内容"""
        return file_path.read_text(encoding="utf-8")

    def supported_extensions(self) -> List[str]:
        return ["txt"]


# ════════════════════════════════════════════════════════════════
# 具体实现：PDF
# ════════════════════════════════════════════════════════════════

class PDFLoader(BaseDocumentLoader):
    """PDF 文件加载器

    使用 pypdf 库提取文本。pypdf 是纯 Python 实现，无需系统依赖。

    文本提取流程：
    1. 逐页读取 PDF，提取每页的文字内容
    2. 跳过空页
    3. 页与页之间用双换行分隔（保留"翻页"这一结构信息）
    4. 返回拼接后的完整文本

    分片策略（由 DocumentSplitterService.split_pdf 完成）：
    1. 加载后的文本直接送入 RecursiveCharacterTextSplitter
    2. 分隔符优先在段落边界切分
    3. 合并小于 200 字符的碎片

    依赖：pypdf（已在 pyproject.toml 中声明）
    """

    def load(self, file_path: Path) -> str:
        """使用 pypdf 提取 PDF 文本

        Args:
            file_path: PDF 文件路径

        Returns:
            str: 提取的纯文本，页间用 \\n\\n 分隔
        """
        try:
            from pypdf import PdfReader
        except ImportError:
            raise ImportError(
                "pypdf 未安装，请运行: pip install pypdf\n"
                "或: uv pip install pypdf"
            )

        reader = PdfReader(str(file_path))
        total_pages = len(reader.pages)
        logger.info(f"开始解析 PDF: {file_path.name}, 共 {total_pages} 页")

        page_texts: List[str] = []
        empty_pages = 0

        for i, page in enumerate(reader.pages):
            text = page.extract_text()
            if text and text.strip():
                page_texts.append(text.strip())
            else:
                empty_pages += 1
                logger.debug(f"  第 {i+1} 页无文字内容")

        if empty_pages > 0:
            logger.info(f"  {empty_pages}/{total_pages} 页无文字（可能是图片页）")

        full_text = "\n\n".join(page_texts)
        logger.info(
            f"PDF 文本提取完成: {file_path.name}, "
            f"有效页: {len(page_texts)}/{total_pages}, "
            f"总字符: {len(full_text)}"
        )

        return full_text

    def supported_extensions(self) -> List[str]:
        return ["pdf"]


# ════════════════════════════════════════════════════════════════
# 具体实现：Word
# ════════════════════════════════════════════════════════════════

class DocxLoader(BaseDocumentLoader):
    """Word 文档加载器（.docx / .doc）

    使用 docx2txt 库提取文本。docx2txt 基于 python-docx，
    是纯 Python 实现，无需安装 Microsoft Word 或 LibreOffice。

    文本提取流程：
    1. docx2txt.process() 直接提取 Word 文档中的纯文本
    2. 自动处理段落、表格、页眉页脚
    3. 图片中的文字无法提取（这是库的限制）

    分片策略（由 DocumentSplitterService.split_docx 完成）：
    1. 加载后的文本直接送入 RecursiveCharacterTextSplitter
    2. Word 文档天然有段落结构，分隔符会优先在段落边界切分
    3. 合并小于 200 字符的碎片

    注意：
    - .doc（旧格式，Word 97-2003）需要通过 LibreOffice 转换，暂不支持
    - .docx（新格式，Word 2007+）完美支持

    依赖：docx2txt（已在 pyproject.toml 中声明）
    """

    def load(self, file_path: Path) -> str:
        """使用 docx2txt 提取 Word 文档文本

        Args:
            file_path: .docx 文件路径

        Returns:
            str: 提取的纯文本
        """
        try:
            import docx2txt
        except ImportError:
            raise ImportError(
                "docx2txt 未安装，请运行: pip install docx2txt\n"
                "或: uv pip install docx2txt"
            )

        logger.info(f"开始解析 Word 文档: {file_path.name}")

        # docx2txt.process() 直接返回纯文本
        text = docx2txt.process(str(file_path))

        if not text or not text.strip():
            logger.warning(f"Word 文档无文字内容: {file_path.name}")
            return ""

        logger.info(
            f"Word 文档解析完成: {file_path.name}, "
            f"总字符: {len(text)}"
        )

        return text

    def supported_extensions(self) -> List[str]:
        return ["docx", "doc"]


# ════════════════════════════════════════════════════════════════
# 工厂
# ════════════════════════════════════════════════════════════════

class DocumentLoaderFactory:
    """文档加载器工厂

    根据文件扩展名自动匹配对应的加载器。

    使用方式：
        factory = DocumentLoaderFactory()
        text = factory.load(Path("report.pdf"))
        # → 自动使用 PDFLoader 提取文本

    添加新格式只需在 _register_all() 中注册新的 Loader 即可。
    """

    def __init__(self):
        """初始化工厂，注册所有内置加载器"""
        self._loaders: Dict[str, BaseDocumentLoader] = {}
        self._register_all()

    def _register_all(self) -> None:
        """注册所有内置的文件类型处理器"""
        loaders: List[BaseDocumentLoader] = [
            MarkdownLoader(),
            TextLoader(),
            PDFLoader(),
            DocxLoader(),
        ]
        for loader in loaders:
            for ext in loader.supported_extensions():
                self._loaders[ext] = loader
                logger.debug(f"注册文档加载器: .{ext} → {loader.name}")

    def get_loader(self, extension: str) -> BaseDocumentLoader:
        """根据扩展名获取对应的加载器

        Args:
            extension: 文件扩展名（不含点），如 'pdf'

        Returns:
            BaseDocumentLoader: 对应的加载器实例

        Raises:
            ValueError: 不支持的文件类型
        """
        ext = extension.lower().lstrip(".")
        loader = self._loaders.get(ext)
        if loader is None:
            supported = sorted(self.supported_extensions())
            raise ValueError(
                f"不支持的文件类型: .{ext}，"
                f"当前支持: {', '.join(supported)}"
            )
        return loader

    def load(self, file_path: Path) -> str:
        """一行调用：根据文件扩展名自动加载并提取文本

        Args:
            file_path: 文件路径

        Returns:
            str: 提取的纯文本
        """
        extension = file_path.suffix.lstrip(".")
        loader = self.get_loader(extension)
        logger.info(f"使用 {loader.name} 加载: {file_path.name}")
        return loader.load(file_path)

    def supported_extensions(self) -> List[str]:
        """返回所有支持的文件扩展名"""
        return sorted(self._loaders.keys())


# 全局单例
document_loader_factory = DocumentLoaderFactory()
