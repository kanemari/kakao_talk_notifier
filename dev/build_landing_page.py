"""Write docs/invite-done.html from the template in pages.py. Run: python dev/build_landing_page.py

This file is the page friends see after they agree to a friend invite. It is served from the
gh-pages branch (only this file is published there): run dev/publish_landing_page.sh to update
it at https://kanemari.github.io/kakao_talk_notifier/invite-done.html. A test fails if the
file is out of date.
"""
import importlib.util
from pathlib import Path

root = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("pages", root / "custom_components/kakao_talk/pages.py")
pages = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pages)
(root / "docs" / "invite-done.html").write_text(pages.render_landing(), encoding="utf-8", newline="\n")
(root / "docs" / ".nojekyll").write_text("", encoding="utf-8")
print("wrote docs/invite-done.html")
