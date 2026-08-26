from fastapi import APIRouter, Depends, Query, HTTPException
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session
from typing import Any, List, Optional
from ..db import get_db
from ..models import Image
from .scan import get_scan_by_token

router = APIRouter()


# Сквозная картинка встречается на сотнях страниц. Полный список нечитаем
# и занимает 80% ответа, поэтому отдаём первые несколько плюс общее число.
PAGES_PREVIEW = 20


class ImageGroup(BaseModel):
    """Одна картинка со списком страниц, где она встречается."""
    image_url: str
    pages: List[str]
    pages_total: int
    status: str
    http_status: Optional[int] = None
    file_size: Optional[int] = None
    format: Optional[str] = None
    copyright_score: Optional[str] = None
    risk_details: Optional[Any] = None


class GalleryResponse(BaseModel):
    items: List[ImageGroup]
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
    limit: int = Query(200, ge=1, le=1000),
    status: Optional[str] = Query(None),
    db: Session = Depends(get_db)
):
    """
    Галерея скана: по записи на уникальную картинку, а не на каждое размещение.

    GET /api/images?scan_token=...&page=1&limit=200

    Группировка живёт на сервере: сквозная картинка занимает одну строку
    ответа вместо сотни, и ответ становится в десятки раз легче.
    """
    scan = get_scan_by_token(scan_token, db)

    base = db.query(Image).filter(Image.scan_id == scan.id)
    if status:
        base = base.filter(Image.status == status)

    total = base.with_entities(func.count(func.distinct(Image.image_url))).scalar() or 0

    # Атрибуты одинаковы у всех строк одной картинки, поэтому берём первый элемент
    rows = (
        base.with_entities(
            Image.image_url,
            func.array_agg(func.distinct(Image.page_url)).label("pages"),
            func.array_agg(Image.status)[1].label("status"),
            func.array_agg(Image.http_status)[1].label("http_status"),
            func.array_agg(Image.file_size)[1].label("file_size"),
            func.array_agg(Image.format)[1].label("format"),
            func.array_agg(Image.copyright_score)[1].label("copyright_score"),
            func.array_agg(Image.risk_details)[1].label("risk_details"),
        )
        .group_by(Image.image_url)
        .order_by(Image.image_url)
        .offset((page - 1) * limit)
        .limit(limit)
        .all()
    )

    items = [
        ImageGroup(
            image_url=r.image_url,
            pages=sorted(r.pages)[:PAGES_PREVIEW],
            pages_total=len(r.pages),
            status=r.status,
            http_status=r.http_status,
            file_size=r.file_size,
            format=r.format,
            copyright_score=r.copyright_score.value if hasattr(r.copyright_score, "value") else r.copyright_score,
            risk_details=r.risk_details,
        )
        for r in rows
    ]

    return GalleryResponse(
        items=items,
        total=total,
        page=page,
        limit=limit,
        pages=(total + limit - 1) // limit,
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

    # Ограничиваем сканом из токена: иначе чужие записи правятся по номеру id
    updated = db.query(Image).filter(
        Image.id.in_(request.ids),
        Image.scan_id == scan.id,
    ).update({Image.status: request.status}, synchronize_session=False)
    db.commit()

    return {"updated": updated}
