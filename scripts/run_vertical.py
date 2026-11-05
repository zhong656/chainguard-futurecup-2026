#!/usr/bin/env python3
"""一条命令跑通离线纵切，并输出四件交付物。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.vertical_slice import run_vertical_slice  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", default="用机器视觉升级精密零件产线质检")
    parser.add_argument("--output", type=Path, default=ROOT / "outputs" / "_vertical")
    args = parser.parse_args()
    try:
        result = run_vertical_slice(args.request, output=args.output)
    except Exception as exc:
        print(f"[FAIL] 纵切未完成：{exc}", file=sys.stderr)
        return 1
    print(f"[PASS] Mock 纵切完成；修订轮次={result['round']}；评分={result['scorecard']['score']:.3f}")
    print(f"交付包：{args.output.resolve() / 'delivery_artifact.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
