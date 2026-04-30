from __future__ import annotations

from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ForbiddenError, NotFoundError
from app.models.presentation import Presentation
from app.models.project import Project, ProjectDocument, ProjectPresentationLink
from app.models.user import User
from app.schemas.project import (
    DocumentListItem,
    ProjectCreateRequest,
    ProjectDetail,
    ProjectListItem,
    ProjectPresentationItem,
    ProjectUpdateRequest,
)


def _ts(dt) -> str:
    return dt.isoformat() if dt else ""


def _to_list_item(p: Project, doc_count: int, pres_count: int) -> ProjectListItem:
    return ProjectListItem(
        id=str(p.id),
        name=p.name,
        description=p.description,
        status=p.status,
        tags=p.tags or [],
        owner_id=str(p.owner_id),
        document_count=doc_count,
        presentation_count=pres_count,
        created_at=_ts(p.created_at),
        updated_at=_ts(p.updated_at),
    )


def _doc_to_item(d: ProjectDocument) -> DocumentListItem:
    return DocumentListItem(
        id=str(d.id),
        project_id=str(d.project_id),
        filename=d.filename,
        original_filename=d.original_filename,
        format=d.format,
        size_bytes=d.size_bytes,
        version=d.version,
        extraction_status=d.extraction_status,
        tags=d.tags or [],
        uploaded_by=str(d.uploaded_by),
        created_at=_ts(d.created_at),
        updated_at=_ts(d.updated_at),
    )


def _link_to_item(
    link: ProjectPresentationLink, presentation: Optional[Presentation]
) -> ProjectPresentationItem:
    return ProjectPresentationItem(
        id=str(link.id),
        project_id=str(link.project_id),
        presentation_id=str(link.presentation_id),
        role=link.role,
        prompt_version=link.prompt_version,
        source_document_ids=link.source_document_ids or [],
        generated_by=str(link.generated_by),
        title=presentation.title if presentation else "",
        slide_count=len(presentation.slides) if presentation and presentation.slides else 0,
        created_at=_ts(link.created_at),
    )


async def _ensure_owner(project: Project, user: User) -> None:
    if str(project.owner_id) != str(user.id) and user.role != "admin":
        raise ForbiddenError("You do not have access to this project")


async def _load_project(db: AsyncSession, project_id: str) -> Project:
    p = (
        await db.execute(select(Project).where(Project.id == project_id))
    ).scalar_one_or_none()
    if not p:
        raise NotFoundError(f"Project {project_id} not found")
    return p


async def get_project_for_user(
    db: AsyncSession, user: User, project_id: str
) -> Project:
    p = await _load_project(db, project_id)
    await _ensure_owner(p, user)
    return p


# ── CRUD ─────────────────────────────────────────────────────────────────────

async def create_project(
    db: AsyncSession, user: User, req: ProjectCreateRequest
) -> ProjectListItem:
    project = Project(
        owner_id=str(user.id),
        name=req.name,
        description=req.description,
        status=req.status,
        tags=req.tags or [],
    )
    db.add(project)
    await db.commit()
    await db.refresh(project)
    return _to_list_item(project, 0, 0)


async def list_projects(
    db: AsyncSession,
    user: User,
    status: Optional[str] = None,
    search: Optional[str] = None,
    sort: str = "updated_desc",
) -> list[ProjectListItem]:
    stmt = select(Project).where(Project.owner_id == user.id)
    if status:
        stmt = stmt.where(Project.status == status)
    if search:
        like = f"%{search}%"
        stmt = stmt.where(
            (Project.name.ilike(like)) | (Project.description.ilike(like))
        )

    sort_map = {
        "updated_desc": Project.updated_at.desc(),
        "updated_asc": Project.updated_at.asc(),
        "created_desc": Project.created_at.desc(),
        "created_asc": Project.created_at.asc(),
        "name_asc": Project.name.asc(),
        "name_desc": Project.name.desc(),
    }
    stmt = stmt.order_by(sort_map.get(sort, Project.updated_at.desc()))

    projects = (await db.execute(stmt)).scalars().all()
    if not projects:
        return []

    pids = [str(p.id) for p in projects]
    doc_rows = (
        await db.execute(
            select(ProjectDocument.project_id, func.count(ProjectDocument.id))
            .where(ProjectDocument.project_id.in_(pids))
            .group_by(ProjectDocument.project_id)
        )
    ).all()
    pres_rows = (
        await db.execute(
            select(
                ProjectPresentationLink.project_id,
                func.count(ProjectPresentationLink.id),
            )
            .where(ProjectPresentationLink.project_id.in_(pids))
            .group_by(ProjectPresentationLink.project_id)
        )
    ).all()
    doc_map = {pid: cnt for pid, cnt in doc_rows}
    pres_map = {pid: cnt for pid, cnt in pres_rows}

    return [
        _to_list_item(p, doc_map.get(str(p.id), 0), pres_map.get(str(p.id), 0))
        for p in projects
    ]


async def get_project_detail(
    db: AsyncSession, user: User, project_id: str
) -> ProjectDetail:
    project = await get_project_for_user(db, user, project_id)

    docs = (
        await db.execute(
            select(ProjectDocument)
            .where(ProjectDocument.project_id == project_id)
            .order_by(ProjectDocument.created_at.desc())
        )
    ).scalars().all()

    links = (
        await db.execute(
            select(ProjectPresentationLink)
            .where(ProjectPresentationLink.project_id == project_id)
            .order_by(ProjectPresentationLink.created_at.desc())
        )
    ).scalars().all()

    pres_ids = [str(l.presentation_id) for l in links]
    pres_map: dict[str, Presentation] = {}
    if pres_ids:
        pres_rows = (
            await db.execute(
                select(Presentation).where(Presentation.id.in_(pres_ids))
            )
        ).scalars().all()
        pres_map = {str(p.id): p for p in pres_rows}

    base = _to_list_item(project, len(docs), len(links))
    return ProjectDetail(
        **base.model_dump(),
        documents=[_doc_to_item(d) for d in docs],
        presentations=[
            _link_to_item(l, pres_map.get(str(l.presentation_id))) for l in links
        ],
    )


async def update_project(
    db: AsyncSession, user: User, project_id: str, req: ProjectUpdateRequest
) -> ProjectListItem:
    project = await get_project_for_user(db, user, project_id)

    if req.name is not None:
        project.name = req.name
    if req.description is not None:
        project.description = req.description
    if req.tags is not None:
        project.tags = req.tags
    if req.status is not None:
        project.status = req.status

    await db.commit()
    await db.refresh(project)

    doc_count = (
        await db.execute(
            select(func.count(ProjectDocument.id)).where(
                ProjectDocument.project_id == project_id
            )
        )
    ).scalar_one()
    pres_count = (
        await db.execute(
            select(func.count(ProjectPresentationLink.id)).where(
                ProjectPresentationLink.project_id == project_id
            )
        )
    ).scalar_one()

    return _to_list_item(project, doc_count, pres_count)


async def delete_project(db: AsyncSession, user: User, project_id: str) -> None:
    project = await get_project_for_user(db, user, project_id)

    # Delete child rows explicitly (no CASCADE configured at FK level)
    await db.execute(
        ProjectPresentationLink.__table__.delete().where(
            ProjectPresentationLink.project_id == project_id
        )
    )
    await db.execute(
        ProjectDocument.__table__.delete().where(
            ProjectDocument.project_id == project_id
        )
    )
    await db.delete(project)
    await db.commit()
