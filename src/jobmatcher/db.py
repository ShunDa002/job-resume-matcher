from __future__ import annotations
import json, sqlite3
from pathlib import Path
from .models import CandidateProfile, JobRecord, MatchResult

SCHEMA = """
CREATE TABLE IF NOT EXISTS candidates(candidate_id TEXT PRIMARY KEY, content_hash TEXT NOT NULL, payload TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS jobs(job_id TEXT PRIMARY KEY, content_hash TEXT NOT NULL, payload TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP, updated_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS matches(candidate_id TEXT NOT NULL, job_id TEXT NOT NULL, run_key TEXT NOT NULL, eligibility_status TEXT NOT NULL, final_score REAL, payload TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY(candidate_id,job_id,run_key));
CREATE INDEX IF NOT EXISTS idx_matches_candidate ON matches(candidate_id,eligibility_status,final_score DESC);
"""


def connect(path):
    p = Path(path)
    if str(path) not in (":memory:", "") and not str(path).startswith("file:"):
        p.parent.mkdir(parents=True, exist_ok=True)
        if not p.exists() or p.stat().st_size == 0:
            with sqlite3.connect(path) as init_c:
                init_c.execute("VACUUM")
    c = sqlite3.connect(path)
    c.row_factory = sqlite3.Row
    return c


def init_db(path):
    with connect(path) as c:
        c.executescript(SCHEMA)


def upsert_candidate(path, candidate, content_hash):
    with connect(path) as c:
        c.execute(
            "INSERT INTO candidates VALUES(?,?,?,CURRENT_TIMESTAMP) ON CONFLICT(candidate_id) DO UPDATE SET content_hash=excluded.content_hash,payload=excluded.payload",
            (candidate.candidate_id, content_hash, candidate.model_dump_json()),
        )


def upsert_job(path, job):
    with connect(path) as c:
        c.execute(
            "INSERT INTO jobs(job_id,content_hash,payload) VALUES(?,?,?) ON CONFLICT(job_id) DO UPDATE SET content_hash=excluded.content_hash,payload=excluded.payload,updated_at=CURRENT_TIMESTAMP",
            (job.job_id, job.content_hash, job.model_dump_json()),
        )


def get_candidate(path, candidate_id):
    with connect(path) as c:
        r = c.execute(
            "SELECT payload FROM candidates WHERE candidate_id=?", (candidate_id,)
        ).fetchone()
    if not r:
        raise KeyError(f"Candidate not found: {candidate_id}")
    return CandidateProfile.model_validate_json(r[0])


def get_jobs(path):
    with connect(path) as c:
        rows = c.execute("SELECT payload FROM jobs ORDER BY job_id").fetchall()
    return [JobRecord.model_validate_json(r[0]) for r in rows]


def save_match(path, result, run_key):
    score = result.scores.final_match_score if result.scores else None
    with connect(path) as c:
        c.execute(
            "INSERT OR REPLACE INTO matches(candidate_id,job_id,run_key,eligibility_status,final_score,payload) VALUES(?,?,?,?,?,?)",
            (
                result.candidate_id,
                result.job_id,
                run_key,
                result.eligibility_status.value,
                score,
                result.model_dump_json(),
            ),
        )


def get_matches(path, candidate_id, run_key=None):
    sql = "SELECT payload FROM matches WHERE candidate_id=?"
    args = [candidate_id]
    if run_key:
        sql += " AND run_key=?"
        args.append(run_key)
    with connect(path) as c:
        rows = c.execute(sql, args).fetchall()
    return [MatchResult.model_validate_json(r[0]) for r in rows]
