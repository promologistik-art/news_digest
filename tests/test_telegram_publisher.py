from __future__ import annotations

from types import SimpleNamespace

import pytest

from news_digest.publishing.telegram import TelegramPublisher
from news_digest.storage.publication_queue import QueueItem


class FakeQueue:
    def __init__(self) -> None:
        self.published: list[tuple[str, str, int]] = []
        self.completed = False

    async def mark_target_published(
        self,
        _item,
        *,
        target_id: str,
        message_id: str,
        caption_length: int,
    ) -> None:
        self.published.append((target_id, message_id, caption_length))

    async def finish_if_complete(self, _item) -> bool:
        self.completed = True
        return True


class FakeBot:
    last_photo = None
    last_message = None

    def __init__(self, _token: str) -> None:
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def send_photo(self, *, chat_id: str, photo: str, caption: str):
        FakeBot.last_photo = (chat_id, photo, caption)
        return SimpleNamespace(message_id=101)

    async def send_message(self, *, chat_id: str, text: str):
        FakeBot.last_message = (chat_id, text)
        return SimpleNamespace(message_id=102)


def _item(image_url: str | None) -> QueueItem:
    return QueueItem(
        id=1,
        project_id=2,
        article_id=3,
        canonical_url="https://example.com/story",
        title="News",
        image_url=image_url,
        payload={
            "draft": {
                "headline": "News headline",
                "caption": "📰 " + "A detailed news caption. " * 300,
            }
        },
        attempts=1,
        target_ids=("@news_channel",),
    )


@pytest.mark.asyncio
async def test_publisher_sends_selected_image_and_respects_telegram_caption_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("news_digest.publishing.telegram.Bot", FakeBot)
    FakeBot.last_photo = None
    queue = FakeQueue()

    delivered, failed = await TelegramPublisher("test-token", queue).publish(
        _item("https://cdn.example.com/news.jpg")
    )

    assert delivered == 1
    assert failed == 0
    assert FakeBot.last_photo is not None
    chat_id, photo, caption = FakeBot.last_photo
    assert chat_id == "@news_channel"
    assert photo == "https://cdn.example.com/news.jpg"
    assert len(caption.encode("utf-16-le")) // 2 <= 1024
    assert queue.published == [
        ("@news_channel", "101", len(caption.encode("utf-16-le")) // 2)
    ]
    assert queue.completed is True


@pytest.mark.asyncio
async def test_publisher_uses_text_fallback_when_no_image_is_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("news_digest.publishing.telegram.Bot", FakeBot)
    FakeBot.last_message = None
    queue = FakeQueue()

    delivered, failed = await TelegramPublisher("test-token", queue).publish(_item(None))

    assert delivered == 1
    assert failed == 0
    assert FakeBot.last_message is not None
    assert FakeBot.last_message[0] == "@news_channel"
    assert len(FakeBot.last_message[1].encode("utf-16-le")) // 2 <= 4096
    assert queue.completed is True
