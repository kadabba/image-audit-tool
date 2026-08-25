from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from io import StringIO
from ..db import get_db
from ..models import Image, Scan

router = APIRouter()


@router.get("/")
async def export_urls(
    status: str = Query("DELETE"),
    scan_id: int = Query(None),
    db: Session = Depends(get_db)
):
    """
    Экспортировать список URL изображений в .txt формате.

    GET /api/export?status=DELETE&scan_id=1

    Возвращает текстовый файл (один URL на строку), совместимый с remove-images.php
    """
    # Если не указан scan_id, используем последний скан
    if not scan_id:
        last_scan = db.query(Scan).order_by(Scan.id.desc()).first()
        if last_scan:
            scan_id = last_scan.id

    query = db.query(Image.image_url).distinct().filter(Image.status == status)
    if scan_id:
        query = query.filter(Image.scan_id == scan_id)

    urls = query.all()

    # Генерируем текстовый контент
    output = StringIO()
    for (url,) in urls:
        output.write(url + "\n")

    output.seek(0)

    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/plain",
        headers={"Content-Disposition": f"attachment; filename=images-{status.lower()}.txt"}
    )
