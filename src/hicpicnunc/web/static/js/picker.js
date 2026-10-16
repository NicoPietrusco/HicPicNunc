// Google Photos Picker — local desktop OAuth (server session); no GIS / no Bearer from the browser
let authenticated = false;
/** @type {{ base_url: string, filename: string, type: ?string, mime_type: ?string, create_time: ?string, processing_status: ?string }[]} */
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
    if (photos || !videos) parts.push(`${photos} photo${photos !== 1 ? 's' : ''}`);
    if (videos) parts.push(`${videos} video${videos !== 1 ? 's' : ''}`);
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

function appendMetaItem(meta, icon, value, title = '') {
    const row = document.createElement('div');
    row.className = 'meta-item';
    const iconElement = document.createElement('span');
    iconElement.textContent = icon;
    const valueElement = document.createElement('span');
    valueElement.textContent = value;
    if (title) valueElement.title = title;
    row.append(iconElement, valueElement);
    meta.appendChild(row);
}

function createPhotoCard(item, includeLocation = false) {
    const card = document.createElement('div');
    card.className = 'photo-card';

    const imgSrc = pickerImageProxySrc(item.baseUrl || itemToPayload(item).base_url || '');
    if (imgSrc) {
        const image = document.createElement('img');
        image.src = imgSrc;
        image.alt = '';
        image.loading = 'lazy';
        card.appendChild(image);
    }

    const info = document.createElement('div');
    info.className = 'photo-info';
    const heading = document.createElement('h3');
    heading.textContent = item.filename || 'Untitled';
    heading.title = item.filename || 'Untitled';
    info.appendChild(heading);

    const meta = document.createElement('div');
    meta.className = 'photo-meta';
    const width = item.mediaMetadata?.width || '?';
    const height = item.mediaMetadata?.height || '?';
    const created = item.mediaMetadata?.creationTime
        ? new Date(item.mediaMetadata.creationTime).toLocaleDateString()
        : 'Unknown';
    const mime = item.mimeType?.split('/')[1]?.toUpperCase() || 'Unknown';
    appendMetaItem(meta, '📐', `${width} × ${height}`);
    appendMetaItem(meta, '📅', created);
    appendMetaItem(meta, '📄', mime);

    if (includeLocation) {
        const location = item.location || item.mediaMetadata?.location;
        const hasLocation = location && (location.latitude || location.longitude);
        if (hasLocation) {
            const locationText = `${location.latitude?.toFixed(6)}, ${location.longitude?.toFixed(6)}`;
            appendMetaItem(meta, '📍', locationText, 'Latitude, Longitude');
        }
    }

    info.appendChild(meta);
    card.appendChild(info);
    return card;
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

function warnBeforeLeaving(event) {
    event.preventDefault();
    event.returnValue = '';
}

function formatRemaining(seconds) {
    if (seconds < 60) return 'less than a minute left';
    const minutes = Math.round(seconds / 60);
    return `about ${minutes} minute${minutes !== 1 ? 's' : ''} left`;
}

function exportProgress(total) {
    const box = document.getElementById('export-progress');
    const bar = document.getElementById('export-progress-bar');
    const label = document.getElementById('export-progress-label');
    const count = document.getElementById('export-progress-count');
    const detail = document.getElementById('export-progress-detail');
    const startedAt = Date.now();
    bar.max = total;
    bar.value = 0;
    label.textContent = 'Exporting…';
    count.textContent = `0 of ${total}`;
    detail.textContent = 'Keep this page open until it finishes.';
    box.hidden = false;
    return {
        update(done, failed) {
            bar.value = done;
            count.textContent = `${done} of ${total}`;
            const parts = [];
            if (failed) parts.push(`${failed} couldn’t be saved`);
            if (done >= EXPORT_CHUNK_SIZE && done < total) {
                const perPhoto = (Date.now() - startedAt) / 1000 / done;
                parts.push(formatRemaining(perPhoto * (total - done)));
            }
            parts.push('keep this page open until it finishes');
            const text = parts.join(' · ');
            detail.textContent = text.charAt(0).toUpperCase() + text.slice(1) + '.';
        },
        finish() {
            label.textContent = 'Opening your files…';
            detail.textContent = '';
        },
        hide() {
            box.hidden = true;
        },
    };
}

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
    if (!r.ok && !data.job_id) throw new Error(data.detail || data.error || r.statusText);
    return data;
}

async function extractAllExif() {
    if (!loadedPickerItems.length) {
        showStatus('Choose photos or videos first, then wait for the list.', 'error');
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
    const progress = exportProgress(total);
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
        showStatus(`Something went wrong after ${done} of ${total}: ${e.message}`, 'error');
        if (btn) btn.disabled = false;
        if (pickerBtn) pickerBtn.disabled = false;
        return;
    }

    window.removeEventListener('beforeunload', warnBeforeLeaving);
    if (saved === 0) {
        progress.hide();
        showStatus('Nothing could be exported. Check the terminal logs for details.', 'error');
        if (btn) btn.disabled = false;
        if (pickerBtn) pickerBtn.disabled = false;
        return;
    }
    progress.finish();
    const failed = total - saved;
    window.location.href = `/job/${encodeURIComponent(jobId)}${failed ? `?failed=${failed}` : ''}`;
}

function authenticate() {
    showStatus('Opening Google sign-in…', 'info');
    window.location.href = '/auth';
}

async function createSession() {
    const response = await fetch('/api/create-session', {
        method: 'POST',
    });

    if (!response.ok) {
        const error = await response.json().catch(() => ({}));
        throw new Error(error.detail || 'Failed to create session');
    }

    return await response.json();
}

async function openPicker() {
    if (!authenticated) {
        showStatus('Sign in with Google first (button above).', 'error');
        return;
    }
    try {
        showStatus("Opening Google's photo picker...", 'info');

        const sessionData = await createSession();

        if (!sessionData.pickerUri) {
            throw new Error('No picker URI returned');
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
            throw new Error('Popup blocked. Please allow popups for this site.');
        }

        showStatus('Choose photos or videos in the new window, then wait for them to appear here.', 'success');

        pollSessionStatus(sessionData.pollInterval);
    } catch (error) {
        showStatus(`Something went wrong: ${error.message}`, 'error');
    }
}

async function handlePickerResponse(data) {
    console.log('Handling picker response:', data);
    showStatus('Loading your selection…', 'info');

    try {
        const mediaItems = data.mediaItems || [];
        displayPhotos(mediaItems);
    } catch (error) {
        console.error('Error handling picker response:', error);
        showStatus(`Couldn't load your selection: ${error.message}`, 'error');
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
                <h3>Nothing selected yet</h3>
                <p>Use “Choose photos & videos”, pick items in the popup, then they’ll show up here.</p>
            </div>
        `;
        document.getElementById('photo-count').textContent = 'Nothing selected';
        showStatus('Nothing selected yet.', 'info');
        return;
    }

    document.getElementById('photo-count').textContent = describeSelection(items);

    const grid = document.createElement('div');
    grid.className = 'photos-grid';

    items.forEach((item) => grid.appendChild(createPhotoCard(item, true)));

    container.innerHTML = '';
    container.appendChild(grid);
    setLoadedPickerItems(items);
    showStatus(`Loaded ${describeSelection(items)}.`, 'success');
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
            '<div class="loading"><div class="spinner"></div><p>Loading your photos…</p></div>';
        document.getElementById('photos-container').classList.add('show');

        const response = await fetch('/api/list-selected');

        if (!response.ok) {
            const error = await response.json().catch(() => ({}));
            throw new Error(error.detail || error.error || 'Failed to load your selection');
        }

        const data = await response.json();

        if (data.items.length === 0) {
            setLoadedPickerItems([]);
            container.innerHTML = `
                <div class="empty-state">
                    <div class="empty-state-icon">📷</div>
                    <h3>Nothing selected yet</h3>
                    <p>Use “Choose photos & videos”, pick items in the popup, then they’ll show up here.</p>
                </div>
            `;
            document.getElementById('photo-count').textContent = 'Nothing selected';
            return;
        }

        document.getElementById('photo-count').textContent = describeSelection(data.items);

        const grid = document.createElement('div');
        grid.className = 'photos-grid';

        data.items.forEach((item) => grid.appendChild(createPhotoCard(item)));

        container.innerHTML = '';
        container.appendChild(grid);
        setLoadedPickerItems(data.items);
        showStatus(`Loaded ${describeSelection(data.items)}.`, 'success');
    } catch (error) {
        setLoadedPickerItems([]);
        const emptyState = document.createElement('div');
        emptyState.className = 'empty-state';
        const icon = document.createElement('div');
        icon.className = 'empty-state-icon';
        icon.textContent = '⚠️';
        const heading = document.createElement('h3');
        heading.textContent = 'Error';
        const message = document.createElement('p');
        message.textContent = error.message;
        emptyState.append(icon, heading, message);
        const container = document.getElementById('photos-content');
        container.replaceChildren(emptyState);
    }
}

async function signOut() {
    const signoutBtn = document.getElementById('signout-btn');
    if (signoutBtn) signoutBtn.disabled = true;
    showStatus('Signing out…', 'info');

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
            authBtn.textContent = 'Signed in';
            authBtn.className = 'btn btn-muted';
            authBtn.disabled = true;

            const accountBar = document.getElementById('google-account-bar');
            const signedInUser = document.getElementById('signed-in-user');
            if (accountBar && signedInUser) {
                signedInUser.textContent = data.email ? `Signed in as ${data.email} ·` : 'Signed in ·';
                accountBar.style.display = 'flex';
            }

            document.getElementById('picker-btn').disabled = false;
        } else {
            const data = await response.json().catch(() => ({}));
            if (data.reason === 'expired') {
                showStatus('Your Google session expired. Sign in again to choose photos.', 'info');
            }
        }
    } catch {
        // not signed in
    }
});
