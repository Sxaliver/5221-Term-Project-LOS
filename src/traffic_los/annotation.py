import base64
from pathlib import Path


def make_html(jpeg, width, height):
    """Self-contained local annotation UI; image and scripts never leave the browser."""
    page = Path(__file__).with_name("annotation.html").read_text(encoding="utf-8")
    return page.replace("__WIDTH__", str(width)).replace("__HEIGHT__", str(height)).replace("__IMAGE__", base64.b64encode(jpeg).decode())
