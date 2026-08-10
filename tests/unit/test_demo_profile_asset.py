from __future__ import annotations

import re
from pathlib import Path

DEMO_DIR = Path(__file__).resolve().parents[2] / "data" / "demo"
DEMO_PROFILES = (
    DEMO_DIR / "小刘-产品与解决方案简历.md",
    DEMO_DIR / "小刘-机器人方向简历.md",
)


def test_public_demo_profile_is_explicitly_synthetic_without_contact_data() -> None:
    for profile_path in DEMO_PROFILES:
        content = profile_path.read_text(encoding="utf-8")

        assert "SYNTHETIC DEMO" in content
        assert "上海交通大学" in content
        assert not re.search(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", content)
        assert not re.search(r"(?<!\d)1[3-9]\d{9}(?!\d)", content)
        assert "/Users/" not in content
