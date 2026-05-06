from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase

from app.config import settings


class Base(DeclarativeBase):
    pass


_engine = None
_session_factory = None


async def init_db() -> None:
    global _engine, _session_factory
    url = settings.DATABASE_URL
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    _engine = create_async_engine(url, echo=False, connect_args=connect_args)
    _session_factory = async_sessionmaker(_engine, expire_on_commit=False)
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _apply_inline_migrations(conn)


async def _apply_inline_migrations(conn) -> None:
    """Idempotent column additions. Replace with Alembic in production."""
    from sqlalchemy import text

    async def _column_exists(table: str, column: str) -> bool:
        result = await conn.execute(
            text(
                "SELECT COUNT(*) FROM information_schema.columns "
                "WHERE table_schema = DATABASE() "
                "AND table_name = :t AND column_name = :c"
            ),
            {"t": table, "c": column},
        )
        return (result.scalar() or 0) > 0

    # P4: regeneration history columns on project_presentation_links
    if not await _column_exists("project_presentation_links", "prior_link_id"):
        await conn.execute(
            text(
                "ALTER TABLE project_presentation_links "
                "ADD COLUMN prior_link_id VARCHAR(36) NULL, "
                "ADD INDEX idx_ppl_prior (prior_link_id)"
            )
        )
    if not await _column_exists("project_presentation_links", "version"):
        await conn.execute(
            text(
                "ALTER TABLE project_presentation_links "
                "ADD COLUMN version INT NOT NULL DEFAULT 1"
            )
        )

    # P6: backfill project_members from Project.owner_id so existing projects
    # remain accessible after RBAC is enforced. Idempotent — only inserts
    # rows that don't already exist.
    await conn.execute(
        text(
            "INSERT IGNORE INTO project_members "
            "(id, project_id, user_id, role, invited_by, created_at, updated_at) "
            "SELECT UUID(), p.id, p.owner_id, 'owner', p.owner_id, "
            "       COALESCE(p.created_at, UTC_TIMESTAMP()), UTC_TIMESTAMP() "
            "FROM projects p "
            "WHERE NOT EXISTS ("
            "  SELECT 1 FROM project_members m "
            "  WHERE m.project_id = p.id AND m.user_id = p.owner_id"
            ")"
        )
    )

    # P-Templates: discriminator + ownership columns on `templates`. Rows that
    # existed before this migration are seeded built-ins, so they get
    # is_system=true / is_published=true / slide_source='rich'.
    if not await _column_exists("templates", "slide_source"):
        await conn.execute(
            text(
                "ALTER TABLE templates "
                "ADD COLUMN slide_source VARCHAR(16) NOT NULL DEFAULT 'rich'"
            )
        )
    if not await _column_exists("templates", "is_system"):
        await conn.execute(
            text(
                "ALTER TABLE templates "
                "ADD COLUMN is_system BOOLEAN NOT NULL DEFAULT FALSE"
            )
        )
        # Pre-existing rows are the seeded built-ins.
        await conn.execute(text("UPDATE templates SET is_system = TRUE"))
    if not await _column_exists("templates", "is_published"):
        await conn.execute(
            text(
                "ALTER TABLE templates "
                "ADD COLUMN is_published BOOLEAN NOT NULL DEFAULT FALSE"
            )
        )
        # Pre-existing rows (built-ins) are visible to everyone.
        await conn.execute(text("UPDATE templates SET is_published = TRUE"))
    if not await _column_exists("templates", "created_by"):
        await conn.execute(
            text(
                "ALTER TABLE templates "
                "ADD COLUMN created_by VARCHAR(36) NULL, "
                "ADD INDEX idx_templates_created_by (created_by)"
            )
        )
    if not await _column_exists("templates", "role"):
        await conn.execute(
            text(
                "ALTER TABLE templates "
                "ADD COLUMN role VARCHAR(32) NULL"
            )
        )


async def close_db() -> None:
    global _engine
    if _engine:
        await _engine.dispose()
        _engine = None


async def get_db() -> AsyncSession:
    async with _session_factory() as session:
        yield session
