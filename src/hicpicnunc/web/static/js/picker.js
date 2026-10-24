// Google Photos Picker — local desktop OAuth (server session); no GIS / no Bearer from the browser
const { t, tn } = window.i18n;
let authenticated = false;
/** @type {{ id: ?string, base_url: string, filename: string, type: ?string, mime_type: ?string, create_time: ?string, processing_status: ?string }[]} */
let loadedPickerItems = [];

function showStatus(message, type) {
    const el = document.getElementById('status');
    el.textContent = message;
    el.className = `status ${type}`;
    el.style.display = 'block';

    if (type === 'success') {
        setTimeout(() => {
            el.style.display = 'none';
        }, 5000);
    }
}

function hideStatus() {
    document.getElementById('status').style.display = 'none';
}

/** "12 photos · 1 video" — Picker items are typed PHOTO or VIDEO. */
function describeSelection(items) {
    const videos = items.filter((item) => item.type === 'VIDEO').length;
    const photos = items.length - videos;
    const parts = [];
    if (photos || !videos) parts.push(tn('js.picker.photo_count', photos));
    if (videos) parts.push(tn('js.picker.video_count', videos));
    return parts.join(' · ');
}

function itemToPayload(item) {
    const baseUrl =
        item.baseUrl ||
        item.base_url ||
        (item.mediaFile && item.mediaFile.baseUrl) ||
        '';
    const filename =
        item.filename ||
        (item.mediaFile && item.mediaFile.filename) ||
        'photo.jpg';
    return {
        id: item.id || null, // lets the server get a new base_url once this one expires
        base_url: baseUrl,
        filename,
        type: item.type || null,
        mime_type: item.mimeType || null,
        create_time: item.mediaMetadata?.creationTime || null,
        processing_status: item.videoProcessingStatus || null,
    };
}

/**
 * Google baseUrl includes a transform after "=" (e.g. =s0). Replace with a thumbnail size.
 */
function pickerThumbnailUrl(baseUrl) {
    if (!baseUrl) return '';
    const u = baseUrl.trim();
    const eq = u.lastIndexOf('=');
    if (eq !== -1) {
        return u.slice(0, eq) + '=w400-h300';
    }
    return u + '=w400-h300';
}

/** Same-origin proxy: Picker CDN needs OAuth; <img> cannot send Authorization. */
function pickerImageProxySrc(baseUrl) {
    const u = pickerThumbnailUrl(baseUrl);
    if (!u) return '';
    return `/api/picker-image?url=${encodeURIComponent(u)}`;
}

function setLoadedPickerItems(items) {
    loadedPickerItems = (items || [])
        .map(itemToPayload)
        .filter((x) => x.base_url);
    const btn = document.getElementById('extract-exif-btn');
    if (btn) {
        btn.style.display = loadedPickerItems.length > 0 ? 'inline-flex' : 'none';
        btn.disabled = false;
    }
}

// The selection is exported in small chunks so the page can show progress; the server
// is threaded, so a few chunks run in parallel.
const EXPORT_CHUNK_SIZE = 3;
const EXPORT_PARALLEL_REQUESTS = 3;

/** POST one chunk. A 500 that still names the job means only this chunk's items failed. */
async function exportChunk(chunk, jobId, includeJson) {
    const r = await fetch('/api/process-google-batch', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            items: chunk.items,
            offset: chunk.offset,
            job_id: jobId,
            include_json: includeJson,
        }),
    });
    const data = await r.json().catch(() => ({}));
    if (data.code === 'selection_expired') {
        const error = new Error(t('js.picker.selection_expired'));
        error.selectionExpired = true;
        throw error;
    }
    if (!r.ok && !data.job_id) throw new Error(data.detail || data.error || r.statusText);
    return data;
}

async function extractAllExif() {
    if (!loadedPickerItems.length) {
        showStatus(t('js.picker.choose_first'), 'error');
        return;
    }
    const btn = document.getElementById('extract-exif-btn');
    const pickerBtn = document.getElementById('picker-btn');
    const includeJsonInput = document.getElementById('metadata-include-json');
    const includeJson = !includeJsonInput || includeJsonInput.checked;
    const items = loadedPickerItems.slice();
    const total = items.length;
    const chunks = [];
    for (let offset = 0; offset < total; offset += EXPORT_CHUNK_SIZE) {
        chunks.push({ offset, items: items.slice(offset, offset + EXPORT_CHUNK_SIZE) });
    }

    if (btn) btn.disabled = true;
    if (pickerBtn) pickerBtn.disabled = true;
    hideStatus();
    const progress = exportProgress('export', total, {
        label: t('js.picker.exporting'),
        etaAfter: EXPORT_CHUNK_SIZE,
    });
    window.addEventListener('beforeunload', warnBeforeLeaving);

    let done = 0;
    let saved = 0;
    let jobId = null;
    let aborted = false;
    const record = (data, chunk) => {
        done += chunk.items.length;
        saved += data.processed || 0;
        progress.update(done, done - saved);
    };

    try {
        // The first chunk creates the job; the others add to it.
        const first = chunks.shift();
        const firstResult = await exportChunk(first, null, includeJson);
        jobId = firstResult.job_id;
        record(firstResult, first);
        const worker = async () => {
            while (chunks.length && !aborted) {
                const chunk = chunks.shift();
                try {
                    record(await exportChunk(chunk, jobId, includeJson), chunk);
                } catch (e) {
                    aborted = true; // stop the other workers from sending more chunks
                    throw e;
                }
            }
        };
        await Promise.all(Array.from({ length: EXPORT_PARALLEL_REQUESTS }, worker));
    } catch (e) {
        window.removeEventListener('beforeunload', warnBeforeLeaving);
        progress.hide();
        const message = e.selectionExpired
            ? e.message
            : t('js.progress.failed_after', { done, total, message: e.message });
        showStatus(message, 'error');
        if (btn) btn.disabled = false;
        if (pickerBtn) pickerBtn.disabled = false;
        return;
    }

    window.removeEventListener('beforeunload', warnBeforeLeaving);
    if (saved === 0) {
        progress.hide();
        showStatus(t('js.picker.nothing_exported'), 'error');
        if (btn) btn.disabled = false;
        if (pickerBtn) pickerBtn.disabled = false;
        return;
    }
    progress.finish();
    const failed = total - saved;
    window.location.href = `/job/${encodeURIComponent(jobId)}${failed ? `?failed=${failed}` : ''}`;
}

function authenticate() {
    showStatus(t('js.picker.opening_sign_in'), 'info');
    window.location.href = '/auth';
}

async function createSession() {
    const response = await fetch('/api/create-session', {
        method: 'POST',
    });

    if (!response.ok) {
        const error = await response.json().catch(() => ({}));
        throw new Error(error.detail || t('js.picker.create_session_failed'));
    }

    return await response.json();
}

async function openPicker() {
    if (!authenticated) {
        showStatus(t('js.picker.sign_in_first'), 'error');
        return;
    }
    try {
        showStatus(t('js.picker.opening_picker'), 'info');

        const sessionData = await createSession();

        if (!sessionData.pickerUri) {
            throw new Error(t('js.picker.no_picker_uri'));
        }

        const messageListener = (event) => {
            console.log('Received message event:', {
                origin: event.origin,
                data: event.data,
                source: event.source,
            });

            const validOrigins = [
                'https://photospicker.googleapis.com',
                'https://www.google.com',
                'https://accounts.google.com',
                'https://photos.google.com',
            ];

            if (!validOrigins.includes(event.origin)) {
                console.log('Message from unexpected origin:', event.origin);
            }

            if (event.data) {
                if (
                    event.data.mediaItems ||
                    event.data.items ||
                    event.data.selectedItems ||
                    event.data.photos
                ) {
                    window.removeEventListener('message', messageListener);
                    handlePickerResponse(event.data);
                } else if (
                    event.data.type === 'PICKER_RESPONSE' ||
                    event.data.action === 'selected'
                ) {
                    window.removeEventListener('message', messageListener);
                    handlePickerResponse(event.data);
                }
            }
        };

        window.addEventListener('message', messageListener);

        const pickerWindow = window.open(
            sessionData.pickerUri,
            'GooglePhotosPicker',
            'width=900,height=700,scrollbars=yes'
        );

        if (!pickerWindow) {
            window.removeEventListener('message', messageListener);
            throw new Error(t('js.picker.popup_blocked'));
        }

        showStatus(t('js.picker.choose_in_window'), 'success');

        pollSessionStatus(sessionData.pollInterval);
    } catch (error) {
        showStatus(t('js.picker.something_went_wrong', { message: error.message }), 'error');
    }
}

async function handlePickerResponse(data) {
    console.log('Handling picker response:', data);
    showStatus(t('js.picker.loading_selection'), 'info');

    try {
        const mediaItems = data.mediaItems || [];
        displayPhotos(mediaItems);
    } catch (error) {
        console.error('Error handling picker response:', error);
        showStatus(t('js.picker.selection_load_failed', { message: error.message }), 'error');
    }
}

function displayPhotos(items) {
    const container = document.getElementById('photos-content');
    document.getElementById('photos-container').classList.add('show');

    if (items.length === 0) {
        setLoadedPickerItems([]);
        container.innerHTML = `
            <div class="empty-state">
                <div class="empty-state-icon">📷</div>
                <h3>${t('js.picker.empty_title')}</h3>
                <p>${t('js.picker.empty_hint')}</p>
            </div>
        `;
        document.getElementById('photo-count').textContent = t('js.picker.nothing_selected');
        showStatus(t('js.picker.nothing_selected_yet'), 'info');
        return;
    }

    document.getElementById('photo-count').textContent = describeSelection(items);

    const grid = document.createElement('div');
    grid.className = 'photos-grid';

    items.forEach((item) => {
        const card = document.createElement('div');
        card.className = 'photo-card';

        const baseUrl = item.baseUrl || itemToPayload(item).base_url || '';
        const imgSrc = pickerImageProxySrc(baseUrl);
        const width = item.mediaMetadata?.width || '?';
        const height = item.mediaMetadata?.height || '?';
        const created = item.mediaMetadata?.creationTime
            ? new Date(item.mediaMetadata.creationTime).toLocaleDateString()
            : t('js.picker.unknown');

        const location = item.location || item.mediaMetadata?.location;
        const hasLocation = location && (location.latitude || location.longitude);
        const locationText = hasLocation
            ? `${location.latitude?.toFixed(6)}, ${location.longitude?.toFixed(6)}`
            : null;

        card.innerHTML = `
            ${imgSrc ? `<img src="${imgSrc}" alt="" loading="lazy">` : ''}
            <div class="photo-info">
                <h3 title="${item.filename || t('js.picker.untitled')}">${item.filename || t('js.picker.untitled')}</h3>
                <div class="photo-meta">
                    <div class="meta-item">
                        <span>📐</span>
                        <span>${width} × ${height}</span>
                    </div>
                    <div class="meta-item">
                        <span>📅</span>
                        <span>${created}</span>
                    </div>
                    <div class="meta-item">
                        <span>📄</span>
                        <span>${item.mimeType?.split('/')[1]?.toUpperCase() || t('js.picker.unknown')}</span>
                    </div>
                    ${
                        locationText
                            ? `
                    <div class="meta-item">
                        <span>📍</span>
                        <span title="${t('js.picker.lat_lng')}">${locationText}</span>
                    </div>
                    `
                            : ''
                    }
                </div>
            </div>
        `;

        grid.appendChild(card);
    });

    container.innerHTML = '';
    container.appendChild(grid);
    setLoadedPickerItems(items);
    showStatus(t('js.picker.loaded', { selection: describeSelection(items) }), 'success');
}

async function pollSessionStatus(pollInterval) {
    const intervalMs = parseInt(pollInterval, 10) * 1000 || 5000;
    let pollCount = 0;
    const maxPolls = 60;

    const checkStatus = setInterval(async () => {
        try {
            pollCount++;

            const response = await fetch('/api/session-status');
            if (response.ok) {
                const status = await response.json();

                if (status.mediaItemsSet) {
                    clearInterval(checkStatus);
                    hideStatus();
                    await loadSelectedPhotos();
                }
            }

            if (pollCount >= maxPolls) {
                clearInterval(checkStatus);
                hideStatus();
            }
        } catch (error) {
            console.error('Polling error:', error);
        }
    }, intervalMs);
}

async function loadSelectedPhotos() {
    try {
        const container = document.getElementById('photos-content');
        container.innerHTML =
            `<div class="loading"><div class="spinner"></div><p>${t('js.picker.loading_photos')}</p></div>`;
        document.getElementById('photos-container').classList.add('show');

        const response = await fetch('/api/list-selected');

        if (!response.ok) {
            const error = await response.json().catch(() => ({}));
            throw new Error(error.detail || error.error || t('js.picker.list_failed'));
        }

        const data = await response.json();

        if (data.items.length === 0) {
            setLoadedPickerItems([]);
            container.innerHTML = `
                <div class="empty-state">
                    <div class="empty-state-icon">📷</div>
                    <h3>${t('js.picker.empty_title')}</h3>
                    <p>${t('js.picker.empty_hint')}</p>
                </div>
            `;
            document.getElementById('photo-count').textContent = t('js.picker.nothing_selected');
            return;
        }

        document.getElementById('photo-count').textContent = describeSelection(data.items);

        const grid = document.createElement('div');
        grid.className = 'photos-grid';

        data.items.forEach((item) => {
            const card = document.createElement('div');
            card.className = 'photo-card';

            const baseUrl = item.baseUrl || '';
            const imgSrc = pickerImageProxySrc(baseUrl);
            const width = item.mediaMetadata?.width || '?';
            const height = item.mediaMetadata?.height || '?';
            const created = item.mediaMetadata?.creationTime
                ? new Date(item.mediaMetadata.creationTime).toLocaleDateString()
                : t('js.picker.unknown');

            card.innerHTML = `
                ${imgSrc ? `<img src="${imgSrc}" alt="" loading="lazy">` : ''}
                <div class="photo-info">
                    <h3 title="${item.filename || t('js.picker.untitled')}">${item.filename || t('js.picker.untitled')}</h3>
                    <div class="photo-meta">
                        <div class="meta-item">
                            <span>📐</span>
                            <span>${width} × ${height}</span>
                        </div>
                        <div class="meta-item">
                            <span>📅</span>
                            <span>${created}</span>
                        </div>
                        <div class="meta-item">
                            <span>📄</span>
                            <span>${item.mimeType?.split('/')[1]?.toUpperCase() || t('js.picker.unknown')}</span>
                        </div>
                    </div>
                </div>
            `;

            grid.appendChild(card);
        });

        container.innerHTML = '';
        container.appendChild(grid);
        setLoadedPickerItems(data.items);
        showStatus(t('js.picker.loaded', { selection: describeSelection(data.items) }), 'success');
    } catch (error) {
        setLoadedPickerItems([]);
        document.getElementById('photos-content').innerHTML = `
            <div class="empty-state">
                <div class="empty-state-icon">⚠️</div>
                <h3>${t('js.picker.error_title')}</h3>
                <p>${error.message}</p>
            </div>`;
    }
}

async function signOut() {
    const signoutBtn = document.getElementById('signout-btn');
    if (signoutBtn) signoutBtn.disabled = true;
    showStatus(t('js.picker.signing_out'), 'info');

    try {
        await fetch('/auth/logout', {
            method: 'POST',
            headers: { 'X-Requested-With': 'XMLHttpRequest' },
        });
    } catch (e) {
        console.warn('Logout network error:', e);
    }

    location.reload();
}

window.addEventListener('load', async () => {
    try {
        const response = await fetch('/api/check-auth');
        if (response.ok) {
            const data = await response.json().catch(() => ({}));
            authenticated = true;
            const authBtn = document.getElementById('auth-btn');
            authBtn.textContent = t('js.picker.signed_in');
            authBtn.className = 'btn btn-muted';
            authBtn.disabled = true;

            const accountBar = document.getElementById('google-account-bar');
            const signedInUser = document.getElementById('signed-in-user');
            if (accountBar && signedInUser) {
                signedInUser.textContent = data.email
                    ? t('js.picker.signed_in_as', { email: data.email })
                    : t('js.picker.signed_in_no_email');
                accountBar.style.display = 'flex';
            }

            document.getElementById('picker-btn').disabled = false;
        } else {
            const data = await response.json().catch(() => ({}));
            if (data.reason === 'expired') {
                showStatus(t('js.picker.session_expired'), 'info');
            }
        }
    } catch {
        // not signed in
    }
});
