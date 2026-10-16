import shutil
import subprocess
from pathlib import Path

import pytest


def test_picker_security_rendering():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is required for the picker JavaScript security regression test")

    test_file = Path(__file__).with_name("picker_security.test.mjs")
    subprocess.run([node, "--test", str(test_file)], check=True, cwd=test_file.parents[2])
