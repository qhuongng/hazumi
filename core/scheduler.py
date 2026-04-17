from apscheduler.schedulers.asyncio import AsyncIOScheduler

from helpers.log import get_logger

_scheduler: AsyncIOScheduler | None = None

LOGGER = get_logger(__name__)


def register_scheduler_jobs(scheduler: AsyncIOScheduler):
    pass


def ensure_scheduler_started():
    global _scheduler
    if _scheduler is None:
        _scheduler = AsyncIOScheduler()
        register_scheduler_jobs(_scheduler)
        job_count = len(_scheduler.get_jobs())
        LOGGER.info("[scheduler] initialized jobs_registered=%s", job_count)
        if job_count == 0:
            LOGGER.info("[scheduler] no jobs registered, skipping start")
            return

    if not _scheduler.running:
        _scheduler.start()
        LOGGER.info("[scheduler] started")
