.PHONY: install test lint demo all validity clean

install:
	pip install -e ".[dev]"

test:
	pytest -q

lint:
	ruff check src tests scripts

demo:
	recheck demo

# every experiment that needs no model, then the direct check of Theorem 3
all:
	recheck all
	python scripts/validity_sim.py

validity:
	python scripts/validity_sim.py

clean:
	rm -rf runs .pytest_cache .ruff_cache
