import os

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from helpers.log import get_logger
from core.memory import delete_old_compacted_messages, delete_old_logs, prune_memories


_scheduler: AsyncIOScheduler | None = None
MEMORY_PRUNE_DAYS = int(os.getenv("MEMORY_PRUNE_DAYS", "14"))
LOGGER = get_logger(__name__)


def register_scheduler_jobs(scheduler: AsyncIOScheduler):
    @scheduler.scheduled_job("cron", hour=4, minute=0)
    async def cleanup_discord_data():
        try:
            LOGGER.info("[scheduler] cleanup started")
            deleted_logs = delete_old_logs(hours=24)
            deleted_compacted = delete_old_compacted_messages(hours=24)
            prune_result = prune_memories(older_than_days=MEMORY_PRUNE_DAYS)
            LOGGER.info(
                "[scheduler] cleanup completed deleted_logs=%s deleted_compacted_messages=%s memory_prune=users=%s pruned=%s kept=%s",
                deleted_logs,
                deleted_compacted,
                prune_result["users"],
                prune_result["pruned"],
                prune_result["kept"],
            )
        except Exception as exc:
            LOGGER.exception("Scheduled cleanup error: %s", exc)


def ensure_scheduler_started():
    global _scheduler
    if _scheduler is None:
        _scheduler = AsyncIOScheduler()
        register_scheduler_jobs(_scheduler)
        LOGGER.info("[scheduler] initialized and jobs registered")

    if not _scheduler.running:
        _scheduler.start()
        LOGGER.info("[scheduler] started")
