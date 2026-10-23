from sqlalchemy import select

from app.db.models import JobRun
from app.jobs.heartbeat import heartbeat
from app.jobs.runner import run_job


def test_heartbeat_succeeds_and_is_logged(db):
    assert run_job("heartbeat", heartbeat) == 0
    run = db.scalars(select(JobRun)).one()
    assert run.status == "success"
    assert run.items_processed == 3


def test_failing_job_returns_error_code_and_is_logged(db):
    def broken(_db):
        raise RuntimeError("boom")

    assert run_job("broken", broken) == 1
    run = db.scalars(select(JobRun)).one()
    assert run.status == "error"
    assert "boom" in run.error
