# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller build definition for desktop releases."""

import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import copy_metadata

ROOT = Path(SPECPATH).parent
PACKAGE = ROOT / "src" / "hicpicnunc"

datas = [
    (str(PACKAGE / "core" / "metadata_fields.yaml"), "hicpicnunc/core"),
    (str(PACKAGE / "web" / "static"), "hicpicnunc/web/static"),
    (str(PACKAGE / "web" / "templates"), "hicpicnunc/web/templates"),
    (str(PACKAGE / "web" / "locales"), "hicpicnunc/web/locales"),
    *copy_metadata("hicpicnunc"),  # lets importlib.metadata report __version__
]

oauth_client = Path(
    os.environ.get("GOOGLE_OAUTH_CLIENT_SECRETS", ROOT / "credentials" / "client_secrets.json")
)
if oauth_client.is_file():
    datas.append((str(oauth_client), "credentials"))
else:
    print("Building without a Google OAuth client; Google Photos sign-in will be unavailable.")

a = Analysis(
    [str(PACKAGE / "__main__.py")],
    pathex=[str(ROOT / "src")],
    binaries=[],
    datas=datas,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Hic Pic Nunc",
    console=False,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name="Hic Pic Nunc",
)

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="Hic Pic Nunc.app",
        bundle_identifier="com.nicopietrusco.hicpicnunc",
    )
