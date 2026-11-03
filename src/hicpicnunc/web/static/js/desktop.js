// Desktop builds stop when their last tab closes: each page reports while it's open and
// says goodbye when it goes away. Loaded only when the server has a lifecycle.
(function () {
  const { t } = window.i18n;
  const HEARTBEAT_MS = 10000;
  const tabId = crypto.randomUUID();
  const quitButton = document.getElementById("app-quit");
  const notice = document.getElementById("app-stopped");
  let leaving = false;
  let stopped = false;

  function tabForm() {
    return new URLSearchParams({ tab: tabId });
  }

  function showStopped(message) {
    stopped = true;
    if (quitButton) quitButton.disabled = true;
    if (notice) {
      notice.textContent = message;
      notice.hidden = false;
    }
  }

  async function heartbeat() {
    if (stopped) return;
    try {
      const response = await fetch("/api/heartbeat", { method: "POST", body: tabForm() });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
    } catch (e) {
      // A request cut short by leaving the page doesn't mean the app has stopped.
      if (!leaving) showStopped(t("js.desktop.closed"));
    }
  }

  window.addEventListener("pagehide", () => {
    leaving = true;
    if (!stopped) navigator.sendBeacon("/api/goodbye", tabForm());
  });
  // A page restored from the back/forward cache registers again.
  window.addEventListener("pageshow", (event) => {
    leaving = false;
    if (event.persisted) heartbeat();
  });

  if (quitButton) {
    quitButton.addEventListener("click", async () => {
      quitButton.disabled = true;
      try {
        await fetch("/api/quit", { method: "POST" });
      } catch (e) {
        // Already stopped
      }
      showStopped(t("js.desktop.quit"));
    });
  }

  heartbeat();
  setInterval(heartbeat, HEARTBEAT_MS);
})();
