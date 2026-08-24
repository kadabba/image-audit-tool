const API_BASE = "/api";
let currentPage = 1;
const PAGE_SIZE = 50;
let selectedIds = new Set();
let allImages = [];
let currentSiteUrl = "";
let filters = {
    status: "",
    page: ""
};

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
        statusDiv.className = "status success";
        statusDiv.textContent = `✓ Найдено ${data.count} изображений`;

        currentSiteUrl = siteUrl;
        currentPage = 1;
        selectedIds.clear();
        loadGallery();
    } catch (error) {
        statusDiv.className = "status error";
        statusDiv.textContent = `✗ ${error.message}`;
    } finally {
        btn.disabled = false;
    }
}

async function loadGallery() {
    try {
        const params = new URLSearchParams();
        params.append('page', 1);
        params.append('limit', 10000);  // загружаем все (без пагинации сейчас)

        if (currentSiteUrl) params.append('site_url', currentSiteUrl);
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
                    ids: [],  // ARRAY всех ID для этого image_url
                    image_url: img.image_url,
                    status: img.status,
                    pages: []
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
        const response = await fetch(`${API_BASE}/export?status=DELETE`);
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
