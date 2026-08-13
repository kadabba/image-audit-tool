from fastapi import APIRouter, Depends, Query, HTTPException
from pydantic import BaseModel, field_serializer
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime
from ..db import get_db
from ..models import Image

router = APIRouter()


class ImageResponse(BaseModel):
    id: int
    site_url: str
    image_url: str
    page_url: str
    status: str
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
    ids: List[int]
    status: str


@router.get("")
@router.get("/")
async def get_images(
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    status: Optional[str] = Query(None),
    page_url: Optional[str] = Query(None),
    site_url: Optional[str] = Query(None),
    db: Session = Depends(get_db)
):
    """
    Получить галерею изображений с фильтрами и пагинацией.

    GET /api/images?page=1&limit=50&status=NEW&page_url=...&site_url=...
    """
    query = db.query(Image)

    if site_url:
        query = query.filter(Image.site_url == site_url)
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
    Обновить статус для нескольких изображений.

    POST /api/images/status
    {
        "ids": [1, 2, 3],
        "status": "DELETE"
    }
    """
    if request.status not in ("NEW", "KEEP", "DELETE"):
        raise HTTPException(status_code=400, detail="Статус может быть: NEW, KEEP, DELETE")

    db.query(Image).filter(Image.id.in_(request.ids)).update({Image.status: request.status})
    db.commit()

    return {"updated": len(request.ids)}


@router.get("/{image_id}")
async def get_image(image_id: int, db: Session = Depends(get_db)):
    """Получить детали одного изображения."""
    img = db.query(Image).filter(Image.id == image_id).first()
    if not img:
        raise HTTPException(status_code=404, detail="Изображение не найдено")
    return ImageResponse.from_orm(img)
