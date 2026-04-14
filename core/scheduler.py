from apscheduler.schedulers.asyncio import AsyncIOScheduler

from constants.config.db import CONVERSATION_HISTORY_PRUNE_HOURS
from core.memory import prune_conversation_history
from helpers.log import get_logger

_scheduler: AsyncIOScheduler | None = None

LOGGER = get_logger(__name__)


def register_scheduler_jobs(scheduler: AsyncIOScheduler):
    @scheduler.scheduled_job("cron", hour=4, minute=0)
    async def cleanup_discord_data():
        try:
            LOGGER.info("[scheduler] cleanup started")
            conversation_result = prune_conversation_history(
                older_than_hours=CONVERSATION_HISTORY_PRUNE_HOURS
            )
            LOGGER.info(
                "[scheduler] cleanup completed conversation_history_prune=pruned=%s retention_hours=%s",
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
