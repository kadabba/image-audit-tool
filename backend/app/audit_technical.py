"""
Технический аудит изображений: HTTP статус, размер, формат, размеры.
"""

import httpx
from PIL import Image as PILImage
from io import BytesIO


async def check_image_technical(image_url: str) -> dict:
    """
    Проверяет техническое состояние изображения.
    Возвращает: http_status, file_size, format, width, height
    """
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.head(image_url, follow_redirects=True)
            http_status = response.status_code
            file_size = None

            if response.status_code == 200:
                # Получаем размер из заголовка или скачиваем целиком
                content_length = response.headers.get("content-length")
                if content_length:
                    file_size = int(content_length)

                # Скачиваем для определения формата и размеров
                img_response = await client.get(image_url, follow_redirects=True)
                if img_response.status_code == 200:
                    file_size = len(img_response.content)

                    try:
                        pil_img = PILImage.open(BytesIO(img_response.content))
                        return {
                            "http_status": http_status,
                            "file_size": file_size,
                            "format": pil_img.format or "unknown",
                            "width": pil_img.width,
                            "height": pil_img.height,
                        }
                    except Exception:
                        # Не удалось открыть как изображение
                        return {
                            "http_status": http_status,
                            "file_size": file_size,
                            "format": None,
                            "width": None,
                            "height": None,
                        }

            return {
                "http_status": http_status,
                "file_size": file_size,
                "format": None,
                "width": None,
                "height": None,
            }

    except Exception as e:
        print(f"Ошибка при проверке {image_url}: {e}")
        return {
            "http_status": None,
            "file_size": None,
            "format": None,
            "width": None,
            "height": None,
        }
