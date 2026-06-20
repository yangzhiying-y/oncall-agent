"""API 集成测试

使用 FastAPI 的 TestClient 和 httpx 进行 API 测试。
"""

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.fixture(scope="module")
def app():
    """创建测试用 FastAPI app（mock 所有外部依赖和模块级单例）"""
    from unittest.mock import MagicMock, patch
    import sys

    mock_memory_saver = MagicMock()
    mock_vsm = MagicMock()
    mock_rerank = MagicMock()
    mock_compressor = MagicMock()
    mock_mcp_client = MagicMock()

    sys.modules['app.services.vector_store_manager'] = MagicMock(vector_store_manager=mock_vsm)
    sys.modules['app.services.vector_embedding_service'] = MagicMock()
    sys.modules['app.services.rerank_service'] = MagicMock(rerank_service=mock_rerank)
    sys.modules['app.services.context_compressor'] = MagicMock(context_compressor=mock_compressor)

    with patch("app.core.milvus_client.milvus_manager.connect"), \
         patch("app.core.milvus_client.milvus_manager.close"), \
         patch("app.core.milvus_client.milvus_manager.health_check", return_value=True), \
         patch("app.core.checkpoint_store.checkpoint_store._saver", mock_memory_saver), \
         patch("app.core.checkpoint_store.checkpoint_store._ctx", MagicMock()), \
         patch("app.core.task_queue.task_queue.start"), \
         patch("app.core.task_queue.task_queue.stop"), \
         patch("app.agent.mcp_client.get_mcp_client_with_retry", return_value=mock_mcp_client), \
         patch("app.agent.mcp_client.load_mcp_tools_safe", return_value=([], None)):
        from app.main import app
        yield app

    for key in list(sys.modules.keys()):
        if key.startswith('app.services.') and isinstance(sys.modules[key], MagicMock):
            del sys.modules[key]


@pytest.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


class TestHealthEndpoint:
    """健康检查接口测试"""

    @pytest.mark.asyncio
    async def test_health_returns_200(self, client):
        resp = await client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 200
        assert data["data"]["status"] == "healthy"


class TestChatEndpoint:
    """对话接口测试"""

    @pytest.mark.asyncio
    async def test_chat_requires_body(self, client):
        resp = await client.post("/api/chat", json={})
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_chat_with_valid_request(self, client):
        resp = await client.post("/api/chat", json={
            "Id": "test-session-1",
            "Question": "你好",
        })
        assert resp.status_code != 422

    @pytest.mark.asyncio
    async def test_clear_session(self, client):
        resp = await client.post("/api/chat/clear", json={
            "session_id": "test-session-1",
        })
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_get_session_history(self, client):
        resp = await client.get("/api/chat/session/nonexistent")
        assert resp.status_code == 200


class TestStaticFiles:
    """静态文件测试"""

    @pytest.mark.asyncio
    async def test_root_returns_html(self, client):
        resp = await client.get("/")
        assert resp.status_code == 200
        assert "text/html" in resp.headers.get("content-type", "")
