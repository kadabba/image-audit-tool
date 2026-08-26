"""
Сканер сайтов: собирает все изображения и сохраняет в PostgreSQL с аудитом.
"""

import asyncio
import xml.etree.ElementTree as ET
from datetime import datetime
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup
from sqlalchemy import func
from sqlalchemy.orm import Session

from .audit_copyright import analyze_copyright_risk
from .audit_technical import check_image_technical
from .models import Image, Scan
from .net_guard import check_public_url

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; ImageAuditBot/1.0)"}

PAGE_TIMEOUT = 15.0
MAX_SITEMAP_BYTES = 10 * 1024 * 1024
BATCH_SIZE = 5


def _is_scannable(url: str) -> bool:
    """Пускаем только публичные http(s)-адреса: sitemap и ссылки приходят извне."""
    try:
        check_public_url(url)
        return True
    except ValueError:
        return False


def _parse_sitemap(content: bytes):
    """
    Разбирает sitemap. Отклоняет объявления сущностей: ElementTree их раскрывает,
    и вложенные сущности («billion laughs») выжирают память.
    """
    if len(content) > MAX_SITEMAP_BYTES:
        raise ValueError("sitemap слишком большой")
    if b"<!ENTITY" in content or b"<!DOCTYPE" in content:
        raise ValueError("sitemap содержит объявления DTD или сущностей")
    return ET.fromstring(content)


async def get_sitemap_urls(base_url: str) -> list:
    """Ищет sitemap.xml (в т.ч. sitemap index) и собирает URL страниц."""
    ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    urls = set()

    async with httpx.AsyncClient(timeout=PAGE_TIMEOUT, headers=HEADERS, follow_redirects=True) as client:
        for name in ("/sitemap.xml", "/sitemap_index.xml"):
            sitemap_url = urljoin(base_url, name)
            try:
                r = await client.get(sitemap_url)
                if r.status_code != 200:
                    continue
                root = _parse_sitemap(r.content)

                sub = [el.text for el in root.findall(".//sm:sitemap/sm:loc", ns) if el.text]
                if sub:
                    for sm in sub:
                        if not _is_scannable(sm):
                            continue
                        try:
                            rr = await client.get(sm)
                            for loc in _parse_sitemap(rr.content).findall(".//sm:url/sm:loc", ns):
                                if loc.text:
                                    urls.add(loc.text.strip())
                        except Exception as e:
                            print(f"  ! Не удалось прочитать вложенный sitemap {sm}: {e}")
                else:
                    for loc in root.findall(".//sm:url/sm:loc", ns):
                        if loc.text:
                            urls.add(loc.text.strip())
                if urls:
                    break
            except Exception as e:
                print(f"  ! Не удалось прочитать {sitemap_url}: {e}")

    return sorted(u for u in urls if _is_scannable(u))


async def crawl_internal_links(base_url: str, max_pages: int = 100) -> list:
    """Обходит сайт по внутренним ссылкам, если sitemap не найден."""
    domain = urlparse(base_url).netloc
    visited = set()
    to_visit = [base_url + "/"]
    skip_ext = (".jpg", ".jpeg", ".png", ".webp", ".pdf", ".svg", ".gif", ".zip", ".doc", ".docx")

    async with httpx.AsyncClient(timeout=PAGE_TIMEOUT, headers=HEADERS, follow_redirects=True) as client:
        while to_visit and len(visited) < max_pages:
            url = to_visit.pop(0)
            if url in visited or not _is_scannable(url):
                continue
            try:
                r = await client.get(url)
                if r.status_code != 200:
                    continue
            except Exception:
                continue

            visited.add(url)
            for a in BeautifulSoup(r.text, "html.parser").find_all("a", href=True):
                link = urljoin(url, a["href"]).split("#")[0]
                if urlparse(link).netloc != domain:
                    continue
                if link in visited or link in to_visit:
                    continue
                if not any(link.lower().endswith(ext) for ext in skip_ext):
                    to_visit.append(link)

    return sorted(visited)


def _images_from_html(page_url: str, html: str) -> list:
    """Достаёт абсолютные URL картинок из HTML страницы."""
    soup = BeautifulSoup(html, "html.parser")
    images = set()

    for img in soup.find_all("img"):
        for attr in ("src", "data-src", "data-original"):
            val = img.get(attr)
            if val:
                images.add(urljoin(page_url, val))

    for source in soup.find_all("source"):
        srcset = source.get("srcset")
        if srcset:
            first = srcset.split(",")[0].strip().split(" ")[0]
            if first:
                images.add(urljoin(page_url, first))

    for el in soup.find_all(style=True):
        style = el["style"]
        if "background-image" in style and "url(" in style:
            try:
                url_part = style.split("url(")[1].split(")")[0].strip("'\" ")
                if url_part:
                    images.add(urljoin(page_url, url_part))
            except IndexError:
                pass

    return sorted(images)


async def extract_images_async(page_url: str) -> list:
    """Загружает страницу и возвращает найденные на ней картинки."""
    try:
        async with httpx.AsyncClient(timeout=PAGE_TIMEOUT, headers=HEADERS, follow_redirects=True) as client:
            r = await client.get(page_url)
            if r.status_code != 200:
                return []
    except Exception:
        return []

    return _images_from_html(page_url, r.text)


async def audit_image(img_url: str) -> dict:
    """Технический аудит + авторские права. Тело картинки скачивается один раз."""
    tech_data = await check_image_technical(img_url)
    body = tech_data.pop("_body", None)
    copyright_data = await analyze_copyright_risk(img_url, image_data=body)
    return {"url": img_url, "tech": tech_data, "copyright": copyright_data}


async def scan_site_async(db: Session, scan_id: int, site_url: str):
    """Асинхронное сканирование сайта с техническим и copyright-аудитом."""
    site_url = site_url.rstrip("/")

    print(f"Ищу sitemap для {site_url} ...")
    pages = await get_sitemap_urls(site_url)

    if not pages:
        print("Sitemap не найден или пуст. Обхожу сайт по внутренним ссылкам (макс. 100 страниц)...")
        pages = await crawl_internal_links(site_url, max_pages=100)

    print(f"Найдено страниц: {len(pages)}")

    scan = db.query(Scan).filter(Scan.id == scan_id).first()
    if scan:
        scan.total_pages = len(pages)
        scan.started_at = datetime.utcnow()
        db.commit()

    count = 0

    async def process_page(page: str):
        try:
            imgs = [u for u in await extract_images_async(page) if _is_scannable(u)]
            if not imgs:
                return page, []
            results = await asyncio.gather(*(audit_image(u) for u in imgs), return_exceptions=True)
            return page, [r for r in results if not isinstance(r, BaseException)]
        except Exception as e:
            print(f"  ✗ Ошибка при обработке {page}: {e}")
            return page, []

    for start in range(0, len(pages), BATCH_SIZE):
        batch = pages[start:start + BATCH_SIZE]
        results = await asyncio.gather(*(process_page(p) for p in batch), return_exceptions=True)

        for result in results:
            if isinstance(result, BaseException):
                continue
            page, page_images = result

            for img in page_images:
                db.add(Image(
                    scan_id=scan_id,
                    image_url=img["url"],
                    page_url=page,
                    status="NEW",
                    http_status=img["tech"].get("http_status"),
                    file_size=img["tech"].get("file_size"),
                    format=img["tech"].get("format"),
                    width=img["tech"].get("width"),
                    height=img["tech"].get("height"),
                    exif_data=img["copyright"].get("exif_data"),
                    copyright_score=img["copyright"].get("copyright_score"),
                    risk_details=img["copyright"].get("risk_details"),
                    created_at=datetime.utcnow(),
                    last_seen_at=datetime.utcnow(),
                ))
                count += 1

            done = min(start + BATCH_SIZE, len(pages))
            print(f"[{done}/{len(pages)}] {page} → {len(page_images)} изображений")

        scan = db.query(Scan).filter(Scan.id == scan_id).first()
        if scan:
            scan.scanned_pages = min(start + BATCH_SIZE, len(pages))
        db.commit()

    # Считаем уникальные картинки: строка заводится на каждое размещение,
    # а в галерее сквозной логотип — одна карточка, а не сотня.
    unique = (
        db.query(func.count(func.distinct(Image.image_url)))
        .filter(Image.scan_id == scan_id)
        .scalar()
    ) or 0

    print(f"Найдено {unique} уникальных картинок ({count} размещений)")
    return {"count": count, "unique": unique}


def demo():
    """Самопроверка разбора и фильтрации. Запуск: python -m app.scanner"""
    # sitemap: бомбы и переростки отклоняются, нормальный разбирается
    for bad, why in [
        (b'<!DOCTYPE l [<!ENTITY a "AA">]><r>&a;</r>', "сущности"),
        (b"x" * (MAX_SITEMAP_BYTES + 1), "размер"),
    ]:
        try:
            _parse_sitemap(bad)
            raise AssertionError(f"должен был отклонить: {why}")
        except ValueError:
            pass

    ok = (b'<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
          b"<url><loc>https://a.test/</loc></url></urlset>")
    assert _parse_sitemap(ok).tag.endswith("urlset")

    # внутренняя сеть недоступна, даже если адрес пришёл со сканируемого сайта
    for internal in ("http://127.0.0.1:8000/", "http://169.254.169.254/", "http://10.0.0.1/"):
        assert not _is_scannable(internal), internal
    assert _is_scannable("https://example.com/img.png")

    # картинки достаются из src, srcset и inline-фона
    html = ('<img src="/a.png"><img data-src="/b.png">'
            '<picture><source srcset="/c.webp 1x, /d.webp 2x"></picture>'
            '<div style="background-image: url(\'/e.jpg\')"></div>')
    found = _images_from_html("https://s.test/page", html)
    assert found == [
        "https://s.test/a.png", "https://s.test/b.png",
        "https://s.test/c.webp", "https://s.test/e.jpg",
    ], found

    print("scanner: ok")


if __name__ == "__main__":
    demo()
