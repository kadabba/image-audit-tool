const API_BASE = "/api";
const HISTORY_KEY = "scanHistory";
const HISTORY_LIMIT = 20;

// Отбираем по URL картинки: id размещений фронтенду не нужны
let selectedUrls = new Set();
let allImages = [];
let currentScanToken = null;
let scanPollTimeout = null;
let scanStartTime = null;

/* ---------- Безопасность вывода ----------
   Данные приходят со сканируемых сайтов, то есть от постороннего.
   Без экранирования кавычка в URL закрывает атрибут и даёт выполнение чужого кода. */
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

/* ---------- История сканов ----------
   Живёт только в этом браузере: без аккаунтов синхронизировать негде. */
function loadHistory() {
    try {
        const raw = JSON.parse(localStorage.getItem(HISTORY_KEY));
        return Array.isArray(raw) ? raw : [];
    } catch {
        return [];
    }
}

function saveHistory(list) {
    localStorage.setItem(HISTORY_KEY, JSON.stringify(list.slice(0, HISTORY_LIMIT)));
}

function rememberScan(entry) {
    const list = loadHistory().filter(e => e.token !== entry.token);
    list.unshift({ ...entry, savedAt: Date.now() });
    saveHistory(list);
    renderHistory();
}

function updateScanInHistory(token, patch) {
    const list = loadHistory();
    const item = list.find(e => e.token === token);
    if (!item) return;
    Object.assign(item, patch);
    saveHistory(list);
    renderHistory();
}

function forgetScan(token) {
    saveHistory(loadHistory().filter(e => e.token !== token));
    renderHistory();
}

function formatDate(value) {
    const d = new Date(value);
    return isNaN(d) ? "" : d.toLocaleString("ru-RU", {
        day: "numeric", month: "long", hour: "2-digit", minute: "2-digit"
    });
}

function renderHistory() {
    const list = loadHistory();
    const wrap = document.getElementById("historyWrap");
    const menu = document.getElementById("historyMenu");

    wrap.hidden = list.length === 0;
    if (!list.length) return;

    menu.innerHTML = list.map(e => {
        const expired = e.expired === true;
        const parts = [];
        if (e.images != null) parts.push(`${e.images} картинок`);
        parts.push(expired ? "срок истёк" : formatDate(e.savedAt));
        return `<button class="history-item" data-token="${esc(e.token)}" ${expired ? "disabled" : ""}>
                    <span class="site">${esc(e.site || "без адреса")}</span>
                    <span class="meta">${esc(parts.join(" · "))}</span>
                </button>`;
    }).join("");

    menu.querySelectorAll(".history-item:not([disabled])").forEach(btn => {
        btn.addEventListener("click", () => {
            menu.hidden = true;
            document.getElementById("historyBtn").setAttribute("aria-expanded", "false");
            openScan(btn.dataset.token);
        });
    });
}

/* ---------- Загрузка ---------- */
window.addEventListener("load", () => {
    renderHistory();
    wireControls();

    // Ссылка, которой поделились, важнее сохранённого в браузере скана
    const shared = new URLSearchParams(window.location.search).get("scan");
    const token = shared || loadHistory()[0]?.token;
    if (token) openScan(token, { fromShare: Boolean(shared) });
});

function wireControls() {
    document.getElementById("scanForm").addEventListener("submit", e => {
        e.preventDefault();
        startScan();
    });

    document.getElementById("shareBtn").addEventListener("click", shareScan);

    const btn = document.getElementById("historyBtn");
    const menu = document.getElementById("historyMenu");
    btn.addEventListener("click", e => {
        e.stopPropagation();
        const open = menu.hidden;
        menu.hidden = !open;
        btn.setAttribute("aria-expanded", String(open));
    });
    document.addEventListener("click", () => {
        menu.hidden = true;
        btn.setAttribute("aria-expanded", "false");
    });
    menu.addEventListener("click", e => e.stopPropagation());
}

async function openScan(token, { fromShare = false } = {}) {
    currentScanToken = token;
    selectedUrls.clear();

    try {
        const response = await fetch(`${API_BASE}/scan/${encodeURIComponent(token)}`);

        // 404 — скан удалён по истечении срока хранения
        if (response.status === 404) {
            updateScanInHistory(token, { expired: true });
            if (fromShare) {
                showStatus("error", "Срок хранения этого скана истёк — данные удалены.");
            }
            currentScanToken = null;
            return;
        }
        if (!response.ok) return;

        const data = await response.json();
        rememberScan({ token, site: data.site_url, images: data.total_images, expiresAt: data.expires_at });

        if (data.status === "running") {
            document.getElementById("scanBtn").disabled = true;
            pollScanStatus(token);
        } else if (data.status === "completed") {
            showResults(data);
            await loadGallery();
        } else {
            showStatus("error", "Это сканирование завершилось с ошибкой.");
        }
    } catch (error) {
        console.error("openScan:", error);
    }
}

/* ---------- Сканирование ---------- */
function showStatus(kind, html) {
    const el = document.getElementById("scanStatus");
    el.hidden = false;
    el.className = `status ${kind}`;
    el.innerHTML = html;
}

function showResults(data) {
    document.body.classList.add("has-results");
    document.getElementById("results").hidden = false;
    document.getElementById("scanStatus").hidden = true;
    document.getElementById("scanBtn").disabled = false;

    document.getElementById("resultsCount").textContent =
        `${data.total_images} ${plural(data.total_images, "картинка", "картинки", "картинок")}`;
    document.getElementById("resultsSite").textContent = data.site_url || "";

    const expiry = document.getElementById("resultsExpiry");
    expiry.textContent = data.expires_at ? `удалится ${formatDate(data.expires_at)}` : "";
}

function plural(n, one, few, many) {
    const m10 = n % 10, m100 = n % 100;
    if (m10 === 1 && m100 !== 11) return one;
    if (m10 >= 2 && m10 <= 4 && (m100 < 10 || m100 >= 20)) return few;
    return many;
}

async function pollScanStatus(token) {
    try {
        const response = await fetch(`${API_BASE}/scan/${encodeURIComponent(token)}`);
        if (!response.ok) return;

        const data = await response.json();

        if (data.status === "running") {
            if (!scanStartTime) scanStartTime = Date.now();
            const elapsed = (Date.now() - scanStartTime) / 1000;
            let remaining = "оцениваем...";

            if (data.progress > 5 && elapsed > 10) {
                const secs = Math.round((elapsed / data.progress) * (100 - data.progress));
                const mins = Math.ceil(secs / 60);
                remaining = mins > 0 ? `осталось ~${mins} мин` : "меньше минуты";
            }

            showStatus("loading", `
                <div>Сканируем ${esc(data.site_url || "сайт")}</div>
                <div class="progress-track">
                    <div class="progress-fill" style="width:${Number(data.progress)}%"></div>
                </div>
                <div class="progress-meta">
                    <span>${Number(data.scanned_pages)} из ${Number(data.total_pages)} страниц</span>
                    <span>${esc(remaining)}</span>
                </div>`);

            scanPollTimeout = setTimeout(() => pollScanStatus(token), 2000);
        } else if (data.status === "completed") {
            scanStartTime = null;
            updateScanInHistory(token, { images: data.total_images, expiresAt: data.expires_at });
            showResults(data);
            loadGallery();
        } else {
            scanStartTime = null;
            showStatus("error", "Сканирование завершилось с ошибкой.");
            document.getElementById("scanBtn").disabled = false;
        }
    } catch (error) {
        console.error("Poll error:", error);
    }
}

async function startScan() {
    const siteUrl = document.getElementById("siteUrl").value.trim().replace(/\/$/, "");
    if (!siteUrl) return;

    const btn = document.getElementById("scanBtn");
    btn.disabled = true;
    showStatus("loading", "Ищем карту сайта...");

    if (scanPollTimeout) clearTimeout(scanPollTimeout);
    scanStartTime = null;
    selectedUrls.clear();
    document.getElementById("results").hidden = true;
    document.getElementById("shareHint").hidden = true;

    try {
        const response = await fetch(`${API_BASE}/scan/`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ site_url: siteUrl })
        });

        if (!response.ok) {
            const detail = await response.json().then(d => d.detail).catch(() => null);
            throw new Error(detail || `Ошибка ${response.status}`);
        }

        const data = await response.json();
        currentScanToken = data.scan_token;
        rememberScan({ token: currentScanToken, site: siteUrl });

        // Адрес в строке браузера — уже готовая ссылка, которой можно поделиться
        history.replaceState(null, "", `?scan=${encodeURIComponent(currentScanToken)}`);
        pollScanStatus(currentScanToken);
    } catch (error) {
        showStatus("error", esc(error.message));
        btn.disabled = false;
    }
}

/* ---------- Поделиться ---------- */
async function shareScan() {
    if (!currentScanToken) return;

    const url = `${window.location.origin}/?scan=${encodeURIComponent(currentScanToken)}`;
    const entry = loadHistory().find(e => e.token === currentScanToken);
    const until = entry?.expiresAt ? ` Действует до ${formatDate(entry.expiresAt)}.` : "";

    let copied = true;
    try {
        await navigator.clipboard.writeText(url);
    } catch {
        copied = false;  // нет доступа к буферу (не https или отказ) — показываем ссылку целиком
    }

    const hint = document.getElementById("shareHint");
    hint.hidden = false;
    hint.innerHTML = copied
        ? `<strong>Ссылка скопирована.</strong>${esc(until)}
           <span class="warn">Открыть скан сможет любой, у кого есть эта ссылка.</span>`
        : `<strong>Скопируйте ссылку:</strong> <code>${esc(url)}</code>${esc(until)}
           <span class="warn">Открыть скан сможет любой, у кого есть эта ссылка.</span>`;
}

/* ---------- Галерея ---------- */
async function loadGallery() {
    if (!currentScanToken) return;

    try {
        // Группировку делает сервер: одна запись на картинку со списком страниц
        const params = new URLSearchParams({ scan_token: currentScanToken, page: 1, limit: 1000 });
        const response = await fetch(`${API_BASE}/images?${params}`);
        if (!response.ok) throw new Error(`Ошибка загрузки галереи: ${response.status}`);

        allImages = (await response.json()).items || [];
        renderGallery();
    } catch (error) {
        console.error("Gallery error:", error);
    }
}

function formatSize(size) {
    if (!size) return "—";
    if (size > 1048576) return (size / 1048576).toFixed(1) + " MB";
    if (size > 1024) return (size / 1024).toFixed(1) + " KB";
    return size + " B";
}

function renderGallery() {
    const gallery = document.getElementById("gallery");
    gallery.innerHTML = "";

    if (!allImages.length) {
        gallery.innerHTML = '<p class="empty">Изображений не найдено</p>';
        return;
    }

    const riskIcon = { low: "✅", medium: "⚠️", high: "🚫" };
    const riskText = { low: "Низкий риск", medium: "Средний риск", high: "Высокий риск" };

    allImages.forEach(img => {
        const card = document.createElement("div");
        card.className = "card";

        const isSelected = selectedUrls.has(img.image_url);
        if (isSelected) card.classList.add("selected");

        const risk = riskText[img.copyright_score] ? img.copyright_score : "low";
        const tooltip = img.risk_details?.reason || "";

        const pagesHtml = img.pages.map(p =>
            `<a href="${esc(safeUrl(p))}" target="_blank" rel="noopener noreferrer">${esc(p)}</a>`
        ).join("") + (img.pages_total > img.pages.length
            ? `<span class="muted">и ещё ${img.pages_total - img.pages.length}</span>` : "");

        card.innerHTML = `
            <div class="card-thumb">
                <img src="/api/image?url=${encodeURIComponent(img.image_url)}" alt="" class="card-image"
                     loading="lazy" onerror="this.closest('.card').classList.add('broken')">
                <input type="checkbox" class="card-checkbox" ${isSelected ? "checked" : ""}
                       aria-label="Отметить изображение">
            </div>
            <div class="card-meta">
                <div class="card-row">
                    <span class="badge ${esc(img.status)}">${esc(img.status)}</span>
                    <span class="risk risk-${risk}" title="${esc(tooltip)}">${riskIcon[risk]} ${riskText[risk]}</span>
                </div>
                <div class="card-row">
                    <span>HTTP</span>
                    <span class="${img.http_status === 200 ? "status-ok" : "status-bad"}">${esc(img.http_status || "—")}</span>
                </div>
                <div class="card-row"><span>Формат</span><span>${esc(img.format || "—")}</span></div>
                <div class="card-row"><span>Размер</span><span>${esc(formatSize(img.file_size))}</span></div>
                <div class="card-row">
                    <span>Файл</span>
                    <span><a href="${esc(safeUrl(img.image_url))}" target="_blank" rel="noopener noreferrer">открыть</a></span>
                </div>
                <details class="card-links">
                    <summary>На страницах (${img.pages_total})</summary>
                    ${pagesHtml}
                </details>
            </div>`;

        const checkbox = card.querySelector(".card-checkbox");
        const toggle = checked => {
            checked ? selectedUrls.add(img.image_url) : selectedUrls.delete(img.image_url);
            card.classList.toggle("selected", checked);
        };

        checkbox.addEventListener("change", () => toggle(checkbox.checked));
        card.addEventListener("click", e => {
            if (e.target.type === "checkbox" || e.target.tagName === "A" || e.target.closest("details")) return;
            checkbox.checked = !checkbox.checked;
            toggle(checkbox.checked);
        });

        gallery.appendChild(card);
    });
}

function selectAll() {
    const all = allImages.every(img => selectedUrls.has(img.image_url));
    selectedUrls.clear();
    if (!all) allImages.forEach(img => selectedUrls.add(img.image_url));
    renderGallery();
}

function exportList() {
    // Отмеченное живёт только в браузере — файл собираем здесь же
    const urls = allImages
        .filter(img => selectedUrls.has(img.image_url))
        .map(img => img.image_url);

    if (!urls.length) {
        alert("Отметьте хотя бы одно изображение");
        return;
    }

    const blob = new Blob([urls.join("\n") + "\n"], { type: "text/plain" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "delete-images.txt";
    document.body.appendChild(a);
    a.click();
    URL.revokeObjectURL(url);
    a.remove();
}
