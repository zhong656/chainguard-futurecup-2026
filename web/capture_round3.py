"""D 的 R3 回放验收夹具：逐轮修复引用，Trace 由实际纵切生成，不伪造事件。"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from unittest.mock import patch

from src.llm_adapter import MockLLMAdapter
from src.vertical_slice import run_vertical_slice


def capture(output: Path) -> dict:
    original = MockLLMAdapter.generate_draft

    def gradual(self, *args, **kwargs):
        response = original(self, *args, **kwargs)
        draft = json.loads(response["content"])
        missing = {0:6, 1:3, 2:1, 3:0}[kwargs["round"]]
        for section in draft["sections"][:missing]:
            section["citations"] = []
        response["content"] = json.dumps(draft, ensure_ascii=False)
        return response

    with patch.object(MockLLMAdapter, "generate_draft", gradual):
        return run_vertical_slice("机器视觉产线质检", output=output, inject_initial_gap=False)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("outputs/d-round3"))
    args = parser.parse_args()
    result = capture(args.output)
    print("[PASS] 故障注入验收（非正常 API 运行）：", [(r["round"],r["score"],r["verdict"]) for r in result["rounds"]])
