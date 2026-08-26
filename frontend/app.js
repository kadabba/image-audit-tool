const API_BASE = "/api";
let selectedIds = new Set();
let allImages = [];
let currentScanToken = null;
let scanPollTimeout = null;
let scanStartTime = null;

// Данные приходят со сканируемых сайтов, то есть от постороннего.
// Без экранирования кавычка в URL закрывает атрибут и даёт выполнение чужого кода.
function esc(value) {
    return String(value ?? "").replace(/[&<>"']/g, c => ({
        "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
    })[c]);
}

// В href пускаем только http(s): javascript:-ссылка сработала бы по клику.
function safeUrl(value) {
    try {
        const u = new URL(value, window.location.href);
        return (u.protocol === "http:" || u.protocol === "https:") ? u.href : "#";
    } catch {
        return "#";
    }
}

window.addEventListener("load", () => {
    currentScanToken = localStorage.getItem("scanToken");
    if (currentScanToken) loadGallery();
});

async function pollScanStatus(token) {
    try {
        const response = await fetch(`${API_BASE}/scan/${encodeURIComponent(token)}`);
        if (!response.ok) return;

        const data = await response.json();
        const statusDiv = document.getElementById("scanStatus");

        if (data.status === "running") {
            if (!scanStartTime) scanStartTime = Date.now();
            const elapsed = (Date.now() - scanStartTime) / 1000;
            let timeRemaining = "...";

            if (data.progress > 5 && elapsed > 10) {
                const remainingSecs = Math.round((elapsed / data.progress) * (100 - data.progress));
                const mins = Math.ceil(remainingSecs / 60);
                timeRemaining = mins > 0 ? `~${mins} мин` : "<1 мин";
            }

            statusDiv.className = "status loading";
            statusDiv.innerHTML = `⏳ Сканирование...
                <div style="margin-top: 8px;">
                    <div style="width:100%; height:20px; background:#e9ecef; border-radius:3px; overflow:hidden;">
                        <div style="width:${Number(data.progress)}%; height:100%; background:#007bff; transition:width 0.3s; display:flex; align-items:center; justify-content:center;">
                            <span style="color:white; font-size:11px; font-weight:bold;">${Number(data.progress)}%</span>
                        </div>
                    </div>
                    <div style="font-size:12px; margin-top:4px; color:#666;">
                        ${Number(data.scanned_pages)}/${Number(data.total_pages)} страниц | ${esc(timeRemaining)}
                    </div>
                </div>`;
            scanPollTimeout = setTimeout(() => pollScanStatus(token), 2000);
        } else if (data.status === "completed") {
            scanStartTime = null;
            statusDiv.className = "status success";
            statusDiv.textContent = `✓ Найдено ${data.total_images} изображений`;
            document.getElementById("scanBtn").disabled = false;
            loadGallery();
        } else {
            scanStartTime = null;
            statusDiv.className = "status error";
            statusDiv.textContent = "✗ Ошибка при сканировании";
            document.getElementById("scanBtn").disabled = false;
        }
    } catch (error) {
        console.error("Poll error:", error);
    }
}

async function startScan() {
    const siteUrl = document.getElementById("siteUrl").value.trim().replace(/\/$/, "");
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
        const response = await fetch(`${API_BASE}/scan/`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ site_url: siteUrl })
        });

        if (!response.ok) {
            const detail = await response.json().then(d => d.detail).catch(() => null);
            throw new Error(detail || `Ошибка: ${response.status}`);
        }

        const data = await response.json();
        currentScanToken = data.scan_token;
        localStorage.setItem("scanToken", currentScanToken);
        selectedIds.clear();

        statusDiv.textContent = "⏳ Сканирование... (обрабатывается)";
        pollScanStatus(currentScanToken);
    } catch (error) {
        statusDiv.className = "status error";
        statusDiv.textContent = `✗ ${error.message}`;
        btn.disabled = false;
    }
}

async function loadGallery() {
    if (!currentScanToken) return;

    try {
        const params = new URLSearchParams({
            scan_token: currentScanToken,
            page: 1,
            limit: 10000
        });

        const response = await fetch(`${API_BASE}/images?${params}`);
        if (!response.ok) throw new Error(`Ошибка загрузки галереи: ${response.status}`);

        const items = (await response.json()).items || [];

        // Одна картинка = одна карточка, страницы собираем в список
        const grouped = {};
        items.forEach(img => {
            if (!grouped[img.image_url]) {
                grouped[img.image_url] = {
                    ids: [],
                    image_url: img.image_url,
                    status: img.status,
                    pages: [],
                    http_status: img.http_status,
                    file_size: img.file_size,
                    format: img.format,
                    copyright_score: img.copyright_score,
                    risk_details: img.risk_details
                };
            }
            grouped[img.image_url].ids.push(img.id);
            if (!grouped[img.image_url].pages.includes(img.page_url)) {
                grouped[img.image_url].pages.push(img.page_url);
            }
        });

        allImages = Object.values(grouped);
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

    const riskColor = { low: "#28a745", medium: "#ffc107", high: "#dc3545" };
    const riskIcon = { low: "✅", medium: "⚠️", high: "🚫" };
    const riskText = { low: "Низкий риск", medium: "Средний риск", high: "Высокий риск" };

    allImages.forEach(img => {
        const card = document.createElement("div");
        card.className = "card";

        const isSelected = img.ids.some(id => selectedIds.has(id));
        if (isSelected) card.classList.add("selected");

        const pagesHtml = img.pages.map(page =>
            `<a href="${esc(safeUrl(page))}" target="_blank" rel="noopener noreferrer"
                style="display:block; margin:4px 0; font-size:11px; word-break:break-all;">${esc(page)}</a>`
        ).join("");

        const size = img.file_size;
        const fileSizeText = size
            ? (size > 1048576 ? (size / 1048576).toFixed(1) + " MB"
                : size > 1024 ? (size / 1024).toFixed(1) + " KB"
                    : size + " B")
            : "—";

        const riskScore = riskColor[img.copyright_score] ? img.copyright_score : "low";
        const riskTooltip = img.risk_details ? (img.risk_details.reason || "") : "";

        card.innerHTML = `
            <div style="position: relative;">
                <img src="/api/image?url=${encodeURIComponent(img.image_url)}"
                     alt="preview"
                     class="card-image"
                     onerror="this.parentElement.parentElement.classList.add('broken')">
                <input type="checkbox" class="card-checkbox" ${isSelected ? "checked" : ""}>
            </div>
            <div class="card-meta">
                <div class="card-status ${esc(img.status)}">${esc(img.status)}</div>
                <div class="url">
                    <a href="${esc(safeUrl(img.image_url))}" target="_blank" rel="noopener noreferrer">🔗 Картинка</a>
                </div>
                <div style="margin-top: 8px; background:#f5f5f5; padding:6px; border-radius:3px; font-size:12px;">
                    <div style="display:flex; justify-content:space-between; align-items:center;">
                        <div><strong>🔍 Аудит:</strong></div>
                        <div style="color:${riskColor[riskScore]}; font-weight:bold; cursor:help;" title="${esc(riskTooltip)}">
                            ${riskIcon[riskScore]} ${riskText[riskScore]}
                        </div>
                    </div>
                    <div>HTTP: <span style="color:${img.http_status === 200 ? "#28a745" : "#dc3545"}">${esc(img.http_status || "—")}</span></div>
                    <div>Формат: ${esc(img.format || "—")}</div>
                    <div>Размер: ${esc(fileSizeText)}</div>
                </div>
                <details style="margin-top: 8px; color: #666; border-top:1px solid #eee; padding-top:8px;">
                    <summary style="cursor:pointer;"><strong>На страницах (${img.pages.length})</strong></summary>
                    ${pagesHtml}
                </details>
            </div>
        `;

        const checkbox = card.querySelector(".card-checkbox");
        checkbox.addEventListener("change", () => {
            toggleSelectMultiple(img.ids, checkbox.checked);
            card.classList.toggle("selected", checkbox.checked);
        });

        card.addEventListener("click", (e) => {
            if (e.target.type !== "checkbox" && e.target.tagName !== "A" && !e.target.closest("details")) {
                checkbox.checked = !checkbox.checked;
                toggleSelectMultiple(img.ids, checkbox.checked);
                card.classList.toggle("selected", checkbox.checked);
            }
        });

        gallery.appendChild(card);
    });
}

function toggleSelectMultiple(ids, checked) {
    ids.forEach(id => checked ? selectedIds.add(id) : selectedIds.delete(id));
}

function selectAll() {
    allImages.forEach(img => img.ids.forEach(id => selectedIds.add(id)));
    renderGallery();
}

function exportList() {
    // Отмеченное живёт только в браузере — файл собираем здесь же
    const urls = allImages
        .filter(img => img.ids.some(id => selectedIds.has(id)))
        .map(img => img.image_url);

    if (urls.length === 0) {
        alert("Отметь хотя бы одну картинку");
        return;
    }

    const blob = new Blob([urls.join("\n") + "\n"], { type: "text/plain" });
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "delete-images.txt";
    document.body.appendChild(a);
    a.click();
    window.URL.revokeObjectURL(url);
    document.body.removeChild(a);
}
