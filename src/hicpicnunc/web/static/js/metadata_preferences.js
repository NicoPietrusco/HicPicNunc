(function () {
  const { t } = window.i18n;
  const menu = document.querySelector(".app-settings-menu");
  const summary = menu && menu.querySelector("summary");
  const cameraDetails = document.getElementById("metadata-camera-details");
  const gpsLocation = document.getElementById("metadata-gps-location");
  const includeJson = document.getElementById("metadata-include-json");
  const resetButton = document.getElementById("metadata-reset-defaults");
  const status = document.getElementById("metadata-preferences-status");

  if (!menu || !summary || !cameraDetails || !gpsLocation || !includeJson || !resetButton || !status) return;

  const STATUS_CLEAR_MS = 2000;

  function readCheckboxes() {
    return {
      camera_details: cameraDetails.checked,
      gps_location: gpsLocation.checked,
      include_json: includeJson.checked,
    };
  }

  function writeCheckboxes(preferences) {
    cameraDetails.checked = preferences.camera_details;
    gpsLocation.checked = preferences.gps_location;
    includeJson.checked = preferences.include_json;
  }

  // What the server last confirmed, restored when a save fails.
  let saved = readCheckboxes();
  // One request at a time: a change made while a save is in flight is sent when
  // it finishes, with the checkboxes as they are then, so the last choice wins.
  let saving = false;
  let pending = false;
  let statusTimer = null;

  function showStatus(message, { clear = false } = {}) {
    clearTimeout(statusTimer);
    status.textContent = message;
    if (clear) {
      statusTimer = setTimeout(() => { status.textContent = ""; }, STATUS_CLEAR_MS);
    }
  }

  async function savePreferences() {
    if (saving) {
      pending = true;
      return;
    }
    saving = true;
    showStatus(t("js.preferences.saving"));

    try {
      const response = await fetch("/api/metadata-preferences", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ preferences: readCheckboxes() }),
      });
      const result = await response.json().catch(() => ({}));
      if (!response.ok || !result.ok) {
        throw new Error(result.detail || t("js.preferences.save_failed"));
      }
      saved = { ...saved, ...result.preferences };
      if (!pending) showStatus(t("js.preferences.saved"), { clear: true });
    } catch (error) {
      pending = false;
      writeCheckboxes(saved);
      showStatus(error.message || t("js.preferences.save_failed"));
    } finally {
      saving = false;
    }

    if (pending) {
      pending = false;
      await savePreferences();
    }
  }

  function closeMenu() {
    menu.open = false;
  }

  for (const checkbox of [cameraDetails, gpsLocation, includeJson]) {
    checkbox.addEventListener("change", savePreferences);
  }
  resetButton.addEventListener("click", () => {
    writeCheckboxes({ camera_details: true, gps_location: true, include_json: false });
    savePreferences();
  });

  document.addEventListener("click", (event) => {
    if (menu.open && !menu.contains(event.target)) closeMenu();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape" || !menu.open) return;
    closeMenu();
    summary.focus();
  });
})();
