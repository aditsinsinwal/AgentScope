from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentscope.persistence.models import RunRecord, WorkerRecord


class LeaseCoordinator:
    """PostgreSQL-backed at-most-one-active-owner run claiming.

    Claims use row locks with SKIP LOCKED. Expired pre-start leases can be reassigned; partially
    executed agent runs require explicit reconciliation rather than automatic replay.
    """

    def __init__(self, sessions: async_sessionmaker[AsyncSession], lease_seconds: int = 60) -> None:
        self.sessions = sessions
        self.lease_seconds = lease_seconds

    async def heartbeat(self, worker_id: str) -> None:
        now = datetime.now(UTC)
        async with self.sessions() as session, session.begin():
            worker = await session.get(WorkerRecord, worker_id)
            if worker:
                worker.heartbeat_at = now
            else:
                session.add(WorkerRecord(id=worker_id, started_at=now, heartbeat_at=now))

    async def claim(self, worker_id: str) -> str | None:
        now = datetime.now(UTC)
        async with self.sessions() as session, session.begin():
            statement = (
                select(RunRecord)
                .where(
                    RunRecord.status == "queued",
                    or_(RunRecord.lease_until.is_(None), RunRecord.lease_until < now),
                )
                .order_by(RunRecord.created_at)
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            run = await session.scalar(statement)
            if run is None:
                return None
            run.worker_id = worker_id
            run.lease_until = now + timedelta(seconds=self.lease_seconds)
            run.attempt += 1
            return run.id

    async def renew(self, run_id: str, worker_id: str) -> bool:
        deadline = datetime.now(UTC) + timedelta(seconds=self.lease_seconds)
        async with self.sessions() as session, session.begin():
            result = await session.execute(
                update(RunRecord)
                .where(RunRecord.id == run_id, RunRecord.worker_id == worker_id)
                .values(lease_until=deadline)
            )
            return bool(result.rowcount)
