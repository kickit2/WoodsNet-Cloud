// Configuration
// In production, this URL would be set dynamically. For testing, we mock it.
let API_BASE_URL = localStorage.getItem('woods_api_url') || '';
let AUTH_TOKEN = localStorage.getItem('woods_auth_token') || '';
let cachedImages = [];
let muleMappings = {};
let muleStatus = {};
let isSelectMode = false;
let selectedKeys = new Set();
let currentNextToken = null;
let isLoadingMore = false;

// Map & Core Helpers
let configMap = null;
let configTempMarker = null;
let mainMap = null;
let mainMarkerLayer = null;

function getMuleName(id) {
    if (!muleMappings[id]) return id;
    if (typeof muleMappings[id] === 'object') return muleMappings[id].name;
    return muleMappings[id];
}

function getMuleLocation(id) {
    if (muleMappings[id] && typeof muleMappings[id] === 'object') {
        return { lat: muleMappings[id].lat, lng: muleMappings[id].lng };
    }
    return null;
}

// DOM Elements
const authOverlay = document.getElementById('auth-overlay');
const authForm = document.getElementById('auth-form');
const passwordInput = document.getElementById('password-input');
const authError = document.getElementById('auth-error');
const appContent = document.getElementById('app-content');

const galleryGrid = document.getElementById('gallery-grid');
const loadingState = document.getElementById('loading-state');
const emptyState = document.getElementById('empty-state');
const loadMoreContainer = document.getElementById('load-more-container');
const loadMoreBtn = document.getElementById('load-more-btn');
const refreshBtn = document.getElementById('refresh-btn');
const logoutBtn = document.getElementById('logout-btn');

const lightboxOverlay = document.getElementById('lightbox-overlay');
const lightboxCloseBtn = document.getElementById('lightbox-close');
const lightboxImg = document.getElementById('lightbox-img');

const themeToggleBtn = document.getElementById('theme-toggle-btn');
const themeIconMoon = document.getElementById('theme-icon-moon');
const themeIconSun = document.getElementById('theme-icon-sun');
const dashboardBtn = document.getElementById('dashboard-btn');
const analyticsDashboard = document.getElementById('analytics-dashboard');
const liveDashboardBtn = document.getElementById('live-dashboard-btn');
const liveDashboard = document.getElementById('live-dashboard');
const dashboardGrid = document.getElementById('dashboard-grid');
const mapViewBtn = document.getElementById('map-view-btn');
const mainMapContainer = document.getElementById('main-map-container');

const totalCountEl = document.getElementById('total-count');
const activeMulesEl = document.getElementById('active-mules');

const toolbar = document.getElementById('toolbar');
const sortSelect = document.getElementById('sort-select');
const toggleSelectModeBtn = document.getElementById('toggle-select-mode-btn');
const generateTimelapseBtn = document.getElementById('generate-timelapse-btn');
const bulkActions = document.getElementById('bulk-actions');
const selectedCountEl = document.getElementById('selected-count');
const bulkDownloadBtn = document.getElementById('bulk-download-btn');
const bulkDeleteBtn = document.getElementById('bulk-delete-btn');
const startDateInput = document.getElementById('start-date');
const endDateInput = document.getElementById('end-date');
const aiFilterSelect = document.getElementById('ai-filter');

const configOverlay = document.getElementById('config-overlay');
const configBtn = document.getElementById('config-btn');
const closeConfigBtn = document.getElementById('close-config-btn');
const mappingsList = document.getElementById('mappings-list');
const addMappingBtn = document.getElementById('add-mapping-btn');
const newMuleIdInput = document.getElementById('new-mule-id');
const newMuleNameInput = document.getElementById('new-mule-name');
const newMuleLatInput = document.getElementById('new-mule-lat');
const newMuleLngInput = document.getElementById('new-mule-lng');
const saveConfigBtn = document.getElementById('save-config-btn');
const alertPersonCheckbox = document.getElementById('alert-person');
const alertBuckCheckbox = document.getElementById('alert-buck');

// Initialize
const savedTheme = localStorage.getItem('woods_theme') || 'dark';
if (savedTheme === 'light') {
    document.body.classList.add('light-mode');
    if (themeIconSun) themeIconSun.classList.add('hidden');
    if (themeIconMoon) themeIconMoon.classList.remove('hidden');
}

function init() {
    if (AUTH_TOKEN) {
        showApp();
        fetchImages();
    } else {
        showAuth();
    }
}

// Authentication Flow
authForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const pwd = passwordInput.value.trim();

    // We need the API URL to test the password. 
    // For pure Vanilla demo purposes without a bundler, we prompt if missing.
    if (!API_BASE_URL) {
        let urlRes = prompt("Please enter the AWS API Gateway Base API URL:");
        if (urlRes) {
            API_BASE_URL = urlRes.trim();
            localStorage.setItem('woods_api_url', API_BASE_URL);
        } else {
            return;
        }
    }

    try {
        authError.classList.add('hidden');
        const btn = authForm.querySelector('button');
        btn.textContent = "Verifying...";
        btn.disabled = true;

        const response = await fetch(`${API_BASE_URL}/list-images`, {
            headers: {
                'Authorization': `Bearer ${pwd}`
            }
        });

        if (response.ok) {
            AUTH_TOKEN = pwd;
            localStorage.setItem('woods_auth_token', pwd);
            const data = await response.json();
            cachedImages = data.images || [];
            muleMappings = data.mule_mappings || {};
            muleStatus = data.mule_status || {};
            showApp();
            applySortAndRender();
        } else {
            throw new Error("Invalid password");
        }
    } catch (err) {
        authError.textContent = "Invalid password or network error.";
        authError.classList.remove('hidden');
    } finally {
        const btn = authForm.querySelector('button');
        btn.textContent = "Access Fleet";
        btn.disabled = false;
    }
});

function logout() {
    AUTH_TOKEN = '';
    localStorage.removeItem('woods_auth_token');
    passwordInput.value = '';
    showAuth();
}

function showAuth() {
    authOverlay.classList.add('active');
    authOverlay.classList.remove('hidden');
    appContent.classList.add('hidden');
    passwordInput.focus();
}

function showApp() {
    authOverlay.classList.remove('active');
    setTimeout(() => authOverlay.classList.add('hidden'), 300);
    appContent.classList.remove('hidden');
}

// Data Fetching
async function fetchImages(loadMore = false) {
    if (!API_BASE_URL || !AUTH_TOKEN) return;

    if (!loadMore) {
        galleryGrid.innerHTML = '';
        loadingState.classList.remove('hidden');
        emptyState.classList.add('hidden');
        loadMoreContainer.classList.add('hidden');
        currentNextToken = null;
    } else {
        if (!currentNextToken || isLoadingMore) return;
        isLoadingMore = true;
        loadMoreBtn.textContent = "Loading...";
        loadMoreBtn.disabled = true;
    }

    try {
        let url = `${API_BASE_URL}/list-images`;
        if (loadMore && currentNextToken) {
            url += `?next_token=${encodeURIComponent(currentNextToken)}`;
        }

        const response = await fetch(url, {
            headers: {
                'Authorization': `Bearer ${AUTH_TOKEN}`
            }
        });

        if (response.status === 401) {
            logout(); // Token expired or changed
            return;
        }

        if (!response.ok) throw new Error("API Fetch failed");

        const data = await response.json();

        if (loadMore) {
            cachedImages = cachedImages.concat(data.images || []);
            currentNextToken = data.next_token || null;
            isLoadingMore = false;
        } else {
            cachedImages = data.images || [];
            muleMappings = data.mule_mappings || {};
            muleStatus = data.mule_status || {};

            const prefs = data.notification_prefs || { alert_person: true, alert_buck: true };
            if (alertPersonCheckbox) alertPersonCheckbox.checked = prefs.alert_person;
            if (alertBuckCheckbox) alertBuckCheckbox.checked = prefs.alert_buck;

            currentNextToken = data.next_token || null;
        }

        applySortAndRender();

    } catch (err) {
        console.error("Fetch error:", err);
        if (!loadMore) {
            loadingState.classList.add('hidden');
            emptyState.classList.remove('hidden');
        }
    } finally {
        if (loadMore) {
            loadMoreBtn.textContent = "Load More";
            loadMoreBtn.disabled = false;
        }
    }
}

// Rendering & Sorting
let activityChartInstance = null;
let cameraChartInstance = null;

function applySortAndRender() {
    const sortBy = sortSelect.value;
    const startDate = startDateInput.value ? new Date(startDateInput.value) : null;
    let endDate = endDateInput.value ? new Date(endDateInput.value) : null;
    const aiFilter = aiFilterSelect ? aiFilterSelect.value : 'all';

    if (endDate) {
        endDate.setHours(23, 59, 59, 999);
    }

    // Filter
    let filteredImages = cachedImages.filter(img => {
        const imgDate = new Date(img.timestamp);
        if (startDate && imgDate < startDate) return false;
        if (endDate && imgDate > endDate) return false;

        if (aiFilter === 'animals') {
            if (!img.ai_data || !img.ai_data.has_animals) return false;
        } else if (aiFilter === 'empty') {
            if (img.ai_data && img.ai_data.has_animals) return false;
        } else if (aiFilter === 'deer') {
            if (!img.ai_data || !img.ai_data.tags) return false;
            const tags = Object.keys(img.ai_data.tags);
            if (!tags.includes('Antlered Buck') && !tags.includes('Doe/Young') && !tags.includes('Deer')) return false;
        } else if (aiFilter === 'bucks') {
            if (!img.ai_data || !img.ai_data.tags) return false;
            if (!Object.keys(img.ai_data.tags).includes('Antlered Buck')) return false;
        } else if (aiFilter === 'people') {
            if (!img.ai_data || !img.ai_data.tags) return false;
            const tags = Object.keys(img.ai_data.tags);
            if (!tags.some(t => t.includes('Person') || t.includes('Human') || t.includes('People'))) return false;
        }

        return true;
    });

    // Sort
    filteredImages.sort((a, b) => {
        if (sortBy === 'newest') {
            return new Date(b.timestamp) - new Date(a.timestamp);
        } else if (sortBy === 'oldest') {
            return new Date(a.timestamp) - new Date(b.timestamp);
        } else if (sortBy === 'camera-asc') {
            return a.mule_id.localeCompare(b.mule_id);
        } else if (sortBy === 'name-asc') {
            return a.filename.localeCompare(b.filename);
        }
        return 0;
    });

    if (filteredImages.length > 0) toolbar.classList.remove('hidden');
    else toolbar.classList.add('hidden');

    if (!analyticsDashboard.classList.contains('hidden')) {
        renderCharts(filteredImages);
    }

    if (!liveDashboard.classList.contains('hidden')) {
        renderLiveDashboard(filteredImages);
    }

    renderGallery(filteredImages);
}

function renderCharts(images) {
    if (activityChartInstance) activityChartInstance.destroy();
    if (cameraChartInstance) cameraChartInstance.destroy();

    const isLight = document.body.classList.contains('light-mode');
    const textColor = isLight ? '#0f172a' : '#f8fafc';
    const gridColor = isLight ? 'rgba(0, 0, 0, 0.1)' : 'rgba(255, 255, 255, 0.1)';

    const dateCounts = {};
    const cameraCounts = {};

    images.forEach(img => {
        const dateStr = new Date(img.timestamp).toISOString().split('T')[0];
        if (!dateCounts[dateStr]) {
            dateCounts[dateStr] = { person: 0, buck: 0, doe: 0, other: 0, empty: 0 };
        }

        let hasPerson = false;
        let hasBuck = false;
        let hasDoe = false;
        let hasOther = false;

        if (img.ai_data && img.ai_data.tags) {
            for (const key of Object.keys(img.ai_data.tags)) {
                if (key.includes('Person') || key.includes('Human') || key.includes('People')) hasPerson = true;
                else if (key === 'Antlered Buck') hasBuck = true;
                else if (key === 'Doe/Young') hasDoe = true;
                else hasOther = true;
            }
        }

        if (hasPerson) dateCounts[dateStr].person++;
        else if (hasBuck) dateCounts[dateStr].buck++;
        else if (hasDoe) dateCounts[dateStr].doe++;
        else if (hasOther || (img.ai_data && img.ai_data.has_animals)) dateCounts[dateStr].other++;
        else dateCounts[dateStr].empty++;

        const cName = getMuleName(img.mule_id);
        cameraCounts[cName] = (cameraCounts[cName] || 0) + 1;
    });

    const sortedDates = Object.keys(dateCounts).sort();
    const personData = sortedDates.map(d => dateCounts[d].person);
    const buckData = sortedDates.map(d => dateCounts[d].buck);
    const doeData = sortedDates.map(d => dateCounts[d].doe);
    const otherData = sortedDates.map(d => dateCounts[d].other);
    const emptyData = sortedDates.map(d => dateCounts[d].empty);

    const ctxActivity = document.getElementById('activityChart').getContext('2d');
    activityChartInstance = new Chart(ctxActivity, {
        type: 'bar',
        data: {
            labels: sortedDates,
            datasets: [
                { label: 'People / Hunters', data: personData, backgroundColor: '#ef4444' },
                { label: 'Antlered Bucks', data: buckData, backgroundColor: '#f59e0b' },
                { label: 'Does / Young', data: doeData, backgroundColor: '#3b82f6' },
                { label: 'Other Wildlife', data: otherData, backgroundColor: '#10b981' },
                { label: 'Empty (No Animal)', data: emptyData, backgroundColor: '#64748b' }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: { legend: { labels: { color: textColor } } },
            scales: {
                y: { stacked: true, ticks: { color: textColor, precision: 0 }, grid: { color: gridColor } },
                x: { stacked: true, ticks: { color: textColor }, grid: { display: false } }
            }
        }
    });

    const cameraLabels = Object.keys(cameraCounts);
    const cameraData = Object.values(cameraCounts);
    const bgColors = ['#34d399', '#a78bfa', '#fb923c', '#38bdf8', '#f472b6', '#facc15'];

    const ctxCamera = document.getElementById('cameraChart').getContext('2d');
    cameraChartInstance = new Chart(ctxCamera, {
        type: 'doughnut',
        data: {
            labels: cameraLabels,
            datasets: [{
                data: cameraData,
                backgroundColor: bgColors,
                borderWidth: 0
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { position: 'right', labels: { color: textColor } }
            }
        }
    });
}

function renderLiveDashboard(images) {
    dashboardGrid.innerHTML = '';

    // Calculate per-mule stats from images (acting as offline fallback if muleStatus is missing)
    const cameraStats = {};
    images.forEach(img => {
        const id = img.mule_id;
        if (!cameraStats[id]) {
            cameraStats[id] = { count: 0, latestImage: img };
        }
        cameraStats[id].count++;
        if (new Date(img.timestamp) > new Date(cameraStats[id].latestImage.timestamp)) {
            cameraStats[id].latestImage = img;
        }
    });

    const uniqueMules = Object.keys(cameraStats);
    if (uniqueMules.length === 0) {
        dashboardGrid.innerHTML = '<div style="grid-column: 1/-1; text-align: center; color: var(--text-secondary); padding: 3rem;">No active cameras found.</div>';
        return;
    }

    const docFrag = document.createDocumentFragment();

    uniqueMules.forEach(id => {
        const stats = cameraStats[id];
        const statusData = muleStatus[id] || {};

        let lastHeartbeatStr = statusData.last_heartbeat || stats.latestImage.timestamp;
        const lastHeartbeat = new Date(lastHeartbeatStr);

        // Calculate age
        const hoursAgo = (new Date() - lastHeartbeat) / (1000 * 60 * 60);
        let healthClass = 'healthy';
        if (hoursAgo > 24) healthClass = 'offline';
        else if (hoursAgo > 12) healthClass = 'warning';

        const hbDisplay = lastHeartbeat.toLocaleDateString([], { month: 'short', day: 'numeric' }) + ' ' +
            lastHeartbeat.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

        const battery = statusData.battery || '--';
        const signal = statusData.signal || '--';
        const pl = statusData.power_level ? statusData.power_level.replace('PL', '') : '?';

        const card = document.createElement('div');
        card.className = 'status-card';
        card.onclick = () => {
            // For MVP, just close dashboard to show gallery
            if (!liveDashboard.classList.contains('hidden')) {
                liveDashboardBtn.click();
            }
        };

        card.innerHTML = `
            <div class="status-header">
                <div class="status-title">
                    <div class="status-indicator ${healthClass}"></div>
                    ${getMuleName(id)}
                    <span style="font-size: 0.75rem; font-weight: 400; color: var(--text-secondary);">(${id})</span>
                </div>
                <div style="font-size: 0.8rem; font-weight: 600; color: var(--text-secondary);">${healthClass.toUpperCase()}</div>
            </div>
            
            <div class="status-metrics">
                <div class="metric">
                    <span class="metric-label">Last Check-in</span>
                    <span class="metric-value">
                        <svg class="metric-icon" viewBox="0 0 24 24" width="14" height="14" stroke="currentColor" stroke-width="2" fill="none"><circle cx="12" cy="12" r="10"></circle><polyline points="12 6 12 12 16 14"></polyline></svg>
                        <span style="font-size:0.85rem">${hbDisplay}</span>
                    </span>
                </div>
                <div class="metric">
                    <span class="metric-label">Battery / Power</span>
                    <span class="metric-value">
                        <svg class="metric-icon" viewBox="0 0 24 24" width="14" height="14" stroke="currentColor" stroke-width="2" fill="none"><rect x="1" y="6" width="18" height="12" rx="2" ry="2"></rect><line x1="23" y1="13" x2="23" y2="11"></line></svg>
                        ${battery}% <span style="font-size: 0.75rem; color: var(--text-secondary);">(PL${pl})</span>
                    </span>
                </div>
                <div class="metric">
                    <span class="metric-label">Signal (RSSI)</span>
                    <span class="metric-value">
                        <svg class="metric-icon" viewBox="0 0 24 24" width="14" height="14" stroke="currentColor" stroke-width="2" fill="none"><path d="M5 12.55a11 11 0 0 1 14.08 0"></path><path d="M1.42 9a16 16 0 0 1 21.16 0"></path><path d="M8.53 16.11a6 6 0 0 1 6.95 0"></path><line x1="12" y1="20" x2="12.01" y2="20"></line></svg>
                        ${signal} dBm
                    </span>
                </div>
                <div class="metric">
                    <span class="metric-label">Recent Captures</span>
                    <span class="metric-value">
                        <svg class="metric-icon" viewBox="0 0 24 24" width="14" height="14" stroke="currentColor" stroke-width="2" fill="none"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"></rect><circle cx="8.5" cy="8.5" r="1.5"></circle><polyline points="21 15 16 10 5 21"></polyline></svg>
                        ${stats.count}
                    </span>
                </div>
            </div>
        `;
        docFrag.appendChild(card);
    });

    dashboardGrid.appendChild(docFrag);
}

function renderGallery(images) {
    loadingState.classList.add('hidden');

    if (!images || images.length === 0) {
        emptyState.classList.remove('hidden');
        toolbar.classList.add('hidden');
        updateStats(0, 0);
        return;
    }

    emptyState.classList.add('hidden');

    // Calculate stats
    totalCountEl.parentElement.classList.remove('loading-pulse');
    activeMulesEl.parentElement.classList.remove('loading-pulse');

    const uniqueMules = new Set(images.map(img => img.mule_id));
    updateStats(images.length, uniqueMules.size);

    const docFrag = document.createDocumentFragment();

    images.forEach(img => {
        const card = document.createElement('div');
        card.className = 'image-card';

        // Format Timestamp (e.g. "Mar 8, 2026 - 10:45 AM")
        const dateObj = new Date(img.timestamp);
        const dateStr = dateObj.toLocaleDateString([], { month: 'short', day: 'numeric', year: 'numeric' });
        const timeStr = dateObj.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

        // Format Size
        const kb = (img.size_bytes / 1024).toFixed(1);

        let checkboxHtml = '';
        if (isSelectMode) {
            checkboxHtml = `<input type="checkbox" class="select-checkbox" data-key="${img.key}" ${selectedKeys.has(img.key) ? 'checked' : ''} onclick="toggleImageSelection('${img.key}')">`;
        }

        const aiTags = img.ai_data && img.ai_data.tags ? img.ai_data.tags : {};
        let aiBadgesHtml = '';
        for (const [tag, count] of Object.entries(aiTags)) {
            let icon = '';
            const tLower = tag.toLowerCase();
            if (tLower.includes('deer') || tLower.includes('buck') || tLower.includes('doe')) icon = '🦌 ';
            else if (tLower.includes('raccoon')) icon = '🦝 ';
            else if (tLower.includes('bear')) icon = '🐻 ';
            else if (tLower.includes('bird') || tLower.includes('turkey')) icon = '🦃 ';
            else if (tLower.includes('person') || tLower.includes('human')) icon = '🚶 ';
            else if (tLower.includes('vehicle') || tLower.includes('car') || tLower.includes('truck') || tLower.includes('atv')) icon = '🚙 ';

            aiBadgesHtml += `<span class="badge-tag">${icon}${tag} (${count})</span>`;
        }

        // Add Weather Badges if available
        if (img.ai_data && img.ai_data.weather) {
            const w = img.ai_data.weather;
            if (w.temp !== undefined) {
                const tempF = Math.round((w.temp * 9 / 5) + 32);
                aiBadgesHtml += `<span class="badge-tag" style="background: rgba(56, 189, 248, 0.2); color: #38bdf8; border-color: rgba(56, 189, 248, 0.4);">🌡️ ${tempF}°F</span>`;
            }
            if (w.wind !== undefined) {
                const windMph = Math.round(w.wind * 0.621371);
                aiBadgesHtml += `<span class="badge-tag" style="background: rgba(148, 163, 184, 0.2); color: #94a3b8; border-color: rgba(148, 163, 184, 0.4);">💨 ${windMph} mph</span>`;
            }
            if (w.moon !== undefined) {
                let moonIcon = '🌕';
                const m = w.moon;
                if (m === 0 || m === 1) moonIcon = '🌑';
                else if (m > 0 && m < 0.25) moonIcon = '🌒';
                else if (m >= 0.25 && m < 0.5) moonIcon = '🌓';
                else if (m > 0.25 && m < 0.5) moonIcon = '🌔';
                else if (m === 0.5) moonIcon = '🌕';
                else if (m > 0.5 && m < 0.75) moonIcon = '🌖';
                else if (m >= 0.75 && m < 1.0) moonIcon = '🌗';
                else if (m > 0.75 && m < 1.0) moonIcon = '🌘';

                aiBadgesHtml += `<span class="badge-tag" style="background: rgba(24cd, 211, 77, 0.2); color: #fcd34d; border-color: rgba(252, 211, 77, 0.4);">${moonIcon}</span>`;
            }
        }

        const badgeContainer = aiBadgesHtml ? `<div class="ai-badges">${aiBadgesHtml}</div>` : '';

        card.innerHTML = `
            ${checkboxHtml}
            <div class="image-wrapper">
                ${badgeContainer}
                <div class="actions-menu">
                    <a href="${img.url}" download="${img.filename}" class="action-btn" title="Download High-Res">
                        <svg viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" stroke-width="2" fill="none"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><polyline points="7 10 12 15 17 10"></polyline><line x1="12" y1="15" x2="12" y2="3"></line></svg>
                    </a>
                    <button class="action-btn" onclick="renameImage('${img.key}')" title="Rename Capture">
                        <svg viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" stroke-width="2" fill="none"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"></path></svg>
                    </button>
                    <button class="action-btn delete-btn" onclick="deleteImage('${img.key}')" title="Delete Capture">
                        <svg viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" stroke-width="2" fill="none"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path><line x1="10" y1="11" x2="10" y2="17"></line><line x1="14" y1="11" x2="14" y2="17"></line></svg>
                    </button>
                </div>
                <picture style="cursor: zoom-in;" onclick="openLightbox('${img.url}')">
                    <source srcset="${img.url}" type="image/avif">
                    <img src="${img.url}" alt="Trail Camera Capture" loading="lazy" onerror="this.parentElement.innerHTML='<div class=\\'img-fallback-msg\\'>⚠️ Image format not supported by browser viewer.<br>Download source to view.</div>'">
                </picture>
                <div class="card-metadata">
                    <div class="meta-left">
                        <span class="mule-id" title="${img.mule_id}">${getMuleName(img.mule_id)}</span>
                        <span class="timestamp">${dateStr} • ${timeStr}</span>
                    </div>
                    <span class="file-size">${kb} KB</span>
                </div>
            </div>
        `;
        docFrag.appendChild(card);
    });

    galleryGrid.appendChild(docFrag);

    // Show/hide load more button
    if (currentNextToken) {
        loadMoreContainer.classList.remove('hidden');
    } else {
        loadMoreContainer.classList.add('hidden');
    }
}

function updateStats(total, mules) {
    totalCountEl.textContent = total;
    activeMulesEl.textContent = mules;
}

function toggleImageSelection(key) {
    if (!isSelectMode) return;
    if (selectedKeys.has(key)) selectedKeys.delete(key);
    else selectedKeys.add(key);
    updateSelectionUI();
}

function updateSelectionUI() {
    selectedCountEl.textContent = `${selectedKeys.size} selected`;
    const checkboxes = document.querySelectorAll('.select-checkbox');
    checkboxes.forEach(cb => {
        cb.checked = selectedKeys.has(cb.dataset.key);
    });
}

// Map interactions & Lightbox
function openLightbox(url) {
    if (isSelectMode) return; // Prevent full screen if just trying to check boxes
    lightboxImg.src = url;
    lightboxOverlay.classList.remove('hidden');
    lightboxOverlay.classList.add('active');
}

function closeLightbox() {
    lightboxOverlay.classList.remove('active');
    setTimeout(() => {
        lightboxOverlay.classList.add('hidden');
        lightboxImg.src = '';
    }, 300);
}

lightboxCloseBtn.addEventListener('click', closeLightbox);
lightboxOverlay.addEventListener('click', (e) => {
    if (e.target === lightboxOverlay) closeLightbox();
});

// Event Listeners
refreshBtn.addEventListener('click', () => fetchImages(false));
loadMoreBtn.addEventListener('click', () => fetchImages(true));
logoutBtn.addEventListener('click', logout);
sortSelect.addEventListener('change', applySortAndRender);
startDateInput.addEventListener('change', applySortAndRender);
endDateInput.addEventListener('change', applySortAndRender);
if (aiFilterSelect) aiFilterSelect.addEventListener('change', applySortAndRender);

dashboardBtn.addEventListener('click', () => {
    analyticsDashboard.classList.toggle('hidden');
    mainMapContainer.classList.add('hidden');
    liveDashboard.classList.add('hidden');
    mapViewBtn.style.color = '';
    mapViewBtn.style.borderColor = '';
    liveDashboardBtn.style.color = '';
    liveDashboardBtn.style.borderColor = '';

    if (!analyticsDashboard.classList.contains('hidden')) {
        dashboardBtn.style.color = 'var(--accent)';
        dashboardBtn.style.borderColor = 'var(--accent)';
        applySortAndRender(); // Re-trigger chart render mapped to current filters
    } else {
        dashboardBtn.style.color = '';
        dashboardBtn.style.borderColor = '';
    }
});

liveDashboardBtn.addEventListener('click', () => {
    liveDashboard.classList.toggle('hidden');
    analyticsDashboard.classList.add('hidden');
    mainMapContainer.classList.add('hidden');
    dashboardBtn.style.color = '';
    dashboardBtn.style.borderColor = '';
    mapViewBtn.style.color = '';
    mapViewBtn.style.borderColor = '';

    if (!liveDashboard.classList.contains('hidden')) {
        liveDashboardBtn.style.color = 'var(--accent)';
        liveDashboardBtn.style.borderColor = 'var(--accent)';
        applySortAndRender();
    } else {
        liveDashboardBtn.style.color = '';
        liveDashboardBtn.style.borderColor = '';
    }
});

mapViewBtn.addEventListener('click', () => {
    mainMapContainer.classList.toggle('hidden');
    analyticsDashboard.classList.add('hidden');
    liveDashboard.classList.add('hidden');
    dashboardBtn.style.color = '';
    dashboardBtn.style.borderColor = '';
    liveDashboardBtn.style.color = '';
    liveDashboardBtn.style.borderColor = '';

    if (!mainMapContainer.classList.contains('hidden')) {
        mapViewBtn.style.color = 'var(--accent)';
        mapViewBtn.style.borderColor = 'var(--accent)';
        applySortAndRender(); // Render map points
    } else {
        mapViewBtn.style.color = '';
        mapViewBtn.style.borderColor = '';
    }
});

themeToggleBtn.addEventListener('click', () => {
    document.body.classList.toggle('light-mode');
    const isLight = document.body.classList.contains('light-mode');
    localStorage.setItem('woods_theme', isLight ? 'light' : 'dark');

    // Update Icons
    if (isLight) {
        themeIconSun.classList.add('hidden');
        themeIconMoon.classList.remove('hidden');
    } else {
        themeIconSun.classList.remove('hidden');
        themeIconMoon.classList.add('hidden');
    }

    // Update chart colors if they are visible
    if (!analyticsDashboard.classList.contains('hidden') || !liveDashboard.classList.contains('hidden')) {
        applySortAndRender();
    }
});

toggleSelectModeBtn.addEventListener('click', () => {
    isSelectMode = !isSelectMode;
    selectedKeys.clear();

    if (isSelectMode) {
        toggleSelectModeBtn.textContent = 'Cancel Selection';
        bulkActions.classList.remove('hidden');
    } else {
        toggleSelectModeBtn.textContent = 'Select Items';
        bulkActions.classList.add('hidden');
    }

    updateSelectionUI();
    applySortAndRender(); // Re-render to inject/remove checkboxes
});

// --- Image Management ---
async function deleteImage(key) {
    if (!confirm("Are you sure you want to delete this capture? This cannot be undone.")) return;

    try {
        const response = await fetch(`${API_BASE_URL}/manage-image`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${AUTH_TOKEN}`
            },
            body: JSON.stringify({ action: 'delete', key: key })
        });

        if (!response.ok) throw new Error("Delete failed");

        // Refresh UI
        fetchImages();
    } catch (err) {
        alert("Failed to delete image.");
        console.error(err);
    }
}

async function renameImage(key) {
    const oldName = key.split('/').pop();
    const newName = prompt("Enter a new filename (must end in .avif):", oldName);

    if (!newName || newName === oldName) return;
    if (!newName.toLowerCase().endsWith('.avif')) {
        alert("Filename must retain the .avif extension.");
        return;
    }

    // Construct new key
    const parts = key.split('/');
    parts.pop(); // Remove old filename
    parts.push(newName);
    const newKey = parts.join('/');

    try {
        const response = await fetch(`${API_BASE_URL}/manage-image`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${AUTH_TOKEN}`
            },
            body: JSON.stringify({ action: 'rename', key: key, new_key: newKey })
        });

        if (!response.ok) throw new Error("Rename failed");

        // Refresh UI
        fetchImages();
    } catch (err) {
        alert("Failed to rename image.");
        console.error(err);
    }
}

// --- Bulk Actions ---
bulkDownloadBtn.addEventListener('click', () => {
    if (selectedKeys.size === 0) return;
    const selectedImages = cachedImages.filter(img => selectedKeys.has(img.key));

    selectedImages.forEach((img, index) => {
        // Stagger programmatic downloads slightly
        setTimeout(() => {
            const a = document.createElement('a');
            a.href = img.url;
            a.download = img.filename;
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
        }, index * 300);
    });

    toggleSelectModeBtn.click(); // Exit mode
});

bulkDeleteBtn.addEventListener('click', async () => {
    if (selectedKeys.size === 0) return;
    if (!confirm(`Are you sure you want to delete ${selectedKeys.size} captures?`)) return;

    try {
        bulkDeleteBtn.textContent = "Deleting...";
        bulkDeleteBtn.disabled = true;

        const response = await fetch(`${API_BASE_URL}/manage-image`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${AUTH_TOKEN}`
            },
            body: JSON.stringify({ action: 'bulk_delete', keys: Array.from(selectedKeys) })
        });

        if (!response.ok) throw new Error("Bulk delete failed");

        // Refresh UI
        selectedKeys.clear();
        isSelectMode = false;
        toggleSelectModeBtn.textContent = 'Select Items';
        bulkActions.classList.add('hidden');
        fetchImages(false);
    } catch (err) {
        alert("Failed to delete images.");
        console.error(err);
    } finally {
        bulkDeleteBtn.textContent = "Delete";
        bulkDeleteBtn.disabled = false;
    }
});



generateTimelapseBtn.addEventListener('click', async () => {
    // Only allow if we have active mules
    const uniqueMules = [...new Set(cachedImages.map(img => img.mule_id))];
    if (uniqueMules.length === 0) {
        alert("No cameras available.");
        return;
    }

    // Create a simple prompt message listing available IDs
    const muleList = uniqueMules.map(id => `${id} (${getMuleName(id)})`).join('\n');
    let promptMsg = `Enter the Camera ID to generate a timelapse for:\n\nAvailable Cameras:\n${muleList}`;

    const targetMule = prompt(promptMsg);
    if (!targetMule) return;

    // Verify it exists in our list
    const actualId = targetMule.trim().toUpperCase();
    if (!uniqueMules.includes(actualId) && !Object.values(muleMappings).some(m => m.name === targetMule || m === targetMule)) {
        alert("Invalid Camera ID.");
        return;
    }

    // Resolve name back to ID if they typed the human name
    let finalId = actualId;
    for (const [id, data] of Object.entries(muleMappings)) {
        if ((typeof data === 'object' && data.name === targetMule) || data === targetMule) {
            finalId = id;
            break;
        }
    }

    generateTimelapseBtn.disabled = true;
    generateTimelapseBtn.innerHTML = '<div class="spinner" style="width: 14px; height: 14px; border-width: 2px;"></div>';

    try {
        const response = await fetch(`${API_BASE_URL}/generate-timelapse`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${AUTH_TOKEN}` },
            body: JSON.stringify({ mule_id: finalId, fps: 5 })
        });

        const data = await response.json();
        if (!response.ok) throw new Error(data.error || "Generation failed");

        // Success - trigger download
        alert(`Success! Generated timelapse with ${data.frames} frames.`);
        const a = document.createElement('a');
        a.href = data.url;
        a.download = data.filename;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);

    } catch (err) {
        alert(`Failed to generate timelapse: ${err.message}`);
        console.error(err);
    } finally {
        generateTimelapseBtn.disabled = false;
        generateTimelapseBtn.innerHTML = `
            <svg viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" stroke-width="2" fill="none">
                <polygon points="23 7 16 12 23 17 23 7"></polygon>
                <rect x="1" y="5" width="15" height="14" rx="2" ry="2"></rect>
            </svg>
        `;
    }
});

// --- Mule Configuration ---
configBtn.addEventListener('click', () => {
    renderMappingsList();
    configOverlay.classList.remove('hidden');
    configOverlay.classList.add('active');

    // Initialize map on first open
    setTimeout(() => {
        if (!configMap) {
            configMap = L.map('config-map').setView([39.8283, -98.5795], 4);
            L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
                attribution: '© OpenStreetMap contributors'
            }).addTo(configMap);

            configMap.on('click', (e) => {
                const lat = e.latlng.lat.toFixed(6);
                const lng = e.latlng.lng.toFixed(6);
                newMuleLatInput.value = lat;
                newMuleLngInput.value = lng;

                if (configTempMarker) configMap.removeLayer(configTempMarker);
                configTempMarker = L.marker([lat, lng]).addTo(configMap);
            });
        } else {
            configMap.invalidateSize();
        }
    }, 100);
});

closeConfigBtn.addEventListener('click', () => {
    configOverlay.classList.remove('active');
    setTimeout(() => configOverlay.classList.add('hidden'), 300);
});

function renderMappingsList() {
    mappingsList.innerHTML = '';
    for (const [id, data] of Object.entries(muleMappings)) {
        const name = typeof data === 'object' ? data.name : data;
        const loc = typeof data === 'object' && data.lat ? ` <span style="font-size:0.75rem; color:var(--text-secondary);">(${data.lat}, ${data.lng})</span>` : '';

        const row = document.createElement('div');
        row.style.display = 'flex';
        row.style.justifyContent = 'space-between';
        row.style.marginBottom = '0.5rem';
        row.style.alignItems = 'center';
        row.innerHTML = `
            <span><strong>${id}</strong> = ${name}${loc}</span>
            <button class="btn-outline" style="padding: 0.2rem 0.5rem; color: var(--error); border-color: rgba(239, 68, 68, 0.5);" onclick="removeMapping('${id}')">Remove</button>
        `;
        mappingsList.appendChild(row);
    }
}

window.removeMapping = function (id) {
    delete muleMappings[id];
    renderMappingsList();
};

addMappingBtn.addEventListener('click', () => {
    const id = newMuleIdInput.value.trim().toUpperCase();
    const name = newMuleNameInput.value.trim();
    const lat = newMuleLatInput.value;
    const lng = newMuleLngInput.value;

    if (id && name) {
        if (lat && lng) {
            muleMappings[id] = { name: name, lat: parseFloat(lat), lng: parseFloat(lng) };
        } else {
            muleMappings[id] = { name: name };
        }

        newMuleIdInput.value = '';
        newMuleNameInput.value = '';
        newMuleLatInput.value = '';
        newMuleLngInput.value = '';
        if (configTempMarker) configMap.removeLayer(configTempMarker);
        renderMappingsList();
    }
});

saveConfigBtn.addEventListener('click', async () => {
    saveConfigBtn.textContent = "Saving...";
    saveConfigBtn.disabled = true;

    try {
        const p1 = fetch(`${API_BASE_URL}/manage-image`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${AUTH_TOKEN}`
            },
            body: JSON.stringify({ action: 'save_mappings', mappings: muleMappings })
        });

        let prefsPayload = null;
        if (alertPersonCheckbox && alertBuckCheckbox) {
            prefsPayload = {
                alert_person: alertPersonCheckbox.checked,
                alert_buck: alertBuckCheckbox.checked
            };
        }

        const p2 = prefsPayload ? fetch(`${API_BASE_URL}/manage-image`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${AUTH_TOKEN}`
            },
            body: JSON.stringify({ action: 'save_notification_prefs', prefs: prefsPayload })
        }) : Promise.resolve({ ok: true });

        const [res1, res2] = await Promise.all([p1, p2]);

        if (!res1.ok || !res2.ok) throw new Error("Save failed");

        closeConfigBtn.click();
        applySortAndRender(); // Re-render gallery with new names
    } catch (err) {
        alert("Failed to save configuration.");
        console.error(err);
    } finally {
        saveConfigBtn.textContent = "Save to Cloud";
        saveConfigBtn.disabled = false;
    }
});

// --- Main Map Rendering ---
function renderMap(images) {
    if (!mainMap) {
        mainMap = L.map('main-map').setView([39.8283, -98.5795], 4);
        L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
            attribution: '© OpenStreetMap contributors'
        }).addTo(mainMap);
        mainMarkerLayer = L.featureGroup().addTo(mainMap);
    }

    mainMarkerLayer.clearLayers();

    const cameraStats = {};
    images.forEach(img => {
        const id = img.mule_id;
        if (!cameraStats[id]) {
            cameraStats[id] = { count: 0, latestImage: img, bucks: 0, hunters: 0 };
        }
        cameraStats[id].count++;

        if (img.ai_data && img.ai_data.tags) {
            const tags = Object.keys(img.ai_data.tags).map(t => t.toLowerCase());
            if (tags.some(t => t.includes('buck'))) cameraStats[id].bucks++;
            if (tags.some(t => t.includes('human') || t.includes('person'))) cameraStats[id].hunters++;
        }

        if (new Date(img.timestamp) > new Date(cameraStats[id].latestImage.timestamp)) {
            cameraStats[id].latestImage = img;
        }
    });

    let hasValidPins = false;

    for (const [id, stats] of Object.entries(cameraStats)) {
        const loc = getMuleLocation(id);
        if (loc && loc.lat && loc.lng) {
            hasValidPins = true;
            const name = getMuleName(id);
            const thumbUrl = stats.latestImage.url;

            let color = '#3b82f6';
            if (stats.hunters > 0) color = '#ef4444';
            else if (stats.bucks > 0) color = '#f59e0b';
            else if (stats.count > 10) color = '#10b981';

            const marker = L.circleMarker([loc.lat, loc.lng], {
                radius: Math.min(10 + (stats.count * 0.5), 30),
                fillColor: color,
                color: '#fff',
                weight: 2,
                fillOpacity: 0.7
            });

            const popupContent = `
                <div style="text-align: center; min-width: 150px;">
                    <div style="font-weight: bold; margin-bottom: 5px; color: #000;">${name}</div>
                    <img src="${thumbUrl}" style="width: 100%; height: 100px; object-fit: cover; border-radius: 4px; border: 1px solid #ccc; margin-bottom: 5px;">
                    <div style="font-size: 0.8rem; color: #555;">
                        Recent Activity: ${stats.count} Captures<br>
                        ${stats.bucks > 0 ? `<span style="color: #d97706; font-weight: bold;">🦌 Bucks: ${stats.bucks}</span><br>` : ''}
                        ${stats.hunters > 0 ? `<span style="color: #dc2626; font-weight: bold;">🚶 Humans: ${stats.hunters}</span>` : ''}
                    </div>
                </div>
            `;

            marker.bindPopup(popupContent);
            mainMarkerLayer.addLayer(marker);
        }
    }

    setTimeout(() => {
        mainMap.invalidateSize();
        if (hasValidPins) {
            mainMap.fitBounds(mainMarkerLayer.getBounds(), { padding: [50, 50], maxZoom: 16 });
        }
    }, 100);
}

// Boot
init();
