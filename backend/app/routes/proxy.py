from fastapi import APIRouter, Query, HTTPException
from fastapi.responses import StreamingResponse
import requests

router = APIRouter()


@router.get("/image")
async def proxy_image(url: str = Query(...)):
    """
    Прокси для загрузки изображений.

    GET /api/proxy-image?url=https://example.com/image.jpg

    Используется для обхода CORS и блокировок хотлинкинга.
    """
    if not url.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="URL должен начинаться с http(s)://")

    try:
        # Загружаем с таймаутом и ограничением размера
        response = requests.get(
            url,
            timeout=10,
            headers={"User-Agent": "Mozilla/5.0 (compatible; ImageAuditBot/1.0)"},
            stream=True
        )
        response.raise_for_status()

        # Ограничиваем размер (10 МБ максимум)
        content_length = response.headers.get("content-length")
        if content_length and int(content_length) > 10 * 1024 * 1024:
            raise HTTPException(status_code=413, detail="Файл слишком большой")

        # Возвращаем контент с оригинальным Content-Type
        return StreamingResponse(
            response.iter_content(chunk_size=8192),
            media_type=response.headers.get("content-type", "image/jpeg")
        )
    except requests.RequestException as e:
        raise HTTPException(status_code=502, detail=f"Не удалось загрузить изображение: {str(e)}")
