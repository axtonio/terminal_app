PYTHON ?= python3

.PHONY: quality format
quality:
	$(PYTHON) .quality/run.py quality

format:
	$(PYTHON) .quality/run.py format
