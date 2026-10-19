"""Read-only, exhaustive WeKnora document/chunk snapshots.

Uses list endpoints rather than search, which would only retrieve top-k hits.
Credentials belong to the caller and are never included in snapshots.
"""

from datetime import datetime, timezone
from hashlib import sha256
from typing import Callable, Optional
from urllib.parse import quote, urlsplit

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


class WeKnoraIngestor:
    def __init__(self, base_url: str, *, token: str = "", api_key: str = "",
                 timeout: float = 30, session=None):
        parsed = urlsplit(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("WeKnora requires an HTTP(S) base URL")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("Do not place credentials or query strings in the URL")
        if not token and not api_key:
            raise ValueError("A WeKnora token or API key is required")
        self.base_url = base_url.rstrip("/")
        if self.base_url.endswith("/api/v1"):
            self.base_url = self.base_url[:-7]
        self.timeout = timeout
        self.session = session or requests.Session()
        # The URL is administrator-configured, including authorized intranet hosts.
        # Never take a target URL or credentials from an Explorer request body.
        self.session.trust_env = False
        self.session.headers.update({"X-API-Key": api_key} if api_key else
                                    {"Authorization": f"Bearer {token}"})
        self.session.mount("http://", HTTPAdapter(max_retries=Retry(
            total=3, backoff_factor=.5, status_forcelist=[429, 502, 503, 504],
            allowed_methods=["GET"])))
        self.session.mount("https://", HTTPAdapter(max_retries=Retry(
            total=3, backoff_factor=.5, status_forcelist=[429, 502, 503, 504],
            allowed_methods=["GET"])))

    def _get(self, path, **params):
        response = self.session.get(self.base_url + "/api/v1" + path,
                                    params=params, timeout=self.timeout,
                                    allow_redirects=False)
        if response.status_code != 200:
            raise RuntimeError(f"WeKnora read failed: HTTP {response.status_code}")
        data = response.json()
        if not isinstance(data, dict) or data.get("success") is not True:
            raise RuntimeError("WeKnora returned an unsuccessful response")
        return data

    def _list(self, path):
        records, seen, expected = [], set(), None
        for page in range(1, 100001):
            result = self._get(path, page=page, page_size=100)
            batch = result.get("data")
            if not isinstance(batch, list) or not isinstance(result.get("total"), int):
                raise RuntimeError("WeKnora pagination schema is unsupported")
            total = result["total"]
            if expected is not None and total != expected:
                raise RuntimeError("WeKnora changed during pagination; retry snapshot")
            expected = total
            for record in batch:
                identity = record.get("id")
                if not identity or identity in seen:
                    raise RuntimeError("Missing or repeated ID during pagination")
                seen.add(identity)
                records.append(record)
            if len(records) == total:
                return records
            if not batch or len(records) > total:
                raise RuntimeError("Incomplete WeKnora pagination")
        raise RuntimeError("WeKnora pagination limit exceeded")

    def snapshot(self, knowledge_base_id: str,
                 progress: Optional[Callable[[dict], None]] = None):
        kb = quote(knowledge_base_id, safe="")
        info = self._get(f"/knowledge-bases/{kb}")["data"]
        documents = self._list(f"/knowledge-bases/{kb}/knowledge")
        chunks, issues = [], []
        for index, document in enumerate(documents):
            doc_id = document["id"]
            if document.get("parse_status") != "completed":
                issues.append({"document_id": doc_id, "reason": "document_not_parsed"})
            parts = self._list(f"/chunks/{quote(doc_id, safe='')}")
            if not parts:
                issues.append({"document_id": doc_id, "reason": "no_chunks"})
            for part in parts:
                if part.get("knowledge_id") != doc_id:
                    raise RuntimeError("Chunk belongs to a different document")
                content = part.get("content") or ""
                if not content.strip():
                    issues.append({"document_id": doc_id, "chunk_id": part["id"],
                                   "reason": "empty_content"})
                chunks.append({"knowledge_base_id": knowledge_base_id,
                               "document_id": doc_id,
                               "document_title": document.get("title") or document.get("file_name"),
                               "chunk_id": part["id"], "content": content,
                               "sha256": sha256(content.encode()).hexdigest(),
                               "raw": part})
            if progress:
                progress({"documents_done": index + 1, "documents_total": len(documents),
                          "chunks_fetched": len(chunks)})
        # Detect inventory changes across the fetch; this is not a transactional
        # snapshot and the coverage report explicitly records that limitation.
        after = self._list(f"/knowledge-bases/{kb}/knowledge")
        before_versions = {(d["id"], d.get("updated_at")) for d in documents}
        if before_versions != {(d["id"], d.get("updated_at")) for d in after}:
            issues.append({"reason": "inventory_changed_during_snapshot"})
        return {"schema_version": 1, "knowledge_base": info,
                "captured_at": datetime.now(timezone.utc).isoformat(),
                "documents": documents, "chunks": chunks,
                "coverage": {"documents": len(documents), "chunks": len(chunks),
                             "issues": issues, "all_content_available": not issues,
                             "transactional_snapshot": False},
                "audit": {"status": "not_started", "semantic_conflicts": None}}
