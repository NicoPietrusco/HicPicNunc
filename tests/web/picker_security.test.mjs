import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import vm from 'node:vm';

class Element {
    constructor(tagName = 'div') {
        this.tagName = tagName;
        this.children = [];
        this.textContent = '';
        this.style = {};
        this.classList = { add() {} };
    }
    append(...elements) { this.html = ''; this.children.push(...elements); }
    appendChild(element) { this.html = ''; this.children.push(element); return element; }
    replaceChildren(...elements) { this.html = ''; this.children = elements; }
    set innerHTML(value) { this.html = value; this.children = []; }
    get innerHTML() { return this.html || ''; }
}

async function loadPicker() {
    const elements = new Map();
    const document = {
        createElement: (tag) => new Element(tag),
        getElementById: (id) => {
            if (!elements.has(id)) elements.set(id, new Element());
            return elements.get(id);
        },
    };
    const context = vm.createContext({
        document,
        window: { addEventListener() {}, removeEventListener() {} },
        fetch: async () => { throw new Error('Unexpected fetch'); },
        setTimeout() {},
        console,
        URL,
        Date,
        encodeURIComponent,
    });
    const source = await readFile(new URL('../../src/hicpicnunc/web/static/js/picker.js', import.meta.url), 'utf8');
    vm.runInContext(source, context);
    return { context, elements };
}

function allText(element) {
    return `${element.textContent || ''}${element.children.map(allText).join('')}`;
}

function findTag(element, tagName) {
    if (element.tagName === tagName) return element;
    for (const child of element.children) {
        const found = findTag(child, tagName);
        if (found) return found;
    }
    return null;
}

test('Google metadata is rendered as text, not executable markup', async () => {
    const { context, elements } = await loadPicker();
    const malicious = '<img src=x onerror=alert(1)>.jpg';
    vm.runInContext(`displayPhotos([{
        baseUrl: 'https://example.test/photo=s0',
        filename: ${JSON.stringify(malicious)},
        mimeType: 'image/<svg onload=alert(2)>',
        mediaMetadata: { width: '<svg onload=alert(3)>', height: 12 },
    }])`, context);

    const content = elements.get('photos-content');
    assert.equal(allText(content).includes(malicious), true);
    assert.equal(content.html || '', '');
    assert.equal(content.children.length, 1);
    assert.equal(findTag(content, 'h3').title, malicious);
});

test('an error message containing markup is rendered as text', async () => {
    const { context, elements } = await loadPicker();
    context.fetch = async () => { throw new Error('<img src=x onerror=alert(1)>'); };
    await vm.runInContext('loadSelectedPhotos()', context);

    const content = elements.get('photos-content');
    assert.match(allText(content), /<img src=x onerror=alert\(1\)>/);
    assert.equal(content.html || '', '');
});
