"""
Copyright аудит: парсинг EXIF и расчет риска авторского права.
"""

import io
from PIL import Image as PILImage
from PIL.ExifTags import TAGS
import httpx


async def analyze_copyright_risk(image_url: str, image_data: bytes = None) -> dict:
    """
    Анализирует EXIF данные и рассчитывает риск авторского права.

    Возвращает:
    {
        "copyright_score": "low" | "medium" | "high",
        "exif_data": {Artist, Copyright, Software, ...},
        "risk_details": {reason: "...", confidence: 0-100}
    }
    """
    exif_data = {}
    copyright_score = "low"
    risk_details = {"reason": "No EXIF data found", "confidence": 0}

    try:
        # Если image_data не передана, скачиваем
        if not image_data:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(image_url, follow_redirects=True)
                if response.status_code != 200:
                    return {
                        "copyright_score": copyright_score,
                        "exif_data": exif_data,
                        "risk_details": {"reason": f"Failed to fetch image: {response.status_code}", "confidence": 0}
                    }
                image_data = response.content

        # Парсим EXIF
        try:
            pil_img = PILImage.open(io.BytesIO(image_data))
            exif_raw = pil_img._getexif() if hasattr(pil_img, '_getexif') else None

            if exif_raw:
                for tag_id, value in exif_raw.items():
                    tag_name = TAGS.get(tag_id, tag_id)
                    # Сохраняем только текстовые поля до 500 символов
                    if isinstance(value, (str, bytes)):
                        try:
                            exif_data[tag_name] = value[:500] if isinstance(value, (str, bytes)) else str(value)[:500]
                        except:
                            pass
        except Exception as e:
            print(f"EXIF parse error for {image_url}: {e}")

        # Рассчитываем риск
        copyright_score, risk_details = _calculate_risk(exif_data)

    except Exception as e:
        print(f"Copyright audit error for {image_url}: {e}")
        risk_details = {"reason": f"Analysis error: {str(e)}", "confidence": 0}

    return {
        "copyright_score": copyright_score,
        "exif_data": exif_data if exif_data else None,
        "risk_details": risk_details
    }


def _calculate_risk(exif_data: dict) -> tuple:
    """Рассчитывает риск на основе EXIF данных."""

    copyright_score = "low"
    risk_details = {"reason": "No copyright indicators found", "confidence": 0}

    if not exif_data:
        return copyright_score, risk_details

    artist = exif_data.get("Artist", "").strip().lower()
    copyright_field = exif_data.get("Copyright", "").strip().lower()
    software = exif_data.get("Software", "").strip().lower()

    # Признаки HIGH риска
    high_risk_keywords = ["stock", "getty", "shutterstock", "123rf", "deposit", "alamy", "istockphoto"]

    if copyright_field:
        # Есть явное поле Copyright
        if any(keyword in copyright_field for keyword in high_risk_keywords):
            copyright_score = "high"
            risk_details = {
                "reason": f"Stock/commercial license detected: {copyright_field[:100]}",
                "confidence": 95
            }
        elif "©" in copyright_field or "copyright" in copyright_field or "reserved" in copyright_field:
            copyright_score = "medium"
            risk_details = {
                "reason": f"Copyright notice present but unclear origin",
                "confidence": 60
            }
        else:
            copyright_score = "low"
            risk_details = {
                "reason": f"Copyright field present: {copyright_field[:50]}",
                "confidence": 20
            }
    elif artist and len(artist) > 2:
        # Есть Artist но нет Copyright
        copyright_score = "medium"
        risk_details = {
            "reason": f"Artist field present but no copyright notice: {artist[:50]}",
            "confidence": 50
        }
    else:
        # Нет никаких данных об авторе
        copyright_score = "low"
        risk_details = {
            "reason": "No artist or copyright metadata",
            "confidence": 30
        }

    return copyright_score, risk_details
