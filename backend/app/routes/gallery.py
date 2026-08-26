from fastapi import APIRouter, Depends, Query, HTTPException
from pydantic import BaseModel, field_serializer
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime
from ..db import get_db
from ..models import Image
from .scan import get_scan_by_token

router = APIRouter()


class ImageResponse(BaseModel):
    id: int
    image_url: str
    page_url: str
    status: str
    http_status: Optional[int] = None
    file_size: Optional[int] = None
    format: Optional[str] = None
    created_at: datetime
    last_seen_at: datetime

    @field_serializer('created_at', 'last_seen_at')
    def serialize_datetime(self, value: datetime) -> str:
        return value.isoformat() if value else None

    class Config:
        from_attributes = True


class GalleryResponse(BaseModel):
    items: List[ImageResponse]
    total: int
    page: int
    limit: int
    pages: int


class StatusUpdateRequest(BaseModel):
    scan_token: str
    ids: List[int]
    status: str


@router.get("")
@router.get("/")
async def get_images(
    scan_token: str = Query(..., description="Токен скана, выданный при запуске"),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=10000),
    status: Optional[str] = Query(None),
    page_url: Optional[str] = Query(None),
    db: Session = Depends(get_db)
):
    """
    Получить галерею изображений скана.

    GET /api/images?scan_token=...&page=1&limit=50
    """
    scan = get_scan_by_token(scan_token, db)

    query = db.query(Image).filter(Image.scan_id == scan.id)
    if status:
        query = query.filter(Image.status == status)
    if page_url:
        query = query.filter(Image.page_url.ilike(f"%{page_url}%"))

    total = query.count()
    pages = (total + limit - 1) // limit

    items = query.offset((page - 1) * limit).limit(limit).all()

    return GalleryResponse(
        items=[ImageResponse.from_orm(img) for img in items],
        total=total,
        page=page,
        limit=limit,
        pages=pages
    )


@router.post("/status")
async def update_status(request: StatusUpdateRequest, db: Session = Depends(get_db)):
    """
    Обновить статус изображений внутри своего скана.

    POST /api/images/status
    {
        "scan_token": "...",
        "ids": [1, 2, 3],
        "status": "DELETE"
    }
    """
    if request.status not in ("NEW", "KEEP", "DELETE"):
        raise HTTPException(status_code=400, detail="Статус может быть: NEW, KEEP, DELETE")

    scan = get_scan_by_token(request.scan_token, db)

    # Ограничиваем скан-ом из токена: иначе чужие записи правятся по номеру id
    updated = db.query(Image).filter(
        Image.id.in_(request.ids),
        Image.scan_id == scan.id,
    ).update({Image.status: request.status}, synchronize_session=False)
    db.commit()

    return {"updated": updated}
