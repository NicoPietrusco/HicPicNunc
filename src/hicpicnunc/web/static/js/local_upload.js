(function () {
  const { t, tn } = window.i18n;
  const form = document.getElementById("local-upload-form");
  const fileInput = document.getElementById("local-file-input");
  const pickFilesBtn = document.getElementById("local-pick-files");
  const pickFolderBtn = document.getElementById("local-pick-folder");
  const fileLabelText = document.getElementById("local-file-label-text");
  const includeJson = document.getElementById("metadata-include-json");
  const includeJsonField = document.getElementById("local-include-json-field");
  const stemField = document.getElementById("local-stem-suffix");
  const localPreview = document.getElementById("local-preview");
  const localPreviewCount = document.getElementById("local-preview-count");
  const localPreviewGrid = document.getElementById("local-preview-grid");
  const localPreviewNames = document.getElementById("local-preview-names");
  /** @type {string[]} */
  let previewObjectUrls = [];
  const MAX_PREVIEW_THUMBS = 48;
  const imageExtensions = new Set(window.__IMAGE_EXTENSIONS__ || []);

  /** Same extensions as the server: anything else (videos, .DS_Store...) is skipped. */
  function isSupportedImage(file) {
    const dot = file.name.lastIndexOf(".");
    return dot > 0 && imageExtensions.has(file.name.slice(dot).toLowerCase());
  }

  const suffixDefault = () =>
    (window.__LOCAL_SUFFIX__ && String(window.__LOCAL_SUFFIX__).trim()) || "_exif";

  function syncStemField() {
    if (!stemField) return;
    stemField.value = suffixDefault();
  }

  function syncJsonField() {
    if (includeJsonField) includeJsonField.value = includeJson && includeJson.checked ? "1" : "0";
  }

  if (includeJson) {
    includeJson.addEventListener("change", () => {
      syncJsonField();
      updateLocalPreview();
    });
  }
  syncStemField();
  syncJsonField();

  function clearLocalPreview() {
    previewObjectUrls.forEach((u) => URL.revokeObjectURL(u));
    previewObjectUrls = [];
    if (localPreviewGrid) localPreviewGrid.innerHTML = "";
    if (localPreviewNames) localPreviewNames.innerHTML = "";
    if (localPreviewCount) localPreviewCount.textContent = "";
    if (localPreview) localPreview.hidden = true;
  }

  function updateLocalPreview() {
    clearLocalPreview();
    if (!fileInput || !localPreview) return;
    const files = fileInput.files;
    if (!files || !files.length) {
      localPreview.hidden = true;
      return;
    }
    localPreview.hidden = false;
    const n = files.length;
    let imageCount = 0;
    for (let i = 0; i < files.length; i++) {
      if (files[i].type.startsWith("image/")) imageCount += 1;
    }
    if (localPreviewCount) {
      const output = t("js.local.output_name", { suffix: suffixDefault() });
      const json = t(includeJson && includeJson.checked ? "js.local.with_json" : "js.local.images_only");
      let line = tn("js.local.selected", n, { output, json });
      if (imageCount !== n) line += " " + tn("js.local.image_previews", imageCount);
      if (n > MAX_PREVIEW_THUMBS) {
        line += " " + t("js.local.showing_thumbnails", { count: MAX_PREVIEW_THUMBS });
      }
      const skipped = Array.from(files).filter((f) => !isSupportedImage(f)).length;
      if (skipped) line += " " + tn("js.local.skipped", skipped);
      localPreviewCount.textContent = line;
    }
    if (localPreviewNames) {
      for (let i = 0; i < files.length; i++) {
        const f = files[i];
        const rel = f.webkitRelativePath || f.name;
        const li = document.createElement("li");
        li.textContent = rel;
        localPreviewNames.appendChild(li);
      }
    }
    if (localPreviewGrid) {
      let shown = 0;
      for (let i = 0; i < files.length && shown < MAX_PREVIEW_THUMBS; i++) {
        const f = files[i];
        if (!f.type.startsWith("image/")) continue;
        const url = URL.createObjectURL(f);
        previewObjectUrls.push(url);
        const rel = f.webkitRelativePath || f.name;
        const img = document.createElement("img");
        img.src = url;
        img.alt = rel;
        img.loading = "lazy";
        img.decoding = "async";
        localPreviewGrid.appendChild(img);
        shown += 1;
      }
    }
  }

  function setPickMode(mode) {
    if (!fileInput) return;
    fileInput.value = "";
    if (mode === "folder") {
      fileInput.setAttribute("webkitdirectory", "");
      fileInput.setAttribute("multiple", "");
    } else {
      fileInput.removeAttribute("webkitdirectory");
      fileInput.setAttribute("multiple", "");
    }
    if (pickFilesBtn) {
      pickFilesBtn.classList.toggle("is-active", mode === "files");
      pickFilesBtn.setAttribute("aria-pressed", mode === "files" ? "true" : "false");
    }
    if (pickFolderBtn) {
      pickFolderBtn.classList.toggle("is-active", mode === "folder");
      pickFolderBtn.setAttribute("aria-pressed", mode === "folder" ? "true" : "false");
    }
    const labelStr = t(mode === "folder" ? "js.local.choose_folder" : "js.local.choose_files");
    if (fileLabelText) {
      fileLabelText.textContent = labelStr;
    }
    fileInput.setAttribute("aria-label", labelStr);
    clearLocalPreview();
  }

  if (pickFilesBtn && pickFolderBtn && fileInput) {
    pickFilesBtn.addEventListener("click", () => setPickMode("files"));
    pickFolderBtn.addEventListener("click", () => setPickMode("folder"));
    setPickMode("files");
  }

  if (!form || !fileInput) return;

  fileInput.addEventListener("change", updateLocalPreview);

  const submitBtn = document.getElementById("local-submit");
  const statusEl = document.getElementById("local-status");

  // Files go up a few at a time, so no request exceeds the server's MAX_UPLOAD_MB and the
  // page can show progress. Chunks are sent one after the other: in parallel, two files
  // with the same name could both claim the same "name (2)" in the job.
  const CHUNK_MAX_FILES = 10;
  const MAX_UPLOAD_BYTES = window.__MAX_UPLOAD_BYTES__ || 50 * 1024 * 1024;
  const CHUNK_MAX_BYTES = MAX_UPLOAD_BYTES - 1024 * 1024; // headroom for the multipart fields
  function showLocalStatus(message, type) {
    if (!statusEl) return;
    statusEl.textContent = message;
    statusEl.className = `status ${type}`;
    statusEl.style.display = "block";
  }

  /**
   * Group files into chunks of at most CHUNK_MAX_FILES files and CHUNK_MAX_BYTES. A file
   * over CHUNK_MAX_BYTES on its own is not sent: the first chunk carries its name instead.
   */
  function makeChunks(files) {
    const chunks = [];
    const tooLarge = [];
    let current = null;
    files.forEach((file, index) => {
      if (file.size > CHUNK_MAX_BYTES) {
        tooLarge.push(file);
        return;
      }
      const fits =
        current &&
        current.files.length < CHUNK_MAX_FILES &&
        current.bytes + file.size <= CHUNK_MAX_BYTES;
      if (!fits) {
        current = { offset: index, files: [], bytes: 0, tooLarge: [] };
        chunks.push(current);
      }
      current.files.push(file);
      current.bytes += file.size;
    });
    if (chunks.length) chunks[0].tooLarge = tooLarge;
    return chunks;
  }

  /** POST one chunk. A failure that still names the job means only this chunk's files failed. */
  async function uploadChunk(chunk, jobId) {
    const data = new FormData();
    chunk.files.forEach((file) => {
      data.append("file", file, file.name);
      data.append("relative_paths", file.webkitRelativePath || file.name);
    });
    chunk.tooLarge.forEach((file) => data.append("too_large", file.webkitRelativePath || file.name));
    data.append("stem_suffix", stemField ? stemField.value : "");
    data.append("include_json", includeJsonField ? includeJsonField.value : "1");
    data.append("offset", String(chunk.offset));
    if (jobId) data.append("job_id", jobId);
    const r = await fetch(form.action, {
      method: "POST",
      body: data,
      headers: { Accept: "application/json", "X-Requested-With": "XMLHttpRequest" },
    });
    const body = await r.json().catch(() => ({}));
    if (!r.ok && !body.job_id) throw new Error(body.detail || r.statusText);
    return body;
  }

  async function uploadInChunks(files) {
    const total = files.length;
    const chunks = makeChunks(files);
    if (!chunks.length) {
      const limit = Math.round(MAX_UPLOAD_BYTES / 1024 / 1024);
      showLocalStatus(t("js.local.all_too_large", { limit }), "error");
      return;
    }
    if (submitBtn) submitBtn.disabled = true;
    if (statusEl) statusEl.style.display = "none";
    const progress = exportProgress("local", total, {
      label: t("js.local.restoring"),
      etaAfter: CHUNK_MAX_FILES,
    });
    window.addEventListener("beforeunload", warnBeforeLeaving);

    let done = 0;
    let saved = 0;
    let jobId = null;
    try {
      for (const chunk of chunks) {
        const result = await uploadChunk(chunk, jobId);
        jobId = jobId || result.job_id;
        done += chunk.files.length + chunk.tooLarge.length;
        saved += result.processed || 0;
        progress.update(done, done - saved);
      }
    } catch (e) {
      window.removeEventListener("beforeunload", warnBeforeLeaving);
      progress.hide();
      showLocalStatus(t("js.progress.failed_after", { done, total, message: e.message }), "error");
      if (submitBtn) submitBtn.disabled = false;
      return;
    }

    window.removeEventListener("beforeunload", warnBeforeLeaving);
    if (saved === 0) {
      progress.hide();
      showLocalStatus(t("js.local.nothing_restored"), "error");
      if (submitBtn) submitBtn.disabled = false;
      return;
    }
    progress.finish();
    const failed = total - saved;
    window.location.href = `/job/${encodeURIComponent(jobId)}${failed ? `?failed=${failed}` : ""}`;
  }

  form.addEventListener("submit", (e) => {
    syncStemField();
    syncJsonField();
    const files = fileInput.files;
    if (!files || !files.length) return;

    e.preventDefault();
    // Folders often hold videos and system files the server would skip: don't upload them
    // (the preview says how many).
    const images = Array.from(files).filter(isSupportedImage);
    if (!images.length) {
      showLocalStatus(t("js.local.no_supported_images"), "error");
      return;
    }
    uploadInChunks(images);
  });
})();
