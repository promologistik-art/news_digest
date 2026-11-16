"""Read-only adapter for KontentFabrik's existing PostgreSQL registry."""

from __future__ import annotations

from dataclasses import dataclass

import asyncpg


class KontentFabrikError(RuntimeError):
    """Raised when KontentFabrik cannot resolve an active worker binding."""


@dataclass(frozen=True, slots=True)
class KontentFabrikBinding:
    head_user_id: int
    worker_user_id: int
    bot_type: str
    clone_id: int
    bot_username: str
    db_prefix: str


class KontentFabrikAdapter:
    """Resolve the head-bot identity to a news_digest worker identity.

    This adapter reads only kf_users, user_bindings and workers. It never writes
    to KontentFabrik; project data remains in this worker's own database.
    """

    def __init__(self, database_url: str, *, bot_type: str = "news_digest") -> None:
        if not database_url:
            raise ValueError("KONTENTFABRIK_DATABASE_URL is required.")
        self.database_url = database_url.replace(
            "postgresql+asyncpg://", "postgresql://", 1
        )
        self.bot_type = bot_type

    async def resolve_binding(self, *, head_user_id: int) -> KontentFabrikBinding:
        connection = await asyncpg.connect(
            self.database_url,
            server_settings={"default_transaction_read_only": "on"},
        )
        try:
            row = await connection.fetchrow(
                """
                SELECT b.head_user_id, b.worker_user_id, b.bot_type, b.clone_id,
                       w.bot_username, w.db_prefix
                FROM user_bindings b
                JOIN workers w
                  ON w.bot_type=b.bot_type AND w.clone_id=b.clone_id
                JOIN kf_users u ON u.telegram_id=b.head_user_id
                WHERE b.head_user_id=$1 AND b.bot_type=$2
                  AND w.is_active IS TRUE
                ORDER BY b.id DESC LIMIT 1
                """,
                head_user_id, self.bot_type,
            )
        except (asyncpg.UndefinedTableError, asyncpg.UndefinedColumnError) as exc:
            raise KontentFabrikError(
                "KontentFabrik registry schema is not available."
            ) from exc
        finally:
            await connection.close()

        if row is None:
            raise KontentFabrikError(
                f"No active {self.bot_type} worker binding for this KontentFabrik user."
            )
        return KontentFabrikBinding(
            head_user_id=int(row["head_user_id"]),
            worker_user_id=int(row["worker_user_id"]),
            bot_type=str(row["bot_type"]),
            clone_id=int(row["clone_id"]),
            bot_username=str(row["bot_username"]),
            db_prefix=str(row["db_prefix"]),
        )
