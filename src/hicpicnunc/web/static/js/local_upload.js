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

  /** Full page POST so the browser follows Flask’s 302 (fetch + manual redirect often hides Location). */
  function submitWithRelativePaths() {
    form.querySelectorAll('input[name="relative_paths"][data-local-rel="1"]').forEach((el) => {
      el.remove();
    });
    const files = fileInput.files;
    if (!files?.length) return;
    for (let i = 0; i < files.length; i++) {
      const inp = document.createElement("input");
      inp.type = "hidden";
      inp.name = "relative_paths";
      inp.value = files[i].webkitRelativePath || files[i].name;
      inp.setAttribute("data-local-rel", "1");
      form.appendChild(inp);
    }
    form.submit();
  }

  form.addEventListener("submit", (e) => {
    syncStemField();
    syncJsonField();
    const files = fileInput.files;
    if (!files || !files.length) return;

    e.preventDefault();
    submitWithRelativePaths();
  });
})();
