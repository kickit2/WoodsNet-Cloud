window.addEventListener('error', function (e) {
    var errDiv = document.createElement('div');
    errDiv.style = "padding: 20px; color: red; background: white; z-index: 9999; position: fixed; top: 0; left: 0; right: 0; font-size: 14px; text-align: left; border-bottom: 3px solid red;";
    errDiv.innerHTML = `<h2>JS Error</h2><p>${e.message}</p><pre>${e.error ? e.error.stack : ''}</pre>`;
    document.body.appendChild(errDiv);
});
window.addEventListener('unhandledrejection', function (e) {
    var errDiv = document.createElement('div');
    errDiv.style = "padding: 20px; color: red; background: white; z-index: 9999; position: fixed; top: 0; left: 0; right: 0; font-size: 14px; text-align: left; border-bottom: 3px solid red;";
    errDiv.innerHTML = `<h2>Promise Error</h2><p>${e.reason}</p>`;
    document.body.appendChild(errDiv);
});

// App configuration
// In production, this URL would be set dynamically. For testing, we mock it.
let API_BASE_URL = localStorage.getItem('woods_api_url') || 'https://iwsscp4o5f.execute-api.us-east-1.amazonaws.com';
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
const muleFilter = document.getElementById('mule-filter');
const aiFilterCheckboxes = document.querySelectorAll('.ai-filter-cb');
const aiSearchInput = document.getElementById('ai-search');

const settingsDashboard = document.getElementById('settings-dashboard');
const configBtn = document.getElementById('config-btn');
const closeSettingsBtn = document.getElementById('close-settings-btn');
const settingsTabBtns = document.querySelectorAll('.settings-tab-btn');
const settingsTabs = document.querySelectorAll('.settings-tab');
const mappingsList = document.getElementById('mappings-list');
const addMappingBtn = document.getElementById('add-mapping-btn');
const newMuleIdInput = document.getElementById('new-mule-id');
const newMuleNameInput = document.getElementById('new-mule-name');
const newMuleLatInput = document.getElementById('new-mule-lat');
const newMuleLngInput = document.getElementById('new-mule-lng');
const saveGeneralBtn = document.getElementById('save-general-btn');
const configPortalNameInput = document.getElementById('config-portal-name');
const configPortalPasswordInput = document.getElementById('config-portal-password');

// Initialize
const savedTheme = localStorage.getItem('woods_theme') || 'dark';
if (savedTheme === 'light') {
    document.body.classList.add('light-mode');
    if (themeIconSun) themeIconSun.classList.add('hidden');
    if (themeIconMoon) themeIconMoon.classList.remove('hidden');
}

async function initPortalBrand() {
    if (!API_BASE_URL) return;
    try {
        const response = await fetch(`${API_BASE_URL}/list-images`, {
            headers: { 'Authorization': 'Bearer ' }
        });
        if (response.status === 401) {
            const errData = await response.json().catch(() => ({}));
            if (errData.portal_name) {
                document.title = errData.portal_name;
                const loginTitle = document.getElementById('login-portal-title');
                const headerTitle = document.getElementById('header-portal-title');
                if (loginTitle) loginTitle.textContent = errData.portal_name;
                if (headerTitle) headerTitle.textContent = errData.portal_name;
                if (configPortalNameInput) configPortalNameInput.value = errData.portal_name;
            }
        }
    } catch (e) {
        console.warn("Could not fetch portal brand", e);
    }
}

function init() {
    if (AUTH_TOKEN && API_BASE_URL) {
        showApp();
        fetchImages();
    } else {
        if (AUTH_TOKEN) {
            AUTH_TOKEN = '';
            localStorage.removeItem('woods_auth_token');
        }
        showAuth();
        initPortalBrand();
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

            if (data.portal_name) {
                document.title = data.portal_name;
                const loginTitle = document.getElementById('login-portal-title');
                const headerTitle = document.getElementById('header-portal-title');
                if (loginTitle) loginTitle.textContent = data.portal_name;
                if (headerTitle) headerTitle.textContent = data.portal_name;
                if (configPortalNameInput) configPortalNameInput.value = data.portal_name;
            }

            await fetchSubscribers();
            showApp();
            applySortAndRender();
        } else {
            if (response.status === 401) {
                const errData = await response.json().catch(() => ({}));
                if (errData.portal_name) {
                    document.title = errData.portal_name;
                    const loginTitle = document.getElementById('login-portal-title');
                    if (loginTitle) loginTitle.textContent = errData.portal_name;
                }
            }
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

// UI Macros Listener System
const macroDeer = document.getElementById('macro-select-deer');
const macroPeople = document.getElementById('macro-select-people');
const macroClear = document.getElementById('macro-clear-all');

if (macroDeer) {
    macroDeer.addEventListener('click', (e) => {
        e.preventDefault();
        // Reaching into the DOM structure next to the Macros for the camera rows
        // The routing list is directly adjacent to the Global Macros div
        const routingContainer = macroDeer.parentElement.parentElement;
        const checkboxes = routingContainer.querySelectorAll('label');
        checkboxes.forEach(label => {
            if (label.textContent.includes('Buck Alerts')) {
                label.querySelector('input').checked = true;
            }
        });
    });
}

if (macroPeople) {
    macroPeople.addEventListener('click', (e) => {
        e.preventDefault();
        const routingContainer = macroPeople.parentElement.parentElement;
        const checkboxes = routingContainer.querySelectorAll('label');
        checkboxes.forEach(label => {
            if (label.textContent.includes('People Alerts')) {
                label.querySelector('input').checked = true;
            }
        });
    });
}

if (macroClear) {
    macroClear.addEventListener('click', (e) => {
        e.preventDefault();
        const routingContainer = macroClear.parentElement.parentElement;
        const checkboxes = routingContainer.querySelectorAll('input[type="checkbox"]');
        checkboxes.forEach(checkbox => checkbox.checked = false);
    });
}

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
    if (!API_BASE_URL || !AUTH_TOKEN) {
        console.error("fetchImages aborted: missing API_BASE_URL or AUTH_TOKEN");
        return;
    }

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
            populateMuleFilter(cachedImages);

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

function populateMuleFilter(images) {
    if (!muleFilter) return;
    const uniqueMules = [...new Set(images.map(img => img.mule_id))].sort((a, b) => getMuleName(a).localeCompare(getMuleName(b)));

    const currentSelection = muleFilter.value;
    muleFilter.innerHTML = '<option value="all">All Cameras</option>';
    uniqueMules.forEach(id => {
        const option = document.createElement('option');
        option.value = id;
        option.textContent = getMuleName(id);
        muleFilter.appendChild(option);
    });

    if (uniqueMules.includes(currentSelection)) {
        muleFilter.value = currentSelection;
    }
}

// Rendering & Sorting
let activityChartInstance = null;
let cameraChartInstance = null;

function applySortAndRender() {
    const sortBy = sortSelect.value;
    const startDate = startDateInput.value ? new Date(startDateInput.value) : null;
    let endDate = endDateInput.value ? new Date(endDateInput.value) : null;
    const activeAiFilters = Array.from(aiFilterCheckboxes).filter(cb => cb.checked).map(cb => cb.value);
    const tagSearchText = aiSearchInput ? aiSearchInput.value.toLowerCase().trim() : '';
    const searchTags = tagSearchText ? tagSearchText.split(',').map(s => s.trim()).filter(s => s) : [];

    if (endDate) {
        endDate.setHours(23, 59, 59, 999);
    }

    // Filter
    let filteredImages = cachedImages.filter(img => {
        if (muleFilter && muleFilter.value !== 'all') {
            if (img.mule_id !== muleFilter.value) return false;
        }

        const imgDate = new Date(img.timestamp);
        if (startDate && imgDate < startDate) return false;
        if (endDate && imgDate > endDate) return false;

        if (searchTags.length > 0) {
            if (!img.ai_data || !img.ai_data.tags) return false;
            const imgTags = Object.keys(img.ai_data.tags).map(t => t.toLowerCase());
            // AND logic: every search tag must match at least one imgTag
            const matchesAll = searchTags.every(searchTag => imgTags.some(t => t.includes(searchTag)));
            if (!matchesAll) return false;
        }

        let passesAiFilter = false;

        // If an image is awaiting ID, ONLY the 'awaiting' checkbox can keep it visible.
        // It should not accidentally pass because it technically matches 'empty' (0 tags).
        if (img.ai_data && img.ai_data.awaiting_id) {
            if (activeAiFilters.includes('awaiting')) passesAiFilter = true;
        } else {
            // It has been fully analyzed. Check the other categories.
            if (activeAiFilters.includes('empty') && (!img.ai_data || img.ai_data.has_animals === false)) {
                passesAiFilter = true;
            }

            const tags = (img.ai_data && img.ai_data.tags) ? Object.keys(img.ai_data.tags) : [];

            const hasDeer = tags.some(t => t.includes('Doe/Young') || t.includes('Deer'));
            const hasBuck = tags.some(t => t.includes('Antlered Buck'));
            const hasPeople = tags.some(t => t.includes('Person') || t.includes('Human') || t.includes('People'));
            const hasOther = tags.some(t => !t.includes('Doe/Young') && !t.includes('Deer') && !t.includes('Antlered Buck') && !t.includes('Person') && !t.includes('Human') && !t.includes('People')) && img.ai_data.has_animals;

            if (activeAiFilters.includes('deer') && hasDeer) passesAiFilter = true;
            if (activeAiFilters.includes('bucks') && hasBuck) passesAiFilter = true;
            if (activeAiFilters.includes('people') && hasPeople) passesAiFilter = true;
            if (activeAiFilters.includes('animals') && hasOther) passesAiFilter = true;
        }

        // If NO filter boxes are checked, we hide everything
        if (!passesAiFilter && activeAiFilters.length > 0) return false;

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

    if (filteredImages.length > 0) {
        // Continue showing rendered views
    }

    if (!analyticsDashboard.classList.contains('hidden')) {
        renderCharts(filteredImages);
    }

    if (!liveDashboard.classList.contains('hidden')) {
        renderLiveDashboard(filteredImages);
    }

    if (!mainMapContainer.classList.contains('hidden')) {
        renderMap(filteredImages);
    }

    const isAnyDashboardVisible = !analyticsDashboard.classList.contains('hidden') ||
        !liveDashboard.classList.contains('hidden') ||
        !mainMapContainer.classList.contains('hidden');

    if (isAnyDashboardVisible) {
        toolbar.classList.add('hidden');
        galleryGrid.classList.add('hidden');
        emptyState.classList.add('hidden');
        loadMoreContainer.classList.add('hidden');
    } else {
        toolbar.classList.remove('hidden');
        galleryGrid.classList.remove('hidden');
        renderGallery(filteredImages);
    }
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
            dateCounts[dateStr] = { person: 0, buck: 0, doe: 0, other: 0, empty: 0, awaiting: 0 };
        }

        let hasPerson = false;
        let hasBuck = false;
        let hasDoe = false;
        let hasOther = false;
        let isAwaiting = img.ai_data && img.ai_data.awaiting_id === true;

        if (img.ai_data && img.ai_data.tags) {
            for (const key of Object.keys(img.ai_data.tags)) {
                if (key.includes('Person') || key.includes('Human') || key.includes('People')) hasPerson = true;
                else if (key === 'Antlered Buck') hasBuck = true;
                else if (key === 'Doe/Young') hasDoe = true;
                else hasOther = true;
            }
        }

        if (isAwaiting) dateCounts[dateStr].awaiting++;
        else if (hasPerson) dateCounts[dateStr].person++;
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
    const awaitingData = sortedDates.map(d => dateCounts[d].awaiting);

    const ctxActivity = document.getElementById('activityChart').getContext('2d');
    activityChartInstance = new Chart(ctxActivity, {
        type: 'bar',
        data: {
            labels: sortedDates,
            datasets: [
                { label: 'Awaiting ID', data: awaitingData, backgroundColor: '#facc15' },
                { label: 'People / Hunters', data: personData, backgroundColor: '#f97316' },
                { label: 'Antlered Bucks', data: buckData, backgroundColor: '#ef4444' },
                { label: 'Does / Young', data: doeData, backgroundColor: '#f472b6' },
                { label: 'Other Wildlife', data: otherData, backgroundColor: '#38bdf8' },
                { label: 'Empty (No Animal)', data: emptyData, backgroundColor: '#94a3b8' }
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
        galleryGrid.innerHTML = '';
        emptyState.classList.remove('hidden');
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
    galleryGrid.innerHTML = ''; // Clear previous images before re-rendering

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

        if (img.ai_data && img.ai_data.awaiting_id === true) {
            aiBadgesHtml += `<span class="badge-tag" style="background: rgba(250, 204, 21, 0.2); color: #facc15; border-color: rgba(250, 204, 21, 0.4);" title="Image has not been analyzed yet">⏳ Awaiting ID</span>`;
        } else {
            for (const [tag, count] of Object.entries(aiTags)) {
                let icon = '';
                const tLower = tag.toLowerCase();
                if (tLower.includes('deer') || tLower.includes('buck') || tLower.includes('doe')) icon = '🦌 ';
                else if (tLower.includes('raccoon')) icon = '🦝 ';
                else if (tLower.includes('bear')) icon = '🐻 ';
                else if (tLower.includes('bird') || tLower.includes('turkey')) icon = '🦃 ';
                else if (tLower.includes('person') || tLower.includes('human')) icon = '🚶 ';
                else if (tLower.includes('vehicle') || tLower.includes('car') || tLower.includes('truck') || tLower.includes('atv')) icon = '🚙 ';

                // Use window.searchTag global function to allow auto-labeling filter
                aiBadgesHtml += `<span class="badge-tag" style="cursor: pointer;" onclick="searchTag('${tag}')" title="Search this tag">${icon}${tag} (${count})</span>`;
            }
            if (Object.keys(aiTags).length === 0 && (!img.ai_data || !img.ai_data.has_animals)) {
                aiBadgesHtml += `<span class="badge-tag" style="background: rgba(148, 163, 184, 0.2); color: #94a3b8; border-color: rgba(148, 163, 184, 0.4);" title="No wildlife detected">∅ Empty</span>`;
            }
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

                aiBadgesHtml += `<span class="badge-tag" style="background: rgba(252, 211, 77, 0.2); color: #fcd34d; border-color: rgba(252, 211, 77, 0.4);">${moonIcon}</span>`;
            }
        }

        const badgeContainer = aiBadgesHtml ? `<div class="ai-badges">${aiBadgesHtml}</div>` : '';

        card.innerHTML = `
            ${checkboxHtml}
            <div class="image-wrapper">
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
            </div>
            
            <div style="padding: 0 0.5rem 0.5rem 0.5rem;">
                ${badgeContainer}
                <div class="card-metadata">
                    <div class="meta-row">
                        <span class="mule-id" title="${img.mule_id}">${getMuleName(img.mule_id)}</span>
                    </div>
                    <div class="meta-row meta-split">
                        <span class="card-filename" title="${img.filename}">${img.filename}</span>
                        <span class="file-size">${kb} KB</span>
                    </div>
                    <div class="meta-row">
                        <span class="timestamp">${dateStr} • ${timeStr}</span>
                    </div>
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
if (muleFilter) muleFilter.addEventListener('change', () => { currentNextToken = null; applySortAndRender(); });
aiFilterCheckboxes.forEach(cb => cb.addEventListener('change', applySortAndRender));

if (aiSearchInput) {
    aiSearchInput.addEventListener('input', () => {
        if (window.searchTimeout) clearTimeout(window.searchTimeout);
        window.searchTimeout = setTimeout(applySortAndRender, 300);
    });
}

window.searchTag = function (tagStr) {
    if (!aiSearchInput) return;
    let currentVal = aiSearchInput.value.trim();
    let cleanTag = tagStr.replace(/^[^\w\s]+/, '').trim();

    if (!currentVal) {
        aiSearchInput.value = cleanTag;
    } else if (!currentVal.toLowerCase().includes(cleanTag.toLowerCase())) {
        aiSearchInput.value = currentVal + ', ' + cleanTag;
    }
    window.scrollTo({ top: 0, behavior: 'smooth' });
    applySortAndRender();
};

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

// --- Settings Dashboard ---
configBtn.addEventListener('click', () => {
    renderMappingsList();
    appContent.classList.add('hidden');

    // Hide other fullscreens if open
    analyticsDashboard.classList.add('hidden');
    liveDashboard.classList.add('hidden');
    mainMapContainer.classList.add('hidden');

    settingsDashboard.classList.remove('hidden');

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
            // Only invalidate if the map tab is active
            const activeTab = document.querySelector('.settings-tab-btn.active');
            if (activeTab && activeTab.getAttribute('data-target') === 'settings-fleet') {
                configMap.invalidateSize();
            }
        }
    }, 100);
});

closeSettingsBtn.addEventListener('click', () => {
    settingsDashboard.classList.add('hidden');
    appContent.classList.remove('hidden');
    applySortAndRender(); // restore gallery view
});
// Setup tab switching logic
document.querySelectorAll('.settings-tab-btn').forEach(btn => {
    btn.addEventListener('click', () => {
        // Remove active class from all buttons
        document.querySelectorAll('.settings-tab-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');

        // Hide all tabs
        document.querySelectorAll('.settings-tab').forEach(t => t.classList.add('hidden'));

        // Show target tab
        const targetId = btn.getAttribute('data-target');
        const targetTab = document.getElementById(targetId);
        if (targetTab) targetTab.classList.remove('hidden');

        // If map tab, invalidate size to prevent gray boxes
        if (targetId === 'settings-fleet' && configMap) {
            setTimeout(() => configMap.invalidateSize(), 100);
        }
    });
});

function renderMappingsList() {
    mappingsList.innerHTML = '';

    // Collect all known mules from mappings AND from active images
    const activeMulesFromImages = new Set(cachedImages.map(img => img.mule_id));
    const allMuleIds = new Set([...Object.keys(muleMappings), ...activeMulesFromImages]);

    for (const id of Array.from(allMuleIds).sort()) {
        const data = muleMappings[id];
        const name = (data && typeof data === 'object') ? data.name : (data || id);
        const loc = (data && typeof data === 'object' && data.lat) ? ` <span style="font-size:0.7rem; color:var(--text-secondary); white-space:nowrap;">(${data.lat}, ${data.lng})</span>` : '';

        const row = document.createElement('div');
        row.style.display = 'flex';
        row.style.flexWrap = 'wrap';
        row.style.justifyContent = 'space-between';
        row.style.marginBottom = '0.8rem';
        row.style.alignItems = 'center';
        row.style.gap = '0.5rem';
        row.innerHTML = `
            <strong style="min-width: 65px; font-size: 0.9rem;">${id}</strong>
            <input type="text" class="mule-rename-input" data-id="${id}" value="${name !== id ? name : ''}" placeholder="Custom Name" style="flex:1; padding: 0.3rem 0.5rem; font-size: 0.85rem; border-radius:3px; border:1px solid var(--border); background:var(--bg-content); color:var(--text-main);">
            ${loc}
            <button class="btn-outline" style="padding: 0.2rem 0.4rem; font-size: 0.8rem; color: var(--error); border-color: rgba(239, 68, 68, 0.5);" onclick="removeMapping('${id}')" title="Delete Saved Mapping">X</button>
        `;
        mappingsList.appendChild(row);
    }

    // Add event listeners to all rename inputs to live-update the mapping dictionary
    document.querySelectorAll('.mule-rename-input').forEach(input => {
        input.addEventListener('change', (e) => {
            const id = e.target.dataset.id;
            const newName = e.target.value.trim();
            if (newName) {
                if (typeof muleMappings[id] === 'object') {
                    muleMappings[id].name = newName;
                } else {
                    muleMappings[id] = newName;
                }
            } else {
                // Remove name mapping if cleared, preserving location if exists
                if (typeof muleMappings[id] === 'object') {
                    muleMappings[id].name = id;
                } else {
                    delete muleMappings[id];
                }
            }
            // Trigger UI update natively
            populateMuleFilter(cachedImages);
            applySortAndRender();
        });
    });
}

window.removeMapping = function (id) {
    delete muleMappings[id];
    renderMappingsList();
    populateMuleFilter(cachedImages);
    applySortAndRender();
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

const addSubscriberBtn = document.getElementById('add-subscriber-btn');
if (addSubscriberBtn) {
    addSubscriberBtn.addEventListener('click', () => {
        // Scrape current DOM state
        const currentDeps = buildSubscribersPayload();

        // Push a fresh blank subscriber
        currentDeps.push({
            id: 'sub-' + Date.now(),
            name: '',
            active: true,
            contact_sms: '',
            contact_email: '',
            routing: {}
        });

        // Re-render the UI matrix
        renderSubscribers(currentDeps);
    });
}

async function fetchSubscribers() {
    try {
        const response = await fetch(`${API_BASE_URL}/manage-image`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${AUTH_TOKEN}` },
            body: JSON.stringify({ action: 'get_subscribers' })
        });
        if (response.ok) {
            const data = await response.json();
            renderSubscribers(data.subscribers || []);
        }
    } catch (err) {
        console.error("Failed to fetch subscribers:", err);
    }
}

function renderSubscribers(subscribers) {
    const container = document.getElementById('subscribers-container');
    if (!container) return;
    container.innerHTML = '';

    subscribers.forEach(sub => {
        const subId = sub.id || 'unknown';
        const card = document.createElement('div');
        card.className = 'subscriber-card';
        card.setAttribute('data-sub-id', subId);
        card.setAttribute('data-sub-name', sub.name || '');
        card.style.cssText = 'border: 1px solid var(--border); border-radius: var(--radius-md); padding: 1.5rem; background: rgba(0,0,0,0.1); margin-bottom: 1.5rem;';

        let routingHtml = '';
        const allCameras = Object.keys(muleMappings).length > 0 ? Object.keys(muleMappings) : Object.keys(sub.routing || {});

        allCameras.forEach(camId => {
            const camName = (muleMappings[camId] && muleMappings[camId].name) ? muleMappings[camId].name : camId;
            const activeTags = (sub.routing && sub.routing[camId]) ? sub.routing[camId] : [];

            const buckChecked = activeTags.includes('Antlered Buck') ? 'checked' : '';
            const peopleChecked = activeTags.includes('Person') ? 'checked' : '';

            routingHtml += `
            <div style="display: flex; flex-direction: column; gap: 0.5rem; padding-bottom: 0.75rem; border-bottom: 1px solid rgba(255,255,255,0.05);">
                <div style="display: flex; justify-content: space-between; align-items: center;">
                    <div style="font-weight: 500;">${camId} (${camName})</div>
                </div>
                <div style="display: flex; gap: 1rem; flex-wrap: wrap;">
                    <label style="display: flex; align-items: center; gap: 0.5rem; font-size: 0.875rem; color: var(--text-secondary);">
                        <input type="checkbox" class="route-checkbox" data-mule="${camId}" data-tag="Person" ${peopleChecked}> People Alerts
                    </label>
                    <label style="display: flex; align-items: center; gap: 0.5rem; font-size: 0.875rem; color: var(--text-secondary);">
                        <input type="checkbox" class="route-checkbox" data-mule="${camId}" data-tag="Antlered Buck" ${buckChecked}> Buck Alerts
                    </label>
                </div>
            </div>`;
        });

        if (routingHtml === '') routingHtml = '<div style="color:var(--text-secondary);font-size:0.875rem;">No cameras available for routing.</div>';

        card.innerHTML = `
            <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 1rem; margin-bottom: 1rem; padding-bottom: 1rem; border-bottom: 1px solid var(--border);">
                <div style="display: flex; align-items: center; gap: 1rem;">
                    <input type="text" class="sub-name-input" value="${sub.name || ''}" placeholder="Subscriber Name" style="padding: 0.3rem 0.5rem; font-size: 1.1rem; font-weight: bold; border-radius:3px; border:1px solid var(--border); background:rgba(0,0,0,0.2); color:var(--text-main); width: 150px;">
                    <label style="display: flex; align-items: center; gap: 0.5rem; font-size: 0.875rem;">
                        <input type="checkbox" class="sub-active" ${sub.active ? 'checked' : ''}> Active
                    </label>
                </div>
                <div style="display: flex; gap: 1rem; flex-wrap: wrap;">
                    <div style="display:flex; flex-direction:column; gap:0.25rem;">
                        <span style="font-size:0.75rem;color:var(--text-secondary);">SMS</span>
                        <input type="text" class="sub-sms-input" value="${sub.contact_sms || ''}" placeholder="+15551234567" style="padding: 0.3rem 0.5rem; font-size: 0.85rem; border-radius:3px; border:1px solid var(--border); background:var(--bg-content); color:var(--text-main);">
                    </div>
                    <div style="display:flex; flex-direction:column; gap:0.25rem;">
                         <span style="font-size:0.75rem;color:var(--text-secondary);">Email</span>
                         <input type="email" class="sub-email-input" value="${sub.contact_email || ''}" placeholder="jeff@email.com" style="padding: 0.3rem 0.5rem; font-size: 0.85rem; border-radius:3px; border:1px solid var(--border); background:var(--bg-content); color:var(--text-main);">
                    </div>
                </div>
            </div>
            <div style="display: flex; flex-direction: column; gap: 1rem; margin-top: 1rem;">
                 <div style="display: flex; gap: 0.5rem; flex-wrap: wrap; padding-bottom: 1rem; border-bottom: 1px solid rgba(255,255,255,0.1);">
                      <button class="btn-outline macro-select-deer" style="flex: 1 1 auto; padding: 0.5rem; font-size: 0.8rem;">Select all - Deer</button>
                      <button class="btn-outline macro-select-people" style="flex: 1 1 auto; padding: 0.5rem; font-size: 0.8rem;">Select all - People</button>
                      <button class="btn-outline macro-clear-all" style="flex: 1 1 auto; padding: 0.5rem; font-size: 0.8rem; color: var(--error); border-color: rgba(239, 68, 68, 0.3);">Clear all</button>
                 </div>
                 ${routingHtml}
            </div>
        `;
        container.appendChild(card);
    });
    bindLocalMacros();
}

function bindLocalMacros() {
    document.querySelectorAll('.macro-select-deer').forEach(btn => {
        btn.onclick = (e) => { e.preventDefault(); Array.from(btn.parentElement.parentElement.querySelectorAll('.route-checkbox[data-tag="Antlered Buck"]')).forEach(chk => chk.checked = true); };
    });
    document.querySelectorAll('.macro-select-people').forEach(btn => {
        btn.onclick = (e) => { e.preventDefault(); Array.from(btn.parentElement.parentElement.querySelectorAll('.route-checkbox[data-tag="Person"]')).forEach(chk => chk.checked = true); };
    });
    document.querySelectorAll('.macro-clear-all').forEach(btn => {
        btn.onclick = (e) => { e.preventDefault(); Array.from(btn.parentElement.parentElement.querySelectorAll('.route-checkbox')).forEach(chk => chk.checked = false); };
    });
}

function buildSubscribersPayload() {
    const payload = [];
    document.querySelectorAll('.subscriber-card').forEach(card => {
        const id = card.getAttribute('data-sub-id');
        const nameInput = card.querySelector('.sub-name-input');
        const name = nameInput ? nameInput.value.trim() : (card.getAttribute('data-sub-name') || 'Unknown User');

        const activeCheckbox = card.querySelector('.sub-active');
        const isActive = activeCheckbox ? activeCheckbox.checked : true;

        const smsInput = card.querySelector('.sub-sms-input');
        const emailInput = card.querySelector('.sub-email-input');

        const sms = smsInput ? smsInput.value.trim() : "";
        const email = emailInput ? emailInput.value.trim() : "";

        const routing = {};

        // Find all checked tag inputs within this specific subscriber card
        const checkedRoutes = card.querySelectorAll('.route-checkbox:checked');
        checkedRoutes.forEach(chk => {
            const muleId = chk.getAttribute('data-mule');
            const tag = chk.getAttribute('data-tag');

            if (!routing[muleId]) {
                routing[muleId] = [];
            }
            if (tag) {
                routing[muleId].push(tag);
            }
        });

        payload.push({
            id: id,
            name: name,
            active: isActive,
            contact_sms: sms,
            contact_email: email,
            routing: routing
        });
    });
    return payload;
}

const saveAlertsBtn = document.getElementById('save-alerts-btn');
if (saveAlertsBtn) {
    saveAlertsBtn.addEventListener('click', async () => {
        saveAlertsBtn.textContent = "Saving...";
        saveAlertsBtn.disabled = true;

        try {
            const response = await fetch(`${API_BASE_URL}/manage-image`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': `Bearer ${AUTH_TOKEN}`
                },
                body: JSON.stringify({
                    action: 'save_alert_settings',
                    subscribers: buildSubscribersPayload()
                })
            });

            if (!response.ok) {
                throw new Error(`Server returned ${response.status}`);
            }

            alert("Alert settings successfully saved to the cloud!");
        } catch (error) {
            console.error("Error saving alerts:", error);
            alert("Failed to save alert settings. Please check your connection.");
        } finally {
            saveAlertsBtn.textContent = "Save Alert Settings";
            saveAlertsBtn.disabled = false;
        }
    });
}

saveGeneralBtn.addEventListener('click', async () => {
    saveGeneralBtn.textContent = "Saving...";
    saveGeneralBtn.disabled = true;

    try {
        const p1 = fetch(`${API_BASE_URL}/manage-image`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${AUTH_TOKEN}`
            },
            body: JSON.stringify({ action: 'save_mappings', mappings: muleMappings })
        });

        let p2 = Promise.resolve({ ok: true });
        if (configPortalNameInput && configPortalPasswordInput && configPortalNameInput.value) {
            p2 = fetch(`${API_BASE_URL}/manage-image`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': `Bearer ${AUTH_TOKEN}`
                },
                body: JSON.stringify({
                    action: 'save_portal_config',
                    portal_name: configPortalNameInput.value.trim(),
                    portal_password: configPortalPasswordInput.value.trim()
                })
            });
        }

        const [res1, res2] = await Promise.all([p1, p2]);

        if (!res1.ok || !res2.ok) throw new Error("Save failed");

        // If password was changed, update local storage
        if (configPortalPasswordInput && configPortalPasswordInput.value.trim() !== '') {
            const newPwd = configPortalPasswordInput.value.trim();
            AUTH_TOKEN = newPwd;
            localStorage.setItem('woods_auth_token', newPwd);
            configPortalPasswordInput.value = ''; // clear it on success
        }

        if (configPortalNameInput && configPortalNameInput.value.trim() !== '') {
            const newName = configPortalNameInput.value.trim();
            document.title = newName;
            const loginTitle = document.getElementById('login-portal-title');
            const headerTitle = document.getElementById('header-portal-title');
            if (loginTitle) loginTitle.textContent = newName;
            if (headerTitle) headerTitle.textContent = newName;
        }

        alert("Settings saved successfully!");
        applySortAndRender(); // Re-render gallery with new names
    } catch (err) {
        alert("Failed to save configuration.");
        console.error(err);
    } finally {
        saveGeneralBtn.textContent = "Save General Settings";
        saveGeneralBtn.disabled = false;
    }
});

// --- Main Map Rendering ---
function renderMap(images) {
    if (!mainMap) {
        mainMap = L.map('main-map').setView([39.8283, -98.5795], 4);
        L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
            attribution: '© OpenStreetMap contributors'
        }).addTo(mainMap);
        mainMarkerLayer = L.markerClusterGroup({
            maxClusterRadius: 50,
        }).addTo(mainMap);
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

            const iconHtml = `
                <div style="background-color: ${color}; width: 30px; height: 30px; border-radius: 50% 50% 50% 0; border: 2px solid #fff; transform: rotate(-45deg); display: flex; align-items: center; justify-content: center; box-shadow: 0 4px 6px rgba(0,0,0,0.3);">
                    <div style="transform: rotate(45deg); color: white; font-size: 11px; font-weight: 600;">${stats.count}</div>
                </div>
            `;
            const customIcon = L.divIcon({
                html: iconHtml,
                className: '',
                iconSize: [30, 30],
                iconAnchor: [15, 30],
                popupAnchor: [0, -30]
            });
            const marker = L.marker([loc.lat, loc.lng], { icon: customIcon });

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
