"""
Сканер сайтов: собирает все изображения и сохраняет в PostgreSQL с аудитом.
"""

import asyncio
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
import xml.etree.ElementTree as ET
from sqlalchemy.orm import Session
from .models import Image, Scan
from datetime import datetime
from .audit_technical import check_image_technical
from .audit_seo import extract_image_attributes
from .audit_copyright import analyze_copyright_risk
import httpx

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; ImageAuditBot/1.0)"}


def get_sitemap_urls(base_url):
    """Пытается найти sitemap.xml (в т.ч. sitemap index) и собрать все URL страниц."""
    candidates = [
        urljoin(base_url, "/sitemap.xml"),
        urljoin(base_url, "/sitemap_index.xml"),
    ]
    urls = set()
    for sitemap_url in candidates:
        try:
            r = requests.get(sitemap_url, headers=HEADERS, timeout=15)
            if r.status_code != 200:
                continue
            root = ET.fromstring(r.content)
            ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
            # Если это sitemap index — там <sitemap><loc>
            sub_sitemaps = [el.text for el in root.findall(".//sm:sitemap/sm:loc", ns)]
            if sub_sitemaps:
                for sm in sub_sitemaps:
                    try:
                        rr = requests.get(sm, headers=HEADERS, timeout=15)
                        sroot = ET.fromstring(rr.content)
                        for loc in sroot.findall(".//sm:url/sm:loc", ns):
                            urls.add(loc.text.strip())
                    except Exception as e:
                        print(f"  ! Не удалось прочитать вложенный sitemap {sm}: {e}")
            else:
                for loc in root.findall(".//sm:url/sm:loc", ns):
                    urls.add(loc.text.strip())
            if urls:
                break
        except Exception as e:
            print(f"  ! Не удалось прочитать {sitemap_url}: {e}")
    return sorted(urls)


def crawl_internal_links(base_url, max_pages=100):
    """Обходит сайт по внутренним ссылкам с главной страницы, если sitemap не найден."""
    domain = urlparse(base_url).netloc
    visited = set()
    to_visit = [base_url + "/"]

    while to_visit and len(visited) < max_pages:
        url = to_visit.pop(0)
        if url in visited:
            continue
        try:
            r = requests.get(url, headers=HEADERS, timeout=15)
            if r.status_code != 200:
                continue
        except Exception:
            continue

        visited.add(url)
        soup = BeautifulSoup(r.text, "html.parser")
        for a in soup.find_all("a", href=True):
            link = urljoin(url, a["href"]).split("#")[0]
            parsed = urlparse(link)
            if parsed.netloc == domain and link not in visited and link not in to_visit:
                # пропускаем файлы, оставляем только html-страницы
                if not any(link.lower().endswith(ext) for ext in
                           (".jpg", ".jpeg", ".png", ".webp", ".pdf", ".svg", ".gif", ".zip", ".doc", ".docx")):
                    to_visit.append(link)

    return sorted(visited)


def extract_images(page_url):
    """Возвращает список абсолютных URL картинок на странице."""
    try:
        r = requests.get(page_url, headers=HEADERS, timeout=15)
        if r.status_code != 200:
            print(f"  ! {page_url} -> статус {r.status_code}")
            return []
    except Exception as e:
        print(f"  ! Ошибка загрузки {page_url}: {e}")
        return []

    soup = BeautifulSoup(r.text, "html.parser")
    images = set()

    for img in soup.find_all("img"):
        for attr in ("src", "data-src", "data-original"):
            val = img.get(attr)
            if val:
                images.add(urljoin(page_url, val))

    # picture > source srcset
    for source in soup.find_all("source"):
        srcset = source.get("srcset")
        if srcset:
            first = srcset.split(",")[0].strip().split(" ")[0]
            if first:
                images.add(urljoin(page_url, first))

    # background-image
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


async def extract_images_async(page_url):
    """Асинхронная версия для параллельной загрузки нескольких страниц."""
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.get(page_url, follow_redirects=True)
            if r.status_code != 200:
                return []
    except Exception:
        return []

    soup = BeautifulSoup(r.text, "html.parser")
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


async def scan_site_async(db: Session, scan_id: int, site_url: str, enable_seo: bool = False):
    """
    Асинхронное сканирование сайта с техническим аудитом.
    SEO парсинг отключен по умолчанию для скорости (498 страниц → 5-10 мин вместо 60+).
    """
    site_url = site_url.rstrip("/")

    print(f"Ищу sitemap для {site_url} ...")
    pages = get_sitemap_urls(site_url)

    if not pages:
        print("Sitemap не найден или пуст. Обхожу сайт по внутренним ссылкам (макс. 100 страниц)...")
        pages = crawl_internal_links(site_url, max_pages=100)

    print(f"Найдено страниц: {len(pages)} (SEO: {'ON' if enable_seo else 'OFF'})")

    # Обновляем scan с количеством страниц и временем начала
    scan = db.query(Scan).filter(Scan.id == scan_id).first()
    if scan:
        scan.total_pages = len(pages)
        scan.started_at = datetime.utcnow()
        db.commit()

    count = 0

    async def audit_image(img_url: str):
        """Аудит одного изображения - техника + авторские права (SEO опционально)"""
        tech_data = await check_image_technical(img_url)
        seo_data = await extract_image_attributes(page, img_url) if enable_seo else {}
        copyright_data = await analyze_copyright_risk(img_url)
        return {
            'img_url': img_url,
            'tech_data': tech_data,
            'seo_data': seo_data,
            'copyright_data': copyright_data
        }

    # ponytail: параллельная обработка страниц батчами, если нужна max скорость
    async def process_page(page_idx_tuple):
        """Обработать одну страницу: загрузить изображения и их аудит"""
        i, page = page_idx_tuple
        try:
            imgs = await extract_images_async(page)
            if not imgs:
                return i, []

            # Параллельно обрабатываем все изображения на странице
            tasks = [audit_image(img_url) for img_url in imgs]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            page_images = []
            for result in results:
                if isinstance(result, Exception):
                    continue

                img_url = result['img_url']
                tech_data = result['tech_data']
                seo_data = result['seo_data']
                copyright_data = result['copyright_data']

                page_images.append({
                    'url': img_url,
                    'tech': tech_data,
                    'seo': seo_data,
                    'copyright': copyright_data
                })

            return i, page_images
        except Exception as e:
            print(f"  ✗ Ошибка при обработке {page}: {e}")
            return i, []

    # Обрабатываем страницы батчами по 5 одновременно (избегаем перегрузки сети)
    batch_size = 5
    for batch_start in range(0, len(pages), batch_size):
        batch = list(enumerate(pages[batch_start:batch_start+batch_size], batch_start+1))
        results = await asyncio.gather(*[process_page(item) for item in batch], return_exceptions=True)

        for result in results:
            if isinstance(result, Exception):
                continue
            i, page_images = result
            page = pages[i-1]

            for img_data in page_images:
                new_img = Image(
                    scan_id=scan_id,
                    image_url=img_data['url'],
                    page_url=page,
                    status="NEW",
                    http_status=img_data['tech'].get("http_status"),
                    file_size=img_data['tech'].get("file_size"),
                    format=img_data['tech'].get("format"),
                    width=img_data['tech'].get("width"),
                    height=img_data['tech'].get("height"),
                    alt_text=img_data['seo'].get("alt_text"),
                    title_text=img_data['seo'].get("title_text"),
                    exif_data=img_data['copyright'].get("exif_data"),
                    copyright_score=img_data['copyright'].get("copyright_score"),
                    risk_details=img_data['copyright'].get("risk_details"),
                    created_at=datetime.utcnow(),
                    last_seen_at=datetime.utcnow()
                )
                db.add(new_img)
                count += 1

            print(f"[{i}/{len(pages)}] {page} → {len(page_images)} изображений")

        # Обновляем прогресс после каждого батча
        scan = db.query(Scan).filter(Scan.id == scan_id).first()
        if scan:
            scan.scanned_pages = min(batch_start + batch_size, len(pages))
            db.commit()

    print(f"\nКоммитим {count} изображений...")
    db.commit()
    print(f"Всего найдено и сохранено: {count}")
    return {"count": count}
