import json

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from semantica.explorer.dependencies import require_auth
from semantica.explorer.routes.conflicts import router


def test_conflict_views_require_authentication_and_do_not_expose_connection(tmp_path, monkeypatch):
    monkeypatch.delenv("SEMANTICA_ALLOW_ANONYMOUS", raising=False)
    monkeypatch.setenv("SEMANTICA_API_KEY", "local-test-key")
    monkeypatch.setenv("SEMANTICA_WEKNORA_DIR", str(tmp_path))
    (tmp_path/"snapshot.json").write_text(json.dumps({
        "knowledge_base": {"id": "kb", "name": "Test", "type": "document"},
        "captured_at": "2026-10-19", "coverage": {"documents": 1, "chunks": 1, "issues": []},
        "chunks": [{"chunk_id": "source", "content": "source evidence"}],
    }))
    (tmp_path/"connection.json").write_text('{"token": "do-not-expose"}')
    app = FastAPI()
    app.include_router(router, dependencies=[Depends(require_auth)])
    with TestClient(app) as client:
        assert client.get("/api/conflicts/weknora").status_code == 401
        assert client.get("/api/conflicts/weknora/source/source").status_code == 401
        response = client.get("/api/conflicts/weknora", headers={"X-API-Key": "local-test-key"})
        assert response.status_code == 200
        assert response.json()["audit"]["status"] == "not_started"
        assert "do-not-expose" not in response.text
        assert client.get("/api/conflicts/weknora/source/missing", headers={"X-API-Key": "local-test-key"}).status_code == 404
