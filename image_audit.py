#!/usr/bin/env python3
"""
Собирает все изображения со всех страниц сайта (по sitemap.xml)
и генерирует HTML-галерею для визуального ревью.

Запуск:
    pip install requests beautifulsoup4 --break-system-packages
    python3 image_audit.py https://promtakelag.ru

Результат: image_audit_report.html — открой в браузере.
"""

import sys
import time
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
import xml.etree.ElementTree as ET

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
    """Запасной вариант: обходит сайт по внутренним ссылкам с главной страницы,
    если sitemap.xml не найден или пуст."""
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
                # пропускаем файлы (картинки, pdf, и т.п.), оставляем только html-страницы
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

    # picture > source srcset (webp и т.п.)
    for source in soup.find_all("source"):
        srcset = source.get("srcset")
        if srcset:
            first = srcset.split(",")[0].strip().split(" ")[0]
            if first:
                images.add(urljoin(page_url, first))

    # фоновые картинки: style="background-image:url(...)"
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


def main():
    if len(sys.argv) < 2:
        print("Использование: python3 image_audit.py https://example.com")
        sys.exit(1)

    base_url = sys.argv[1].rstrip("/")
    print(f"Ищу sitemap для {base_url} ...")
    pages = get_sitemap_urls(base_url)

    if not pages:
        print("Sitemap не найден или пуст. Обхожу сайт по внутренним ссылкам (макс. 100 страниц)...")
        pages = crawl_internal_links(base_url, max_pages=100)

    print(f"Найдено страниц: {len(pages)}")

    image_to_pages = {}  # image_url -> [page_url, page_url, ...]

    for i, page in enumerate(pages, 1):
        print(f"[{i}/{len(pages)}] {page}")
        imgs = extract_images(page)
        for img_url in imgs:
            image_to_pages.setdefault(img_url, []).append(page)
        time.sleep(0.3)  # не долбим сервер слишком часто

    print(f"\nВсего уникальных изображений: {len(image_to_pages)}")

    # Генерация HTML-отчёта
    rows = []
    for img_url in sorted(image_to_pages.keys()):
        pages_list = image_to_pages[img_url]
        pages_html = "<br>".join(
            f'<a href="{p}" target="_blank">{p}</a>' for p in pages_list
        )
        rows.append(f"""
        <div class="card">
            <img src="{img_url}" loading="lazy" onerror="this.parentElement.classList.add('broken')">
            <div class="meta">
                <div class="url"><a href="{img_url}" target="_blank">{img_url}</a></div>
                <div class="pages"><strong>Страницы ({len(pages_list)}):</strong><br>{pages_html}</div>
            </div>
        </div>
        """)

    html = f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<title>Аудит изображений — {base_url}</title>
<style>
    body {{ font-family: -apple-system, Arial, sans-serif; background:#f4f4f5; margin:0; padding:24px; }}
    h1 {{ font-size:20px; }}
    .stats {{ margin-bottom:20px; color:#555; }}
    .grid {{ display:grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap:16px; }}
    .card {{ background:#fff; border-radius:8px; overflow:hidden; box-shadow:0 1px 4px rgba(0,0,0,0.1); }}
    .card img {{ width:100%; height:180px; object-fit:cover; display:block; background:#eee; }}
    .card.broken {{ border:2px solid #e11d48; }}
    .card.broken img {{ display:none; }}
    .card.broken::before {{ content:"⚠ Не загрузилось"; display:block; padding:16px; color:#e11d48; font-weight:bold; }}
    .meta {{ padding:10px 12px; font-size:12px; word-break:break-all; }}
    .meta .url {{ margin-bottom:6px; }}
    .meta a {{ color:#0369a1; text-decoration:none; }}
    .meta a:hover {{ text-decoration:underline; }}
</style>
</head>
<body>
    <h1>Аудит изображений сайта {base_url}</h1>
    <div class="stats">Страниц просканировано: {len(pages)} · Уникальных изображений: {len(image_to_pages)}</div>
    <div class="grid">
        {''.join(rows)}
    </div>
</body>
</html>
"""

    domain = urlparse(base_url).netloc.replace(":", "_")
    report_filename = f"image_audit_{domain}.html"

    with open(report_filename, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"\nГотово. Открой {report_filename} в браузере.")


if __name__ == "__main__":
    main()
