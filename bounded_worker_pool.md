Yes. The main speedup is to move from a single sequential batch loop to a bounded worker pool, while preserving independent cache commits and audit directories. I’ll outline a safe concurrency design, rate-limit controls, retry behavior, and the exact CLI changes needed so parallel runs do not corrupt SQLite or overwrite batch artifacts.Yes. The safest and most effective improvement is bounded parallel batch execution in the Python orchestrator.

For 30 jobs split into six batches, four concurrent workers can reduce the critical path from six sequential AI calls to roughly two waves of calls. If each call takes 3 to 5 minutes, total extraction time can potentially decrease from approximately 20 to 30 minutes to around 6 to 12 minutes, subject to provider quota, throttling, and local resource limits.

already supports independent non-interactive headless invocations using agy -p, so several separate agy processes can be launched concurrently. Its documented background/subagent architecture also supports parallel work, but independent headless processes are easier to audit, retry, and cache for this extraction pipeline.

Recommended optimization order
Add bounded batch concurrency.
Keep database writes serialized.
Add live progress output.
Add rate-limit-aware retries.
Use adaptive batch sizes.
Reduce repeated prompt content.
Add optional streaming heartbeats.
Add resumable task states for larger datasets.

1. Run multiple batches concurrently

Currently, the extraction loop effectively does:

for batch in batches:
result = adapter.invoke(batch)
validate(result)
save_to_database(result)

Change it to:

Prepare all pending batches
|
+-- Worker 1 -> Batch 1
+-- Worker 2 -> Batch 2
+-- Worker 3 -> Batch 3
+-- Worker 4 -> Batch 4
|
+-- Main thread validates and commits completed results
|
+-- Available worker -> Batch 5
+-- Available worker -> Batch 6

Use ThreadPoolExecutor, because each worker mostly waits for an external agy subprocess. Python threads are sufficient for this kind of I/O-bound orchestration.

Suggested CLI
jobmatch extract-jobs \
 --adapter antigravity \
 --db data/work/jobmatcher.db \
 --batch-size 5 \
 --workers 3

Start with:

workers = 2

Then test:

workers = 3
workers = 4

Do not start immediately with 10 or 20 workers. Provider-side limits may cause throttling, quota errors, or lower reliability.

2. Do not let workers write to SQLite directly

SQLite supports multiple readers, but write operations are serialized. Several extraction workers attempting to update jobs and extraction_cache simultaneously can cause:

database is locked

or create unpredictable commit timing.

Use this design:

Worker:
Invoke AI
Parse response
Validate schema
Verify evidence
Return validated result

Main thread:
Receive completed result
Open database transaction
Update all jobs in the batch
Write extraction-cache entries
Commit transaction

This keeps AI inference parallel while database writes remain safe and short.

Recommended result object
@dataclass
class BatchExtractionResult:
batch_id: str
job_keys: list[tuple[str, str]]
extracted_jobs: list[ExtractedJobFacts]
valid: bool
errors: list[dict]
attempts: int
duration_seconds: float

The worker returns this object. It does not call upsert_job() or write to extraction_cache.

3. Implement a bounded worker pool

A suitable extraction structure is:

from concurrent.futures import (
ThreadPoolExecutor,
as_completed,
)
from dataclasses import dataclass
from time import monotonic

Worker function
def process_batch(
\*,
batch_number: int,
chunk,
adapter_name: str,
adapter_config: dict,
workspace: Path,
executable: str | None,
schema_path: Path,
prompt_path: Path,
repair_path: Path,
) -> BatchExtractionResult:
batch_id = f"batch-{batch_number:06d}"

    audit_dir = (
        workspace
        / "data"
        / "output"
        / "extraction-audit"
        / adapter_name
        / batch_id
    )

    input_jobs = [
        {
            "job_id": job.job_id,
            "title": job.title,
            "company": job.company,
            "location_country_code": (
                job.location_country_code
            ),
            "description": job.description,
        }
        for job, _ in chunk
    ]

    input_object = {
        "schema_version": "extraction-input.v1",
        "jobs": input_jobs,
    }

    audit_dir.mkdir(parents=True, exist_ok=True)

    (audit_dir / "input.json").write_text(
        json.dumps(
            input_object,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    adapter = create_adapter(
        adapter_name,
        adapter_config,
        workspace,
        executable,
    )

    started = monotonic()

    prompt = render_prompt(
        prompt_path,
        input_object,
    )

    result = adapter.invoke(
        prompt,
        schema_path,
        audit_dir / "attempt-1",
    )

    parsed, errors = validate_agent_result(
        result,
        input_jobs,
    )

    attempts = 1

    if errors:
        attempts = 2

        repair_prompt = render_repair_prompt(
            repair_path,
            input_object,
            errors,
            result.data,
        )

        repaired_result = adapter.invoke(
            repair_prompt,
            schema_path,
            audit_dir / "attempt-2",
        )

        parsed, errors = validate_agent_result(
            repaired_result,
            input_jobs,
        )

    duration = monotonic() - started

    (audit_dir / "validation.json").write_text(
        json.dumps(
            {
                "valid": not errors,
                "errors": errors,
                "duration_seconds": round(duration, 2),
                "attempts": attempts,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    return BatchExtractionResult(
        batch_id=batch_id,
        job_keys=[
            (job.job_id, task_key)
            for job, task_key in chunk
        ],
        extracted_jobs=(
            parsed.jobs if parsed and not errors else []
        ),
        valid=not errors,
        errors=errors,
        attempts=attempts,
        duration_seconds=duration,
    )

Parallel coordinator
def execute_batches_parallel(
\*,
pending,
batch_size: int,
workers: int,
process_kwargs: dict,
):
batches = [
pending[index:index + batch_size]
for index in range(0, len(pending), batch_size)
]

    completed_batches = []
    failed_batches = []

    with ThreadPoolExecutor(
        max_workers=workers
    ) as executor:
        futures = {
            executor.submit(
                process_batch,
                batch_number=batch_number,
                chunk=chunk,
                **process_kwargs,
            ): batch_number
            for batch_number, chunk
            in enumerate(batches)
        }

        total = len(futures)

        for completed_count, future in enumerate(
            as_completed(futures),
            start=1,
        ):
            batch_number = futures[future]

            try:
                result = future.result()
            except Exception as error:
                result = BatchExtractionResult(
                    batch_id=(
                        f"batch-{batch_number:06d}"
                    ),
                    job_keys=[],
                    extracted_jobs=[],
                    valid=False,
                    errors=[
                        {
                            "error": str(error),
                            "type": (
                                error.__class__.__name__
                            ),
                        }
                    ],
                    attempts=1,
                    duration_seconds=0,
                )

            if result.valid:
                completed_batches.append(result)
            else:
                failed_batches.append(result)

            typer.echo(
                format_progress_message(
                    completed_count=completed_count,
                    total_batches=total,
                    result=result,
                ),
                err=True,
            )

    return completed_batches, failed_batches

4. Commit each completed batch in the main thread

After a future completes successfully:

def commit_batch(
db_path: str,
result: BatchExtractionResult,
jobs_by_id: dict,
cache_metadata: dict,
):
facts_by_id = {
fact.job_id: fact
for fact in result.extracted_jobs
}

    connection = connect(db_path)

    try:
        connection.execute("BEGIN IMMEDIATE")

        for job_id, task_key in result.job_keys:
            job = jobs_by_id[job_id]
            fact = facts_by_id[job_id]

            apply_extracted_facts(job, fact)

            connection.execute(
                """
                INSERT INTO jobs(
                    job_id,
                    content_hash,
                    payload
                )
                VALUES (?, ?, ?)
                ON CONFLICT(job_id)
                DO UPDATE SET
                    content_hash = excluded.content_hash,
                    payload = excluded.payload,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    job.job_id,
                    job.content_hash,
                    job.model_dump_json(),
                ),
            )

            connection.execute(
                """
                INSERT OR REPLACE INTO extraction_cache(
                    task_key,
                    job_id,
                    job_content_hash,
                    prompt_hash,
                    schema_hash,
                    adapter_config_hash,
                    payload
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task_key,
                    job.job_id,
                    job.content_hash,
                    cache_metadata["prompt_hash"],
                    cache_metadata["schema_hash"],
                    cache_metadata[
                        "adapter_config_hash"
                    ],
                    json.dumps(
                        fact.model_dump(mode="json"),
                        ensure_ascii=False,
                    ),
                ),
            )

        connection.commit()

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()

A batch transaction ensures that either:

the whole validated batch is committed, or
none of it is committed.

That prevents partially cached batches.

5. Add the --workers option

Update the command:

@app.command("extract-jobs")
def extract_jobs_cmd(
db: str = typer.Option(
"data/work/jobmatcher.db",
"--db",
),
adapter: str = typer.Option(
"antigravity",
"--adapter",
),
batch_size: int = typer.Option(
5,
"--batch-size",
min=1,
max=50,
),
workers: int = typer.Option(
2,
"--workers",
min=1,
max=8,
help=(
"Maximum number of concurrent "
"agent batch invocations"
),
),
force: bool = typer.Option(
False,
"--force",
),
executable: str | None = typer.Option(
None,
"--executable",
),
):
summary = extract(
db,
Path.cwd(),
batch_size=batch_size,
workers=workers,
force=force,
executable=executable,
adapter_name=adapter,
)

    typer.echo(
        json.dumps(
            summary,
            ensure_ascii=False,
            indent=2,
        )
    )

Recommended default:

--workers 2

A conservative default avoids unexpectedly consuming several concurrent model requests.

6. Emit progress after every completed batch

Concurrency solves runtime, but progress output solves the “frozen terminal” problem.

Write progress messages to stderr so the final JSON summary remains clean on stdout. Headless similarly separates its model response on stdout from diagnostics on stderr.

Suggested progress format
[1/6] batch-000001 completed: 5 jobs, 212.4s
[2/6] batch-000000 completed: 5 jobs, 225.1s
[3/6] batch-000003 failed: 5 jobs, repair exhausted
[4/6] batch-000002 completed: 5 jobs, 238.8s

Batches may finish out of numerical order. This is expected under concurrency.

Progress helper
def format_progress_message(
\*,
completed_count: int,
total_batches: int,
result: BatchExtractionResult,
) -> str:
status = (
"completed"
if result.valid
else "failed"
)

    return (
        f"[{completed_count}/{total_batches}] "
        f"{result.batch_id} {status}: "
        f"{len(result.job_keys)} jobs, "
        f"{result.duration_seconds:.1f}s, "
        f"{result.attempts} attempt(s)"
    )

Call:

typer.echo(message, err=True)

The final stdout can remain machine-readable:

{
"adapter": "antigravity",
"total": 30,
"cached": 0,
"completed": 30,
"failed": [],
"workers": 3,
"batches": 6,
"duration_seconds": 719.4
}

7. Use unique audit directories per run

Your current directories use names like:

batch-000001
batch-000002

If two extraction commands run at the same time, they can overwrite each other’s artifacts.

Add a run ID:

data/output/extraction-audit/
└── antigravity/
└── run-20261028T130500Z-a83f2c/
├── batch-000000/
├── batch-000001/
└── run-summary.json

Generate it once:

from datetime import datetime, timezone
from uuid import uuid4

run_id = (
datetime.now(timezone.utc)
.strftime("run-%Y%m%dT%H%M%SZ-") + uuid4().hex[:6]
)

This becomes especially important after enabling worker concurrency.

8. Add retry backoff for provider throttling

When several agy processes start together, the account may return temporary failures.

Classify errors:

Retryable
timeout
HTTP 429 or rate-limit message
temporary service unavailable
network reset
provider process terminated
malformed output after an otherwise successful call
Normally not retryable
invalid executable
authentication required
unsupported flags
invalid JSON Schema
job input validation failure
unavailable model caused by bad configuration

Use exponential backoff:

import random
import time

def retry_delay(attempt: int) -> float:
base = min(60, 2 \*\* attempt)
jitter = random.uniform(0, 1.5)
return base + jitter

Example sequence:

Attempt 1 fails
Wait approximately 2-3.5 seconds

Attempt 2 fails
Wait approximately 4-5.5 seconds

Attempt 3 fails
Quarantine batch

Do not let every worker retry simultaneously at exact intervals. Jitter prevents synchronized retry storms.

9. Add a request-start stagger

Starting four large prompts in the same millisecond can produce throttling.

Stagger worker submissions:

submission_delay_seconds = 1.5

for batch_number, chunk in enumerate(batches):
future = executor.submit(
process_batch,
batch_number=batch_number,
chunk=chunk,
\*\*process_kwargs,
)

    futures[future] = batch_number

    if batch_number < len(batches) - 1:
        time.sleep(submission_delay_seconds)

For six batches, this adds only a few seconds but can reduce burst-related failures.

10. Choose concurrency based on observed behavior

Recommended rollout:

First test
jobmatch extract-jobs \
 --adapter antigravity \
 --batch-size 5 \
 --workers 2

If stable
jobmatch extract-jobs \
 --adapter antigravity \
 --batch-size 5 \
 --workers 3

If quota and reliability remain stable
jobmatch extract-jobs \
 --adapter antigravity \
 --batch-size 5 \
 --workers 4

Avoid increasing workers if you observe:

repeated rate-limit errors,
authentication-state conflicts,
timeouts increasing,
output truncation,
malformed structured results,
repair frequency increasing,
quota exhaustion.

A worker count of 3 is a reasonable expected sweet spot for the described workload.

11. Consider increasing batch size carefully

With 30 jobs:

batch size 5 = 6 calls
batch size 10 = 3 calls
batch size 15 = 2 calls

However, larger batches mean:

larger prompts,
larger structured responses,
higher chance that one omitted job invalidates the entire batch,
more expensive repair calls,
greater blast radius when a batch fails.

A practical combination is:

batch size: 5
workers: 3

This produces two waves of three calls.

Another option:

batch size: 8
workers: 2

This produces four batches in two waves.

I would not recommend a batch of 15 without testing extraction recall and schema compliance.

12. Use adaptive batching

Job descriptions vary greatly in length. A fixed five-job batch may contain:

five short advertisements, or
five extremely long advertisements.

Use a character or token budget.

Example character-aware batching:

def make_batches(
jobs,
\*,
maximum_jobs: int = 8,
maximum_characters: int = 55_000,
):
batch = []
characters = 0

    for item in jobs:
        job, task_key = item
        size = len(job.description)

        would_overflow = (
            batch
            and (
                len(batch) >= maximum_jobs
                or characters + size
                > maximum_characters
            )
        )

        if would_overflow:
            yield batch
            batch = []
            characters = 0

        batch.append(item)
        characters += size

    if batch:
        yield batch

This produces more consistent inference durations and reduces oversized prompts.

13. Reduce prompt size

Your approximately 17 to 18 KB prompts are not huge, but repeated content still affects latency.

Potential reductions:

Send only extraction-relevant fields

Keep:

{
"job_id": "...",
"title": "...",
"company": "...",
"description": "..."
}

Remove fields the agent does not use.

Keep the prompt concise

Do not repeat lengthy explanations that the schema already enforces.

Use canonical enum descriptions in one place

Avoid duplicating the full taxonomy and examples on every invocation unless necessary.

Avoid passing candidate data

Job extraction should remain candidate-independent.

Do not request verbose explanations

Request only structured fields and exact source evidence.

14. Use streaming output for heartbeat visibility

supports stream-json, which emits newline-delimited progress events, while normal json waits and returns one object at completion.

However, do not replace the structured-output path immediately. A safer design is:

continue using schema-constrained final JSON where supported,
add orchestrator-level heartbeat messages,
optionally add a separate streaming adapter mode later.

If using stream-json, the adapter must:

read stdout line by line,
write every event to events.jsonl,
update a heartbeat timestamp,
locate the final agent response,
validate the final structured object,
preserve stderr separately.

For this workflow, orchestrator batch progress gives most of the usability benefit with less parser complexity.

15. Add per-batch heartbeat files

While each agy process is running, write:

status.json

Example:

{
"batch_id": "batch-000003",
"status": "running",
"worker_id": 2,
"started_at": "2026-10-28T13:05:22Z",
"last_heartbeat_at": "2026-10-28T13:08:22Z",
"attempt": 1,
"job_ids": [
"jobstreet_sg-11",
"jobstreet_sg-12",
"jobstreet_sg-13",
"jobstreet_sg-14",
"jobstreet_sg-15"
]
}

Update every 30 seconds from the parent coordinator.

After completion:

{
"status": "completed",
"duration_seconds": 243.8
}

This lets monitoring tools distinguish:

running
stalled
completed
failed

16. Add jobmatch extraction-status

A status command avoids manual directory inspection:

jobmatch extraction-status \
 --adapter antigravity

Suggested output:

Run: run-20261028T130500Z-a83f2c
Adapter: antigravity

Completed: 3/6
Running: 3
Failed: 0
Pending: 0

batch-000000 completed 5 jobs 221.4s
batch-000001 completed 5 jobs 208.7s
batch-000002 completed 5 jobs 236.1s
batch-000003 running 5 jobs 91.2s
batch-000004 running 5 jobs 88.9s
batch-000005 running 5 jobs 87.5s

This improves visibility without changing agent execution.

17. Do not use Antigravity subagents as the primary batching mechanism

supports parallel subagents and background tasks in its interactive architecture.

However, for this pipeline, independent orchestrator-controlled headless processes are preferable because each batch needs:

a stable batch ID,
its own schema validation,
exact audit files,
independent retries,
independent cache entries,
deterministic database commits,
provider-neutral behavior across Claude, Codex, and Copilot.

If batching were delegated inside one large agent session, cache and audit boundaries would become harder to enforce.

Use:

Python worker pool
-> independent agy process per batch

rather than:

one agy prompt
-> ask agent to create six internal subagents

18. Expected performance

For six batches at 3 to 5 minutes each:

Sequential
6 × 3-5 minutes
= 18-30 minutes

Two workers
3 waves × 3-5 minutes
= approximately 9-15 minutes

Three workers
2 waves × 3-5 minutes
= approximately 6-10 minutes

Four workers
2 waves
= approximately 6-10 minutes

Four workers do not reduce six batches to one wave, so the improvement over three workers may be small.

For this workload, I recommend:

jobmatch extract-jobs \
 --adapter antigravity \
 --batch-size 5 \
 --workers 3

19. Recommended implementation configuration
    extraction:
    batch_size: 5
    workers: 3
    submission_delay_seconds: 1.5
    maximum_attempts: 3
    retry_initial_seconds: 2
    retry_multiplier: 2
    retry_jitter_seconds: 1.5
    heartbeat_seconds: 30
    transaction_per_batch: true
    maximum_batch_characters: 55000

For job extraction, keep in non-interactive headless mode. Its headless mode is specifically intended for scripts and CI, and keeps response output on stdout and diagnostics on stderr.

Best immediate change

The highest-value minimal patch is:

Add --workers
Use ThreadPoolExecutor
Keep AI calls inside workers
Keep SQLite commits in the main thread
Print one stderr progress line per completed batch
Use run-specific audit directories

That should substantially reduce runtime without changing the extraction schema, evidence validation, repair process, eligibility logic, scoring logic, or cache semantics.
