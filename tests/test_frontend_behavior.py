from pathlib import Path
import shutil
import subprocess


def test_frontend_selection_and_sizes():
    node = shutil.which('node')
    assert node, 'Node runtime is required to execute the Vanilla JS behavior tests (no build tools)'
    completed = subprocess.run([node, str(Path(__file__).with_name('format_behavior.cjs'))], capture_output=True, text=True, shell=False, timeout=15)
    assert completed.returncode == 0, completed.stdout + completed.stderr
