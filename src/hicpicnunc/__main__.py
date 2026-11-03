"""Start the local server and open the app in the browser.

Used by `python -m hicpicnunc`, the `hicpicnunc` script and the desktop bundles
(PyInstaller runs this file as a script, hence the absolute imports). A desktop bundle
runs one instance at a time and stops when its last browser tab closes.
"""

import os
import sys
import threading
import webbrowser

from werkzeug.serving import make_server

from hicpicnunc.desktop import (
    Lifecycle,
    forget_instance,
    record_instance,
    running_instance_url,
    watch,
)
from hicpicnunc.log import get_logger
from hicpicnunc.settings import settings
from hicpicnunc.web.app import create_app

logger = get_logger(__name__)


def main() -> None:
    desktop = getattr(sys, "frozen", False)
    if desktop:
        running = running_instance_url(settings.instance_path)
        if running:
            logger.info("Hic Pic Nunc is already running at {}", running)
            webbrowser.open(running)
            return

    lifecycle = Lifecycle() if settings.auto_exit else None
    app = create_app(lifecycle)
    # Use a stable development port, but avoid collisions in a frozen desktop app.
    default_port = "0" if desktop else "5001"
    port = int(os.environ.get("PORT", default_port))
    # Threaded, so a long export or a pending Google sign-in doesn't freeze the UI.
    server = make_server("127.0.0.1", port, app, threaded=True)
    url = f"http://127.0.0.1:{server.server_port}"
    logger.info("Hic Pic Nunc is running at {}", url)
    if desktop:
        record_instance(settings.instance_path, server.server_port)
    if lifecycle:
        watch(server, lifecycle)
    threading.Timer(0.2, webbrowser.open, args=(url,)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        if desktop:
            forget_instance(settings.instance_path, server.server_port)
    logger.info("Hic Pic Nunc stopped")


if __name__ == "__main__":
    main()
