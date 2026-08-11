from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from io import StringIO
from ..db import get_db
from ..models import Image

router = APIRouter()


@router.get("/")
async def export_urls(
    status: str = Query("DELETE"),
    db: Session = Depends(get_db)
):
    """
    Экспортировать список URL изображений в .txt формате.

    GET /api/export?status=DELETE

    Возвращает текстовый файл (один URL на строку), совместимый с remove-images.php
    """
    images = db.query(Image).filter(Image.status == status).all()

    # Генерируем текстовый контент
    output = StringIO()
    for img in images:
        output.write(img.image_url + "\n")

    output.seek(0)

    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/plain",
        headers={"Content-Disposition": f"attachment; filename=images-{status.lower()}.txt"}
    )
