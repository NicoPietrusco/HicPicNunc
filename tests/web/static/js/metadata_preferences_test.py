import shutil
import subprocess
from pathlib import Path

import pytest


def test_settings_popover_behaviour():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is required for the Settings popover JavaScript test")

    test_file = Path(__file__).with_name("metadata_preferences.test.mjs")
    subprocess.run([node, "--test", str(test_file)], check=True, cwd=test_file.parents[4])
