"""命令行入口：离线运行需求到可核验交付包的完整纵切。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from src.vertical_slice import run_vertical_slice

ROOT = Path(__file__).resolve().parents[1]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", default="用机器视觉升级精密零件产线质检")
    parser.add_argument("--output", type=Path, default=ROOT / "outputs" / "_vertical")
    args = parser.parse_args(argv)
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
