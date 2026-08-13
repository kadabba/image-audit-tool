"""
Сканер сайтов: собирает все изображения и сохраняет в SQLite.
"""

import time
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
import xml.etree.ElementTree as ET
from sqlalchemy.orm import Session
from .models import Image
from datetime import datetime

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
        time.sleep(0.2)

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


def scan_site(db: Session, site_url: str):
    """
    Сканирует сайт и сохраняет изображения в БД.
    Очищает старые данные для этого сайта перед сканированием.
    Возвращает количество найденных изображений.
    """
    site_url = site_url.rstrip("/")

    # Очищаем старые данные для этого сайта
    print(f"Удаляю старые данные для {site_url}...")
    db.query(Image).filter(Image.site_url == site_url).delete()
    db.commit()

    print(f"Ищу sitemap для {site_url} ...")
    pages = get_sitemap_urls(site_url)

    if not pages:
        print("Sitemap не найден или пуст. Обхожу сайт по внутренним ссылкам (макс. 100 страниц)...")
        pages = crawl_internal_links(site_url, max_pages=100)

    print(f"Найдено страниц: {len(pages)}")

    count = 0

    for i, page in enumerate(pages, 1):
        print(f"[{i}/{len(pages)}] {page}")
        imgs = extract_images(page)

        for img_url in imgs:
            new_img = Image(
                site_url=site_url,
                image_url=img_url,
                page_url=page,
                status="NEW",
                created_at=datetime.utcnow(),
                last_seen_at=datetime.utcnow()
            )
            db.add(new_img)
            count += 1

        time.sleep(0.3)  # не долбим сервер

    db.commit()
    print(f"\nВсего найдено: {count}")
    return {"count": count}
