const API_BASE = "/api";
let currentPage = 1;
const PAGE_SIZE = 50;
let selectedIds = new Set();
let allImages = [];
let currentSiteUrl = "";
let currentScanId = null;
let scanPollTimeout = null;
let filters = {
    status: "",
    page: ""
};

// Загружаем последний скан при загрузке страницы
window.addEventListener('load', async () => {
    let lastScanId = localStorage.getItem('lastScanId');
    console.log('Page loaded, lastScanId from storage:', lastScanId);

    if (!lastScanId) {
        // Fallback: загружаем последний скан из БД через API
        try {
            const response = await fetch(`${API_BASE}/images?limit=1`);
            if (response.ok) {
                const data = await response.json();
                if (data.items && data.items.length > 0) {
                    lastScanId = data.items[0].scan_id;
                    console.log('Loaded lastScanId from API:', lastScanId);
                }
            }
        } catch (e) {
            console.log('Failed to load from API:', e);
        }
    }

    if (lastScanId) {
        currentScanId = parseInt(lastScanId);
        console.log('Loading gallery for scan:', currentScanId);
        loadGallery();
    } else {
        console.log('No scan found');
    }
});

let scanStartTime = null;

async function pollScanStatus(scanId) {
    try {
        const response = await fetch(`${API_BASE}/scan/${scanId}`, {
            method: "GET"
        });

        if (!response.ok) return;

        const data = await response.json();
        const statusDiv = document.getElementById("scanStatus");

        if (data.status === "running") {
            // Рассчитываем оценку времени
            if (!scanStartTime) scanStartTime = Date.now();
            const elapsed = (Date.now() - scanStartTime) / 1000; // секунды
            let timeRemaining = "...";

            if (data.progress > 5 && elapsed > 10) {
                const rate = elapsed / data.progress; // сек на процент
                const remainingPercent = 100 - data.progress;
                const remainingSecs = Math.round(rate * remainingPercent);
                const mins = Math.ceil(remainingSecs / 60);
                timeRemaining = mins > 0 ? `~${mins} мин` : `<1 мин`;
            }

            const progressBar = `
                <div style="margin-top: 8px;">
                    <div style="width:100%; height:20px; background:#e9ecef; border-radius:3px; overflow:hidden;">
                        <div style="width:${data.progress}%; height:100%; background:#007bff; transition:width 0.3s; display:flex; align-items:center; justify-content:center;">
                            <span style="color:white; font-size:11px; font-weight:bold;">${data.progress}%</span>
                        </div>
                    </div>
                    <div style="font-size:12px; margin-top:4px; color:#666;">
                        ${data.scanned_pages}/${data.total_pages} страниц | ${timeRemaining}
                    </div>
                </div>
            `;

            statusDiv.className = "status loading";
            statusDiv.innerHTML = `⏳ Сканирование...${progressBar}`;
            scanPollTimeout = setTimeout(() => pollScanStatus(scanId), 2000);
        } else if (data.status === "completed") {
            scanStartTime = null;
            statusDiv.className = "status success";
            statusDiv.textContent = `✓ Найдено ${data.total_images} изображений`;
            document.getElementById("scanBtn").disabled = false;
            loadGallery();
        } else {
            scanStartTime = null;
            statusDiv.className = "status error";
            statusDiv.textContent = `✗ Ошибка при сканировании`;
            document.getElementById("scanBtn").disabled = false;
        }
    } catch (error) {
        console.error("Poll error:", error);
    }
}

async function startScan() {
    let siteUrl = document.getElementById("siteUrl").value.trim();
    siteUrl = siteUrl.replace(/\/$/, "");  // удаляем trailing slash
    if (!siteUrl) {
        alert("Укажи URL сайта");
        return;
    }

    const statusDiv = document.getElementById("scanStatus");
    const btn = document.getElementById("scanBtn");

    btn.disabled = true;
    statusDiv.className = "status loading";
    statusDiv.textContent = "Сканирование...";

    if (scanPollTimeout) clearTimeout(scanPollTimeout);

    try {
        const response = await fetch(`${API_BASE}/scan`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ site_url: siteUrl })
        });

        if (!response.ok) {
            throw new Error(`Ошибка: ${response.status}`);
        }

        const data = await response.json();
        currentScanId = data.scan_id;
        localStorage.setItem('lastScanId', currentScanId);
        currentSiteUrl = siteUrl;
        currentPage = 1;
        selectedIds.clear();

        // Если сканирование уже завершено (маловероятно), показываем результат
        if (data.status === "completed") {
            statusDiv.className = "status success";
            statusDiv.textContent = `✓ Найдено ${data.count} изображений`;
            btn.disabled = false;
            loadGallery();
        } else {
            // Иначе начинаем polling
            statusDiv.textContent = `⏳ Сканирование... (обрабатывается)`;
            pollScanStatus(data.scan_id);
        }
    } catch (error) {
        statusDiv.className = "status error";
        statusDiv.textContent = `✗ ${error.message}`;
        btn.disabled = false;
    }
}

async function loadGallery() {
    try {
        const params = new URLSearchParams();
        params.append('page', 1);
        params.append('limit', 10000);  // загружаем все (без пагинации сейчас)

        if (currentScanId) params.append('scan_id', currentScanId);
        if (filters.status) params.append('status', filters.status);
        if (filters.page) params.append('page_url', filters.page);

        const response = await fetch(`${API_BASE}/images?${params}`);
        if (!response.ok) throw new Error(`Ошибка загрузки галереи: ${response.status}`);

        const data = await response.json();
        const items = data.items || [];

        // Группируем по image_url
        const groupedImages = {};
        items.forEach(img => {
            if (!groupedImages[img.image_url]) {
                groupedImages[img.image_url] = {
                    ids: [],
                    image_url: img.image_url,
                    status: img.status,
                    pages: [],
                    // Аудит данные
                    http_status: img.http_status,
                    file_size: img.file_size,
                    format: img.format,
                    alt_text: img.alt_text,
                    copyright_score: img.copyright_score,
                    risk_details: img.risk_details
                };
            }
            groupedImages[img.image_url].ids.push(img.id);
            if (!groupedImages[img.image_url].pages.includes(img.page_url)) {
                groupedImages[img.image_url].pages.push(img.page_url);
            }
        });

        allImages = Object.values(groupedImages);
        renderGallery();
    } catch (error) {
        console.error("Gallery error:", error);
        alert(`Ошибка: ${error.message}`);
    }
}

function renderGallery() {
    const gallery = document.getElementById("gallery");
    gallery.innerHTML = "";

    if (allImages.length === 0) {
        gallery.innerHTML = "<p style='text-align:center; padding:40px;'>Нет изображений</p>";
        return;
    }

    allImages.forEach(img => {
        const card = document.createElement("div");
        card.className = "card";
        const firstId = img.ids[0];  // используем первый ID для галочки
        if (selectedIds.has(firstId)) {
            card.classList.add("selected");
        }

        const isSelected = selectedIds.has(firstId);
        const pagesHtml = img.pages.map(page =>
            `<a href="${page}" target="_blank" style="display:block; margin:4px 0; font-size:11px; word-break:break-all;">${page}</a>`
        ).join("");

        // Форматируем размер файла
        const fileSizeText = img.file_size ?
            (img.file_size > 1024*1024 ? (img.file_size/(1024*1024)).toFixed(1) + ' MB' :
             img.file_size > 1024 ? (img.file_size/1024).toFixed(1) + ' KB' :
             img.file_size + ' B') : '—';

        // Риск авторского права
        const riskColor = {
            'low': '#28a745',    // зелёный
            'medium': '#ffc107',  // жёлтый
            'high': '#dc3545'     // красный
        };
        const riskIcon = {
            'low': '✅',
            'medium': '⚠️',
            'high': '🚫'
        };
        const riskText = {
            'low': 'Низкий риск',
            'medium': 'Средний риск',
            'high': 'Высокий риск'
        };

        const riskScore = img.copyright_score || 'low';
        const riskTooltip = img.risk_details ? img.risk_details.reason || '' : '';

        // Аудит информация
        const auditHtml = `
            <div style="margin-top: 8px; background:#f5f5f5; padding:6px; border-radius:3px; font-size:12px;">
                <div style="display:flex; justify-content:space-between; align-items:center;">
                    <div><strong>🔍 Аудит:</strong></div>
                    <div style="color:${riskColor[riskScore]}; font-weight:bold; cursor:help;" title="${riskTooltip}">
                        ${riskIcon[riskScore]} ${riskText[riskScore]}
                    </div>
                </div>
                <div>HTTP: <span style="color:${img.http_status === 200 ? '#28a745' : '#dc3545'}">${img.http_status || '—'}</span></div>
                <div>Формат: ${img.format || '—'}</div>
                <div>Размер: ${fileSizeText}</div>
                ${img.alt_text ? `<div>Alt: <em>"${img.alt_text}"</em></div>` : ''}
            </div>
        `;

        card.innerHTML = `
            <div style="position: relative;">
                <img src="/api/image?url=${encodeURIComponent(img.image_url)}"
                     alt="preview"
                     class="card-image"
                     onerror="this.parentElement.parentElement.classList.add('broken')">
                <input type="checkbox" class="card-checkbox" ${isSelected ? "checked" : ""}
                       onchange="toggleSelectMultiple(${JSON.stringify(img.ids)}, this.checked)">
            </div>
            <div class="card-meta">
                <div class="card-status ${img.status}">${img.status}</div>
                <div class="url"><a href="${img.image_url}" target="_blank">🔗 Картинка</a></div>
                ${auditHtml}
                <div style="margin-top: 8px; color: #666; border-top:1px solid #eee; padding-top:8px;">
                    <div><strong>На страницах (${img.pages.length}):</strong></div>
                    ${pagesHtml}
                </div>
            </div>
        `;

        card.addEventListener("click", (e) => {
            if (e.target.type !== "checkbox" && e.target.tagName !== "A") {
                const checkbox = card.querySelector(".card-checkbox");
                checkbox.checked = !checkbox.checked;
                toggleSelect(img.id, checkbox.checked);
            }
        });

        gallery.appendChild(card);
    });
}

function renderPagination(total, pages) {
    const pagination = document.getElementById("pagination");
    pagination.innerHTML = "";

    if (pages <= 1) return;

    const prevBtn = document.createElement("button");
    prevBtn.textContent = "← Предыдущая";
    prevBtn.disabled = currentPage === 1;
    prevBtn.onclick = () => {
        if (currentPage > 1) {
            currentPage--;
            loadGallery();
        }
    };
    pagination.appendChild(prevBtn);

    for (let i = 1; i <= Math.min(pages, 5); i++) {
        const btn = document.createElement("button");
        btn.textContent = i;
        btn.className = i === currentPage ? "active" : "";
        btn.onclick = () => {
            currentPage = i;
            loadGallery();
        };
        pagination.appendChild(btn);
    }

    if (pages > 5) {
        const dots = document.createElement("span");
        dots.textContent = "...";
        dots.style.padding = "0 5px";
        pagination.appendChild(dots);
    }

    const nextBtn = document.createElement("button");
    nextBtn.textContent = "Следующая →";
    nextBtn.disabled = currentPage === pages;
    nextBtn.onclick = () => {
        if (currentPage < pages) {
            currentPage++;
            loadGallery();
        }
    };
    pagination.appendChild(nextBtn);
}

function toggleSelect(id, checked) {
    if (checked) {
        selectedIds.add(id);
    } else {
        selectedIds.delete(id);
    }
}

function toggleSelectMultiple(ids, checked) {
    ids.forEach(id => {
        if (checked) {
            selectedIds.add(id);
        } else {
            selectedIds.delete(id);
        }
    });
}

function selectAll() {
    allImages.forEach(img => {
        selectedIds.add(img.id);
    });
    renderGallery();
}

async function markAsKeep() {
    if (selectedIds.size === 0) {
        alert("Выбери изображения");
        return;
    }
    await updateStatus(Array.from(selectedIds), "KEEP");
}

async function markAsDelete() {
    if (selectedIds.size === 0) {
        alert("Выбери изображения");
        return;
    }
    await updateStatus(Array.from(selectedIds), "DELETE");
}

async function updateStatus(ids, status) {
    try {
        const response = await fetch(`${API_BASE}/images/status`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ ids: Array.from(ids), status })
        });

        if (!response.ok) throw new Error("Ошибка обновления");

        selectedIds.clear();
        await loadGallery();
    } catch (error) {
        alert(`Ошибка: ${error.message}`);
    }
}

async function exportList() {
    try {
        const scanParam = currentScanId ? `&scan_id=${currentScanId}` : "";
        const response = await fetch(`${API_BASE}/export?status=DELETE${scanParam}`);
        if (!response.ok) throw new Error("Ошибка экспорта");

        const blob = await response.blob();
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = "delete-images.txt";
        document.body.appendChild(a);
        a.click();
        window.URL.revokeObjectURL(url);
        document.body.removeChild(a);
    } catch (error) {
        alert(`Ошибка: ${error.message}`);
    }
}

function applyFilters() {
    filters.status = document.getElementById("statusFilter").value;
    filters.page = document.getElementById("pageFilter").value;
    currentPage = 1;
    loadGallery();
}

function resetFilters() {
    document.getElementById("statusFilter").value = "";
    document.getElementById("pageFilter").value = "";
    filters = { status: "", page: "" };
    currentPage = 1;
    loadGallery();
}

// Initial load
window.addEventListener("load", () => {
    console.log("App loaded");
});
