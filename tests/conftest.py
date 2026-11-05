"""使 pytest 命令与 python -m pytest 使用相同的仓库导入根目录。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
