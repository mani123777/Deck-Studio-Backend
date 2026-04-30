from __future__ import annotations

import json
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user
from app.core.database import get_db
from app.core.exceptions import ValidationError
from app.models.user import User
from app.schemas.project import (
    DocumentDetail,
    DocumentListItem,
    DocumentUpdateRequest,
    GenerateFromProjectRequest,
    ProjectCreateRequest,
    ProjectDetail,
    ProjectListItem,
    ProjectPresentationItem,
    ProjectUpdateRequest,
)
from app.services import (
    document_service,
    project_service,
    role_generation_service,
)

router = APIRouter(prefix="/projects", tags=["projects"])


# ── Roles helper (no project context) ────────────────────────────────────────

@router.get("/roles", summary="List supported generation roles")
async def list_roles(_user: User = Depends(get_current_user)) -> list[dict]:
    return await role_generation_service.list_supported_roles()


# ── Project CRUD ─────────────────────────────────────────────────────────────

@router.post(
    "",
    response_model=ProjectListItem,
    status_code=status.HTTP_201_CREATED,
)
async def create_project(
    req: ProjectCreateRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ProjectListItem:
    return await project_service.create_project(db, user, req)


@router.get("", response_model=list[ProjectListItem])
async def list_projects(
    status_filter: Optional[str] = Query(None, alias="status"),
    search: Optional[str] = Query(None),
    sort: str = Query("updated_desc"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[ProjectListItem]:
    return await project_service.list_projects(
        db, user, status=status_filter, search=search, sort=sort
    )


@router.get("/{project_id}", response_model=ProjectDetail)
async def get_project(
    project_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ProjectDetail:
    return await project_service.get_project_detail(db, user, project_id)


@router.patch("/{project_id}", response_model=ProjectListItem)
async def update_project(
    project_id: str,
    req: ProjectUpdateRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ProjectListItem:
    return await project_service.update_project(db, user, project_id, req)


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(
    project_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    await project_service.delete_project(db, user, project_id)


# ── Documents ────────────────────────────────────────────────────────────────

@router.get("/{project_id}/documents", response_model=list[DocumentListItem])
async def list_documents(
    project_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[DocumentListItem]:
    return await document_service.list_documents(db, user, project_id)


@router.post(
    "/{project_id}/documents",
    response_model=DocumentDetail,
    status_code=status.HTTP_201_CREATED,
)
async def upload_document(
    project_id: str,
    file: UploadFile = File(...),
    tags: Optional[str] = Form(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DocumentDetail:
    parsed_tags: Optional[list[str]] = None
    if tags:
        try:
            decoded = json.loads(tags)
            if isinstance(decoded, list):
                parsed_tags = [str(t) for t in decoded]
            else:
                raise ValidationError("'tags' must be a JSON array of strings")
        except json.JSONDecodeError:
            parsed_tags = [t.strip() for t in tags.split(",") if t.strip()]
    return await document_service.upload_document(
        db, user, project_id, file, tags=parsed_tags
    )


@router.get(
    "/{project_id}/documents/{document_id}",
    response_model=DocumentDetail,
)
async def get_document(
    project_id: str,
    document_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DocumentDetail:
    return await document_service.get_document(db, user, project_id, document_id)


@router.patch(
    "/{project_id}/documents/{document_id}",
    response_model=DocumentDetail,
)
async def update_document(
    project_id: str,
    document_id: str,
    req: DocumentUpdateRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DocumentDetail:
    return await document_service.update_document(
        db, user, project_id, document_id, req
    )


@router.delete(
    "/{project_id}/documents/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_document(
    project_id: str,
    document_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    await document_service.delete_document(db, user, project_id, document_id)


@router.post(
    "/{project_id}/documents/{document_id}/retry-extraction",
    response_model=DocumentDetail,
)
async def retry_extraction(
    project_id: str,
    document_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DocumentDetail:
    return await document_service.retry_extraction(db, user, project_id, document_id)


# ── Role-based generation ────────────────────────────────────────────────────

@router.post(
    "/{project_id}/generate",
    response_model=ProjectPresentationItem,
    status_code=status.HTTP_201_CREATED,
    summary="Generate a role-specific presentation from project documents",
)
async def generate_presentation(
    project_id: str,
    req: GenerateFromProjectRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ProjectPresentationItem:
    return await role_generation_service.generate_role_presentation(
        db, user, project_id, req
    )
