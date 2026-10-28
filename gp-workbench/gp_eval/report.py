"""Self-contained offline report. No CDN, external JavaScript, or network calls."""
import html
import json
from pathlib import Path


def render_report(result, destination):
    template = Path(__file__).with_name("report_template.html").read_text(encoding="utf-8")
    payload = json.dumps(result, ensure_ascii=False, allow_nan=False).replace("<", "\\u003c").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    title = html.escape(result["protocol"]["dataset_label"])
    Path(destination).write_text(template.replace("__REPORT_TITLE__", title).replace("__REPORT_DATA__", payload), encoding="utf-8")
