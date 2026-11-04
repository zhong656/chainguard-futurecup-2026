# ChainGuard 一致性入口
#
# 唯一准入门槛是 `make check`；它只是 scripts/check.py 的薄壳，
# 因此**没装 make 的机器**直接跑 `python scripts/check.py` 也是同一条命令、同一套步骤。
#
#   make check     等价于 python scripts/check.py
#   make contracts 只跑契约与一致性检查
#   make e2e       只跑 Mock 端到端冒烟
#   make test      只跑单元测试

PY ?= python

.PHONY: check contracts test e2e syntax report clean

check:
	$(PY) scripts/check.py

syntax:
	$(PY) -c "import ast,glob;[ast.parse(open(f,encoding='utf-8').read()) for f in glob.glob('scripts/*.py')+glob.glob('src/**/*.py',recursive=True)]"

contracts:
	$(PY) scripts/check_contracts.py

test:
	$(PY) -m pytest -q tests

e2e:
	$(PY) scripts/mock_e2e.py

report: contracts
	@echo "报告已刷新：docs/consistency-report.md"

clean:
	rm -rf outputs/_e2e .pytest_cache
