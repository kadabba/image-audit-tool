from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from io import StringIO
from ..db import get_db
from ..models import Image
from .scan import get_scan_by_token

router = APIRouter()


@router.get("")
@router.get("/")
async def export_urls(
    scan_token: str = Query(..., description="Токен скана, выданный при запуске"),
    status: str = Query("DELETE"),
    db: Session = Depends(get_db)
):
    """
    Экспортировать список URL изображений в .txt формате.

    GET /api/export?scan_token=...&status=DELETE

    Возвращает текстовый файл (один URL на строку), совместимый с remove-images.php
    """
    scan = get_scan_by_token(scan_token, db)

    urls = (
        db.query(Image.image_url)
        .distinct()
        .filter(Image.status == status, Image.scan_id == scan.id)
        .all()
    )

    output = StringIO()
    for (url,) in urls:
        output.write(url + "\n")

    output.seek(0)

    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/plain",
        headers={"Content-Disposition": f"attachment; filename=images-{status.lower()}.txt"}
    )
