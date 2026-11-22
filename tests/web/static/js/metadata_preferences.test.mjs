import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import vm from 'node:vm';

class Element {
    constructor(parent = null) {
        this.parent = parent;
        this.listeners = {};
        this.textContent = '';
        this.checked = false;
        this.focused = false;
    }
    addEventListener(type, listener) { (this.listeners[type] ||= []).push(listener); }
    dispatch(type, event = {}) { for (const listener of this.listeners[type] || []) listener({ target: this, ...event }); }
    contains(element) {
        for (let node = element; node; node = node.parent) if (node === this) return true;
        return false;
    }
    focus() { this.focused = true; }
}

const ids = [
    'metadata-camera-details',
    'metadata-gps-location',
    'metadata-include-json',
    'metadata-reset-defaults',
    'metadata-preferences-status',
];

function deferred() {
    let resolve;
    const promise = new Promise((r) => { resolve = r; });
    return { promise, resolve };
}

function respond(body, ok = true) {
    return { ok, json: async () => body };
}

const flush = () => new Promise((resolve) => setImmediate(resolve));

async function loadPreferences({ preferences = { camera_details: true, gps_location: true, include_json: false } } = {}) {
    const document = new Element();
    const menu = new Element(document);
    menu.open = true;
    const summary = new Element(menu);
    menu.querySelector = () => summary;
    const elements = new Map(ids.map((id) => [id, new Element(menu)]));
    elements.get('metadata-camera-details').checked = preferences.camera_details;
    elements.get('metadata-gps-location').checked = preferences.gps_location;
    elements.get('metadata-include-json').checked = preferences.include_json;
    const outside = new Element(document);
    document.querySelector = () => menu;
    document.getElementById = (id) => elements.get(id);

    const requests = [];
    const context = vm.createContext({
        document,
        window: { i18n: { t: (key) => key } },
        fetch: (url, options) => {
            const reply = deferred();
            requests.push({ url, body: JSON.parse(options.body).preferences, reply });
            return reply.promise;
        },
        setTimeout: () => 0,
        clearTimeout() {},
        Error,
    });
    const source = await readFile(new URL('../../../../src/hicpicnunc/web/static/js/metadata_preferences.js', import.meta.url), 'utf8');
    vm.runInContext(source, context);
    return { document, menu, summary, outside, elements, requests };
}

function toggle(elements, id) {
    const checkbox = elements.get(id);
    checkbox.checked = !checkbox.checked;
    checkbox.dispatch('change');
}

test('a click outside the popover closes it', async () => {
    const { document, menu, outside } = await loadPreferences();
    document.dispatch('click', { target: outside });
    assert.equal(menu.open, false);
});

test('a click inside the popover keeps it open', async () => {
    const { document, menu, elements } = await loadPreferences();
    document.dispatch('click', { target: elements.get('metadata-gps-location') });
    document.dispatch('click', { target: elements.get('metadata-reset-defaults') });
    assert.equal(menu.open, true);
});

test('Esc closes the popover and focuses the Settings button', async () => {
    const { document, menu, summary } = await loadPreferences();
    document.dispatch('keydown', { key: 'Escape' });
    assert.equal(menu.open, false);
    assert.equal(summary.focused, true);
});

test('Esc does nothing while the popover is closed', async () => {
    const { document, menu, summary } = await loadPreferences();
    menu.open = false;
    document.dispatch('keydown', { key: 'Escape' });
    assert.equal(summary.focused, false);
});

test('a checkbox change is saved right away with every value', async () => {
    const { elements, requests } = await loadPreferences();
    toggle(elements, 'metadata-gps-location');

    assert.equal(requests.length, 1);
    assert.equal(requests[0].url, '/api/metadata-preferences');
    assert.deepEqual(requests[0].body, { camera_details: true, gps_location: false, include_json: false });

    requests[0].reply.resolve(respond({ ok: true, preferences: requests[0].body }));
    await flush();
    assert.equal(elements.get('metadata-preferences-status').textContent, 'js.preferences.saved');
});

test('a failed save restores the checkbox and shows the error', async () => {
    const { elements, requests } = await loadPreferences();
    toggle(elements, 'metadata-camera-details');

    requests[0].reply.resolve(respond({ ok: false, detail: 'Disk full' }, false));
    await flush();
    assert.equal(elements.get('metadata-camera-details').checked, true);
    assert.equal(elements.get('metadata-preferences-status').textContent, 'Disk full');
});

test('quick successive changes end in the last state chosen', async () => {
    const { elements, requests } = await loadPreferences();
    toggle(elements, 'metadata-gps-location');
    toggle(elements, 'metadata-include-json');
    toggle(elements, 'metadata-camera-details');
    assert.equal(requests.length, 1, 'only one request is in flight');

    requests[0].reply.resolve(respond({ ok: true, preferences: requests[0].body }));
    await flush();
    assert.equal(requests.length, 2);
    assert.deepEqual(requests[1].body, { camera_details: false, gps_location: false, include_json: true });
    assert.equal(elements.get('metadata-preferences-status').textContent, 'js.preferences.saving');

    requests[1].reply.resolve(respond({ ok: true, preferences: requests[1].body }));
    await flush();
    assert.equal(requests.length, 2);
    assert.equal(elements.get('metadata-preferences-status').textContent, 'js.preferences.saved');
});

test('Reset restores the defaults and saves them', async () => {
    const { elements, requests } = await loadPreferences({
        preferences: { camera_details: false, gps_location: false, include_json: true },
    });
    elements.get('metadata-reset-defaults').dispatch('click');

    assert.equal(requests.length, 1);
    assert.deepEqual(requests[0].body, { camera_details: true, gps_location: true, include_json: false });
});
