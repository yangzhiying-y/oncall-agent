"""工具和工具函数测试"""

import pytest
from datetime import datetime
from unittest.mock import patch, MagicMock

from app.utils.file_utils import get_file_extension, sanitize_filename
from app.tools.time_tool import get_current_time


class TestFileUtils:
    """文件工具函数测试（已有测试的补充）"""

    def test_get_file_extension_lowercase(self):
        assert get_file_extension("file.TXT") == "txt"
        assert get_file_extension("file.PDF") == "pdf"
        assert get_file_extension("file.MD") == "md"

    def test_get_file_extension_no_extension(self):
        assert get_file_extension("README") == ""
        assert get_file_extension(".gitignore") == "gitignore"

    def test_get_file_extension_multiple_dots(self):
        assert get_file_extension("archive.tar.gz") == "gz"

    def test_sanitize_filename_removes_path_chars(self):
        assert "/" not in sanitize_filename("path/to/file.txt")
        assert "\\" not in sanitize_filename("C:\\path\\file.txt")
        assert " " not in sanitize_filename("my document.pdf")

    def test_sanitize_filename_preserves_name(self):
        result = sanitize_filename("hello_world-123.txt")
        assert "hello_world-123" in result


class TestTimeTool:
    """时间工具测试"""

    def test_get_current_time_invoke_default(self):
        # LangChain StructuredTool 需要通过 .invoke() 调用
        result = get_current_time.invoke({})
        assert result is not None
        assert isinstance(result, str)
        # 返回格式: "YYYY-MM-DD HH:MM:SS" (Asia/Shanghai 时区)
        assert "20" in result  # 包含年份

    def test_get_current_time_invoke_utc(self):
        result = get_current_time.invoke({"timezone": "UTC"})
        assert isinstance(result, str)
        assert "20" in result

    def test_get_current_time_contains_date(self):
        result = get_current_time.invoke({})
        current_year = str(datetime.now().year)
        assert current_year in result


class TestKnowledgeTool:
    """知识检索工具测试"""

    def test_tool_has_name(self):
        from app.tools.knowledge_tool import retrieve_knowledge
        assert hasattr(retrieve_knowledge, 'name')
        assert retrieve_knowledge.name == "retrieve_knowledge"

    def test_tool_has_description(self):
        from app.tools.knowledge_tool import retrieve_knowledge
        assert hasattr(retrieve_knowledge, 'description')
        assert len(retrieve_knowledge.description) > 0


class TestDefaultTools:
    """默认工具集测试"""

    def test_default_tools_are_defined(self):
        from app.tools import DEFAULT_LOCAL_AGENT_TOOLS
        assert len(DEFAULT_LOCAL_AGENT_TOOLS) >= 2
        tool_names = [t.name for t in DEFAULT_LOCAL_AGENT_TOOLS]
        assert "retrieve_knowledge" in tool_names
        assert "get_current_time" in tool_names


class TestCheckpointStore:
    """检查点存储测试"""

    def test_checkpoint_store_connect_and_close(self, tmp_path):
        from app.core.checkpoint_store import CheckpointStore
        db_path = str(tmp_path / "test_checkpoints.db")
        store = CheckpointStore()
        saver = store.connect(db_path=db_path)
        assert store.is_connected
        assert saver is not None
        store.close()
        assert not store.is_connected

    def test_duplicate_connect_is_safe(self, tmp_path):
        from app.core.checkpoint_store import CheckpointStore
        db_path = str(tmp_path / "test_checkpoints.db")
        store = CheckpointStore()
        store.connect(db_path=db_path)
        store.connect(db_path=db_path)  # 不应报错
        store.close()

    def test_saver_before_connect_raises(self):
        from app.core.checkpoint_store import CheckpointStore
        store = CheckpointStore()
        with pytest.raises(RuntimeError, match="未连接"):
            _ = store.saver


class TestRateLimiter:
    """速率限制器测试"""

    def test_allows_requests_within_limit(self):
        from app.core.rate_limiter import SlidingWindowRateLimiter
        limiter = SlidingWindowRateLimiter(max_requests=5, window_seconds=60)
        for _ in range(5):
            allowed, info = limiter.is_allowed("test-key")
            assert allowed, f"Request should be allowed, info={info}"

    def test_blocks_after_limit(self):
        from app.core.rate_limiter import SlidingWindowRateLimiter
        limiter = SlidingWindowRateLimiter(max_requests=3, window_seconds=60)
        for _ in range(3):
            limiter.is_allowed("test-key-2")
        allowed, info = limiter.is_allowed("test-key-2")
        assert not allowed
        assert info["remaining"] == 0

    def test_different_keys_are_independent(self):
        from app.core.rate_limiter import SlidingWindowRateLimiter
        limiter = SlidingWindowRateLimiter(max_requests=2, window_seconds=60)
        # 消耗 key1
        for _ in range(2):
            limiter.is_allowed("key-1")
        # key2 不应受影响
        allowed, _ = limiter.is_allowed("key-2")
        assert allowed
