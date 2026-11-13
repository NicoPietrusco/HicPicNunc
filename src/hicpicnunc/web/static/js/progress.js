// Progress box shared by the Google export and the local restore (markup: progress_box in index.html).

function warnBeforeLeaving(event) {
    event.preventDefault();
    event.returnValue = '';
}

function formatRemaining(seconds) {
    const { t, tn } = window.i18n;
    if (seconds < 60) return t('js.progress.less_than_a_minute_left');
    return tn('js.progress.minutes_left', Math.round(seconds / 60));
}

/**
 * Show the "<prefix>-progress" box for total items. The time left appears once etaAfter
 * items are done, so the first chunk doesn't produce a wild estimate.
 */
function exportProgress(prefix, total, { label, etaAfter }) {
    const { t, tn } = window.i18n;
    const box = document.getElementById(`${prefix}-progress`);
    const bar = document.getElementById(`${prefix}-progress-bar`);
    const labelEl = document.getElementById(`${prefix}-progress-label`);
    const count = document.getElementById(`${prefix}-progress-count`);
    const detail = document.getElementById(`${prefix}-progress-detail`);
    const startedAt = Date.now();
    bar.max = total;
    bar.value = 0;
    labelEl.textContent = label;
    count.textContent = t('js.progress.count', { done: 0, total });
    detail.textContent = t('js.progress.keep_open');
    box.hidden = false;
    return {
        update(done, failed) {
            bar.value = done;
            count.textContent = t('js.progress.count', { done, total });
            const parts = [];
            if (failed) parts.push(tn('js.progress.failed_part', failed));
            if (done >= etaAfter && done < total) {
                const perItem = (Date.now() - startedAt) / 1000 / done;
                parts.push(formatRemaining(perItem * (total - done)));
            }
            parts.push(t('js.progress.keep_open_part'));
            const text = parts.join(' · ');
            detail.textContent = text.charAt(0).toUpperCase() + text.slice(1) + '.';
        },
        finish() {
            labelEl.textContent = t('js.progress.opening_files');
            detail.textContent = '';
        },
        hide() {
            box.hidden = true;
        },
    };
}
