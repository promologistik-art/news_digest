from __future__ import annotations

from datetime import UTC, datetime, timedelta

import aiosqlite
import pytest

from news_digest.storage.database import Database
from news_digest.storage.project_repository import ProjectRepository


@pytest.mark.asyncio
async def test_project_source_crud_and_settings_are_isolated(tmp_path) -> None:
    path = tmp_path / "management.sqlite3"
    await Database(path).initialize()
    repository = ProjectRepository(path)
    project_a = await repository.create_project(
        external_user_id="owner-a", slug="culture", name="Culture"
    )
    project_b = await repository.create_project(
        external_user_id="owner-a", slug="tech", name="Technology"
    )

    source_id = await repository.add_source(
        project_id=project_a, url="https://example.com/feed.xml",
        name="Example", reliability_score=0.9,
    )
    assert [item["id"] for item in await repository.list_sources(project_id=project_a)] == [
        source_id
    ]
    assert await repository.list_sources(project_id=project_b) == []

    await repository.set_source_enabled(
        project_id=project_a, source_id=source_id, enabled=False
    )
    assert (await repository.list_sources(project_id=project_a))[0]["enabled"] is False

    await repository.save_rules(
        project_id=project_a, rules={"topics": ["books"], "max_age_hours": 48}
    )
    assert await repository.get_rules(project_id=project_a) == {
        "topics": ["books"],
        "geographies": [],
        "excluded_topics": [],
        "max_age_hours": 48,
    }
    assert await repository.get_rules(project_id=project_b) == {}


@pytest.mark.asyncio
async def test_schedule_validation_and_due_claim_are_persisted(tmp_path) -> None:
    path = tmp_path / "schedules.sqlite3"
    await Database(path).initialize()
    repository = ProjectRepository(path)
    project_id = await repository.create_project(
        external_user_id="owner", slug="daily", name="Daily"
    )
    with pytest.raises(ValueError, match="cron"):
        await repository.set_schedule(
            project_id=project_id, cron_expression="not a cron"
        )

    schedule_id = await repository.set_schedule(
        project_id=project_id, cron_expression="*/5 * * * *",
        timezone="UTC", enabled=True,
    )
    async with aiosqlite.connect(path) as db:
        await db.execute(
            "UPDATE schedules SET next_run_at=? WHERE id=?",
            ((datetime.now(UTC) - timedelta(minutes=1)).replace(tzinfo=None).isoformat(
                sep=" ", timespec="seconds"
            ), schedule_id),
        )
        await db.commit()

    due = await repository.claim_due_schedules(now_utc=datetime.now(UTC))
    assert len(due) == 1
    assert due[0][0] == schedule_id
    assert await repository.claim_due_schedules(now_utc=datetime.now(UTC)) == []
    await repository.finish_schedule(
        schedule_id=schedule_id, cron_expression="*/5 * * * *", timezone="UTC",
        finished_at=datetime.now(UTC),
    )
    assert await repository.claim_due_schedules(now_utc=datetime.now(UTC)) == []


@pytest.mark.asyncio
async def test_only_active_projects_are_selected_by_status(tmp_path) -> None:
    path = tmp_path / "status.sqlite3"
    await Database(path).initialize()
    repository = ProjectRepository(path)
    project_id = await repository.create_project(
        external_user_id="owner", slug="news", name="News"
    )
    await repository.set_project_status(project_id=project_id, status="active")
    with pytest.raises(ValueError, match="Unsupported"):
        await repository.set_project_status(project_id=project_id, status="running")



@pytest.mark.asyncio
async def test_editorial_rules_are_validated_and_normalized(tmp_path) -> None:
    path = tmp_path / "rules-validation.sqlite3"
    await Database(path).initialize()
    repository = ProjectRepository(path)
    project_id = await repository.create_project(
        external_user_id="owner", slug="rules", name="Rules"
    )
    await repository.save_rules(
        project_id=project_id,
        rules={
            "topics": [" кино ", "кино"],
            "geographies": ["Россия"],
            "excluded_topics": [],
            "min_significance": 60,
            "max_age_hours": 48,
        },
    )
    assert await repository.get_rules(project_id=project_id) == {
        "topics": ["кино"],
        "geographies": ["Россия"],
        "excluded_topics": [],
        "min_significance": 60,
        "max_age_hours": 48,
    }
    with pytest.raises(ValueError, match="min_significance"):
        await repository.save_rules(
            project_id=project_id, rules={"min_significance": 101}
        )
    with pytest.raises(ValueError, match="topics"):
        await repository.save_rules(
            project_id=project_id, rules={"topics": ["", 42]}
        )
    with pytest.raises(ValueError, match="Unsupported"):
        await repository.save_rules(
            project_id=project_id, rules={"unknown": True}
        )


@pytest.mark.asyncio
async def test_feed_url_must_be_absolute_http_url(tmp_path) -> None:
    path = tmp_path / "source-validation.sqlite3"
    await Database(path).initialize()
    repository = ProjectRepository(path)
    project_id = await repository.create_project(
        external_user_id="owner", slug="feeds", name="Feeds"
    )
    with pytest.raises(ValueError, match="HTTP"):
        await repository.add_source(
            project_id=project_id, url="file:///etc/passwd"
        )
    with pytest.raises(ValueError, match="Credentials"):
        await repository.add_source(
            project_id=project_id, url="https://user:pass@example.com/feed"
        )



@pytest.mark.asyncio
async def test_monthly_ai_budget_is_validated(tmp_path) -> None:
    path = tmp_path / "ai-budget-rules.sqlite3"
    await Database(path).initialize()
    repository = ProjectRepository(path)
    project_id = await repository.create_project(
        external_user_id="owner", slug="ai-budget", name="AI Budget"
    )
    await repository.save_rules(
        project_id=project_id, rules={"monthly_ai_budget_rub": 25.5}
    )
    assert (await repository.get_rules(project_id=project_id))[
        "monthly_ai_budget_rub"
    ] == 25.5
    with pytest.raises(ValueError, match="non-negative"):
        await repository.save_rules(
            project_id=project_id, rules={"monthly_ai_budget_rub": -1}
        )



@pytest.mark.asyncio
async def test_project_language_and_timezone_can_be_updated(tmp_path) -> None:
    path = tmp_path / "project-settings.sqlite3"
    await Database(path).initialize()
    repository = ProjectRepository(path)
    project_id = await repository.create_project(
        external_user_id="owner", slug="international", name="International"
    )
    await repository.update_project_settings(
        project_id=project_id, language="en", timezone="UTC"
    )
    project = (await repository.list_projects(external_user_id="owner"))[0]
    assert project["language"] == "en"
    assert project["timezone"] == "UTC"
    with pytest.raises(ValueError, match="timezone"):
        await repository.update_project_settings(
            project_id=project_id, language="en", timezone="Unknown/Zone"
        )
