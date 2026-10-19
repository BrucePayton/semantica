"""Read-only evidence views and administrator-configured WeKnora audit jobs."""
import json
from hashlib import sha256
import os
from pathlib import Path
import subprocess
import sys
import threading

from fastapi import APIRouter, HTTPException, Query

router = APIRouter(tags=["Document conflicts"])
_lock = threading.Lock()
_process = None


def _root():
    configured = os.getenv("SEMANTICA_WEKNORA_DIR")
    if not configured:
        raise HTTPException(503, "WeKnora integration is not configured")
    return Path(configured).resolve()


def _read(path):
    if not path.is_file():
        raise HTTPException(404, "No snapshot or audit is available yet")
    return json.loads(path.read_text())


@router.get("/api/conflicts/weknora")
def status():
    root = _root()
    snapshot = _read(root/"snapshot.json")
    report_path = root/"audit"/"report.json"
    report = _read(report_path) if report_path.exists() else {"status": "not_started"}
    if report.get("snapshot_sha256") and report["snapshot_sha256"] != sha256((root/"snapshot.json").read_bytes()).hexdigest():
        report = {"status": "not_started", "limitations": ["快照已更新，需要重新检测。"]}
    return {"knowledge_base": {k: snapshot["knowledge_base"].get(k) for k in ("id", "name", "type")},
            "captured_at": snapshot["captured_at"], "coverage": snapshot["coverage"],
            "audit": {k: v for k, v in report.items() if k not in ("conflicts", "uncertain", "errors")},
            "conflict_count": len(report.get("conflicts", [])),
            "uncertain_count": len(report.get("uncertain", [])),
            "errors": report.get("errors", [])}


@router.get("/api/conflicts/weknora/findings")
def findings(kind: str = Query("conflicts", pattern="^(conflicts|uncertain)$"),
             offset: int = Query(0, ge=0), limit: int = Query(30, ge=1, le=100)):
    report = _read(_root()/"audit"/"report.json")
    rows = report.get(kind, [])
    return {"total": len(rows), "items": rows[offset:offset+limit]}


@router.get("/api/conflicts/weknora/source/{chunk_id}")
def source(chunk_id: str):
    snapshot = _read(_root()/"snapshot.json")
    for row in snapshot["chunks"]:
        if row["chunk_id"] == chunk_id:
            return row
    raise HTTPException(404, "Source chunk not found")


@router.post("/api/conflicts/weknora/audit", status_code=202)
def start_audit():
    """Resume against the frozen snapshot; no remote writes or arbitrary commands."""
    global _process
    root = _root()
    _read(root/"snapshot.json")
    with _lock:
        report = root/"audit"/"report.json"
        if _process is not None and _process.poll() is None:
            raise HTTPException(409, "Audit is already running")
        if report.exists():
            previous = _read(report)
            if previous.get("status") in {"checking_model", "extracting", "comparing"}:
                try:
                    os.kill(previous.get("pid", -1) if previous.get("pid", 0) > 0 else 2**30, 0)
                except ProcessLookupError:
                    pass
                except PermissionError:
                    raise HTTPException(409, "Audit process is still running")
                else:
                    raise HTTPException(409, "Audit is already running")
        with (root/"audit.log").open("ab") as log:
            os.chmod(root/"audit.log", 0o600)
            _process = subprocess.Popen(
                [sys.executable, "-m", "semantica.conflicts.codex_audit",
                 str(root/"snapshot.json"), str(root/"audit")],
                stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True)
        return {"status": "started"}
