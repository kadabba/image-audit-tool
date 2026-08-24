"""
SEO аудит изображений: проверка alt и title атрибутов.
"""

from bs4 import BeautifulSoup
import httpx


async def extract_image_attributes(page_url: str, image_url: str) -> dict:
    """
    Извлекает alt и title атрибуты для конкретного изображения на странице.
    """
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(page_url, follow_redirects=True)
            if response.status_code != 200:
                return {"alt_text": None, "title_text": None}

        soup = BeautifulSoup(response.text, "html.parser")

        # Ищем img теги с нашим URL
        for img in soup.find_all("img"):
            for attr in ("src", "data-src", "data-original"):
                img_src = img.get(attr)
                if img_src and image_url in img_src:
                    alt = img.get("alt")
                    title = img.get("title")
                    return {
                        "alt_text": alt if alt and alt.strip() else None,
                        "title_text": title if title and title.strip() else None,
                    }

        return {"alt_text": None, "title_text": None}

    except Exception as e:
        print(f"Ошибка при извлечении атрибутов для {page_url}: {e}")
        return {"alt_text": None, "title_text": None}
