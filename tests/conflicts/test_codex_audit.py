import json

from semantica.conflicts import codex_audit as audit


def snapshot(tmp_path):
    source = {"chunks": [{"chunk_id": "a", "document_id": "doc1", "document_title": "A",
                          "content": "付款期限为30天", "sha256": "hash-a", "raw": {}},
                         {"chunk_id": "b", "document_id": "doc2", "document_title": "B",
                          "content": "付款期限为60天", "sha256": "hash-b", "raw": {}}],
              "coverage": {"issues": [], "chunks": 2, "documents": 2}}
    path = tmp_path / "snapshot.json"
    path.write_text(json.dumps(source))
    return path


def test_audit_keeps_evidence_and_distinguishes_conflicts_from_review(tmp_path, monkeypatch):
    def complete(self, instruction, payload, output_type, **kwargs):
        if output_type is audit.Extraction:
            return audit.Extraction(processed_chunk_ids=[r["chunk_id"] for r in payload], claims=[
                audit.Claim(chunk_id=r["chunk_id"], quote=r["content"], entity="合同C001",
                            property="付款期限", value=r["content"], conditions="全部付款", valid_time="2026")
                for r in payload])
        return audit.Judgments(judgments=[audit.Judgment(pair_id=r["pair_id"], verdict="conflict",
                                                       kind="数值", reason="同一条件期限互斥") for r in payload])
    monkeypatch.setattr(audit.CodexGateway, "complete", complete)
    monkeypatch.setattr(audit.CodexGateway, "probe", lambda self: None)
    monkeypatch.setattr(audit.shutil, "which", lambda _: "codex")
    report = audit.run_audit(snapshot(tmp_path), tmp_path/"run")
    assert report["status"] == "completed"
    assert report["chunks_processed"] == 2
    assert report["pairs_checked"] == 1
    assert len(report["conflicts"]) == 1
    assert report["conflicts"][0]["left"]["source"]["sha256"]


def test_hallucinated_quote_is_a_failure_not_a_clean_audit(tmp_path, monkeypatch):
    def complete(self, instruction, payload, output_type, **kwargs):
        return audit.Extraction(processed_chunk_ids=[r["chunk_id"] for r in payload], claims=[
            audit.Claim(chunk_id="a", quote="不存在的原文", entity="C001", property="期限",
                        value="90天", conditions="", valid_time="")])
    monkeypatch.setattr(audit.CodexGateway, "complete", complete)
    monkeypatch.setattr(audit.CodexGateway, "probe", lambda self: None)
    monkeypatch.setattr(audit.shutil, "which", lambda _: "codex")
    report = audit.run_audit(snapshot(tmp_path), tmp_path/"run")
    assert report["status"] == "partial"
    assert report["chunks_processed"] == 0
    assert len(report["errors"]) == 1


def test_batching_preserves_every_chunk_without_truncation():
    chunks = [{"chunk_id": str(i), "document_id": "d", "document_title": "Title",
               "content": "正文"*200} for i in range(5)]
    batches = list(audit.text_batches(chunks, max_chars=600))
    assert [r["chunk_id"] for batch in batches for r in batch] == [str(i) for i in range(5)]
    assert all(r["content"] == "正文"*200 for batch in batches for r in batch)


def test_unavailable_model_fails_before_processing_corpus(tmp_path, monkeypatch):
    def unavailable(self):
        raise TimeoutError("offline")
    monkeypatch.setattr(audit.CodexGateway, "probe", unavailable)
    monkeypatch.setattr(audit.shutil, "which", lambda _: "codex")
    report = audit.run_audit(snapshot(tmp_path), tmp_path/"run")
    assert report["status"] == "failed"
    assert report["chunks_processed"] == 0
    assert report["errors"][0]["stage"] == "gateway"
