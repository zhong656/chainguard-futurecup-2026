#!/usr/bin/env python3
"""兼容旧的纵切命令；实际命令行入口见 ``python -m src.run``。"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.run import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
