from unittest.mock import Mock

import pytest

from semantica.ingest.weknora_ingestor import WeKnoraIngestor


def client():
    return WeKnoraIngestor("https://knowledge.example/api/v1", token="secret", session=Mock(headers={}))


def test_pagination_keeps_reading_when_server_clamps_page_size():
    source = client()
    source._get = Mock(side_effect=[
        {"data": [{"id": "a"}], "total": 2},
        {"data": [{"id": "b"}], "total": 2},
    ])
    assert [r["id"] for r in source._list("/chunks/doc")] == ["a", "b"]
    assert source._get.call_args_list[1].kwargs["page"] == 2


@pytest.mark.parametrize("pages", [
    [{"data": [{"id": "a"}], "total": 2}, {"data": [], "total": 2}],
    [{"data": [{"id": "a"}], "total": 2}, {"data": [{"id": "a"}], "total": 2}],
    [{"data": [{"id": "a"}], "total": 2}, {"data": [{"id": "b"}], "total": 3}],
])
def test_pagination_rejects_incomplete_duplicate_and_mutating_pages(pages):
    source = client()
    source._get = Mock(side_effect=pages)
    with pytest.raises(RuntimeError):
        source._list("/chunks/doc")


def test_snapshot_retains_source_locations_and_marks_unavailable_content():
    source = client()
    source._get = Mock(return_value={"data": {"id": "kb", "name": "Test"}})
    documents = [{"id": "doc", "parse_status": "processing", "updated_at": "v1"}]
    source._list = Mock(side_effect=[documents, [{"id": "c", "knowledge_id": "doc",
                                                "content": "", "metadata": {"page": 2}}], documents])
    result = source.snapshot("kb")
    assert result["chunks"][0]["raw"]["metadata"] == {"page": 2}
    assert not result["coverage"]["all_content_available"]
    assert len(result["coverage"]["issues"]) == 2
    assert "secret" not in str(result)


def test_redirects_are_not_followed_and_credentials_are_not_in_errors():
    source = client()
    source.session.get.return_value = Mock(status_code=302)
    with pytest.raises(RuntimeError, match="HTTP 302"):
        source._get("/knowledge-bases")
    assert source.session.get.call_args.kwargs["allow_redirects"] is False
