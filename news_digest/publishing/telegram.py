"""Telegram delivery with target-level durable success recording."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from telegram import Bot, TelegramError

from news_digest.storage.publication_queue import PublicationQueue, QueueItem


class TelegramPublisher:
    def __init__(self, token: str, queue: PublicationQueue) -> None:
        self.token = token
        self.queue = queue

    async def publish(self, item: QueueItem) -> tuple[int, int]:
        draft = item.payload.get("draft") or {}
        headline = str(draft.get("headline") or item.title).strip()
        caption = (
            f"{headline}\n\n{str(draft.get('caption') or '').strip()}"
            f"\n\nИсточник: {item.canonical_url}"
        ).strip()
        delivered = 0
        failed = 0
        async with Bot(self.token) as bot:
            for target_id in item.target_ids:
                try:
                    if item.image_url:
                        text = _truncate_utf16(caption, 1024)
                        message = await bot.send_photo(
                            chat_id=target_id, photo=item.image_url, caption=text
                        )
                    else:
                        text = _truncate_utf16(caption, 4096)
                        message = await bot.send_message(chat_id=target_id, text=text)
                    await self.queue.mark_target_published(
                        item, target_id=target_id, message_id=str(message.message_id),
                        caption_length=len(text.encode("utf-16-le")) // 2,
                    )
                    delivered += 1
                except (TelegramError, OSError, ValueError) as exc:
                    failed += 1
                    retry_at = (
                        datetime.now(UTC) + timedelta(minutes=min(2 ** item.attempts, 60))
                    ).strftime("%Y-%m-%d %H:%M:%S")
                    await self.queue.mark_failed(
                        item, target_id=target_id,
                        error=f"{type(exc).__name__}: {exc}", retry_at=retry_at,
                    )
        await self.queue.finish_if_complete(item)
        return delivered, failed


def _truncate_utf16(value: str, limit: int) -> str:
    output = []
    used = 0
    for char in value:
        units = len(char.encode("utf-16-le")) // 2
        if used + units > limit:
            break
        output.append(char)
        used += units
    return "".join(output)
