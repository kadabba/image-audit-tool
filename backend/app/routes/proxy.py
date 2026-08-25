from fastapi import APIRouter, Query, HTTPException
from fastapi.responses import StreamingResponse
from urllib.parse import urljoin
import requests

from ..net_guard import check_public_url

router = APIRouter()

MAX_REDIRECTS = 3


@router.get("/image")
async def proxy_image(url: str = Query(...)):
    """
    Прокси для загрузки изображений.

    GET /api/image?url=https://example.com/image.jpg

    Используется для обхода CORS и блокировок хотлинкинга.
    Каждый хоп проверяется на SSRF: редирект на внутренний адрес отклоняется.
    """
    try:
        for _ in range(MAX_REDIRECTS + 1):
            check_public_url(url)
            response = requests.get(
                url,
                timeout=10,
                headers={"User-Agent": "Mozilla/5.0 (compatible; ImageAuditBot/1.0)"},
                stream=True,
                allow_redirects=False,
            )
            location = response.headers.get("location")
            if response.is_redirect and location:
                response.close()
                url = urljoin(url, location)
                continue
            break
        else:
            raise HTTPException(status_code=502, detail="Слишком много редиректов")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except requests.RequestException as e:
        raise HTTPException(status_code=502, detail=f"Не удалось загрузить изображение: {str(e)}")

    try:
        response.raise_for_status()
    except requests.RequestException as e:
        response.close()
        raise HTTPException(status_code=502, detail=f"Не удалось загрузить изображение: {str(e)}")

    content_type = response.headers.get("content-type", "")
    if not content_type.startswith("image/"):
        response.close()
        raise HTTPException(status_code=415, detail="По ссылке не изображение")

    content_length = response.headers.get("content-length")
    if content_length and int(content_length) > 10 * 1024 * 1024:
        response.close()
        raise HTTPException(status_code=413, detail="Файл слишком большой")

    return StreamingResponse(
        response.iter_content(chunk_size=8192),
        media_type=content_type,
    )
