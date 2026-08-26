"""
Технический аудит изображений: HTTP статус, размер, формат, размеры.
"""

from io import BytesIO

import httpx
from PIL import Image as PILImage

# Тело качаем целиком в память, поэтому потолок обязателен: без него одна
# большая картинка кладёт процесс, а качаются они параллельно пачками.
MAX_IMAGE_BYTES = 20 * 1024 * 1024


async def _download_capped(client: httpx.AsyncClient, url: str):
    """Скачивает тело, обрывая загрузку на превышении лимита."""
    async with client.stream("GET", url, follow_redirects=True) as response:
        if response.status_code != 200:
            return response.status_code, None

        declared = response.headers.get("content-length")
        if declared and int(declared) > MAX_IMAGE_BYTES:
            return response.status_code, None

        chunks = []
        total = 0
        async for chunk in response.aiter_bytes():
            total += len(chunk)
            if total > MAX_IMAGE_BYTES:
                return response.status_code, None
            chunks.append(chunk)
        return response.status_code, b"".join(chunks)


async def check_image_technical(image_url: str) -> dict:
    """
    Проверяет техническое состояние изображения.

    Возвращает http_status, file_size, format, width, height, а в служебном
    ключе `_body` — уже скачанное тело, чтобы copyright-аудит не качал повторно.
    """
    empty = {
        "http_status": None,
        "file_size": None,
        "format": None,
        "width": None,
        "height": None,
        "_body": None,
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            status, body = await _download_capped(client, image_url)

            if body is None:
                return {**empty, "http_status": status}

            result = {
                "http_status": status,
                "file_size": len(body),
                "format": None,
                "width": None,
                "height": None,
                "_body": body,
            }

            try:
                pil_img = PILImage.open(BytesIO(body))
                result["format"] = pil_img.format or "unknown"
                result["width"] = pil_img.width
                result["height"] = pil_img.height
            except Exception:
                pass  # не изображение (SVG и подобное) — размеры остаются пустыми

            return result

    except Exception as e:
        print(f"Ошибка при проверке {image_url}: {e}")
        return empty
