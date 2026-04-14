import os

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from helpers.log import get_logger
from core.memory import prune_conversation_history, prune_memories


_scheduler: AsyncIOScheduler | None = None
MEMORY_PRUNE_DAYS = int(os.getenv("MEMORY_PRUNE_DAYS", "14"))
CONVERSATION_HISTORY_PRUNE_HOURS = int(os.getenv("CONVERSATION_HISTORY_PRUNE_HOURS", "48"))
LOGGER = get_logger(__name__)


def register_scheduler_jobs(scheduler: AsyncIOScheduler):
    @scheduler.scheduled_job("cron", hour=4, minute=0)
    async def cleanup_discord_data():
        try:
            LOGGER.info("[scheduler] cleanup started")
            prune_result = prune_memories(older_than_days=MEMORY_PRUNE_DAYS)
            conversation_result = prune_conversation_history(
                older_than_hours=CONVERSATION_HISTORY_PRUNE_HOURS
            )
            LOGGER.info(
                "[scheduler] cleanup completed memory_prune=users=%s pruned=%s kept=%s conversation_history_prune=pruned=%s retention_hours=%s",
                prune_result["users"],
                prune_result["pruned"],
                prune_result["kept"],
                conversation_result["pruned"],
                conversation_result["retention_hours"],
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
