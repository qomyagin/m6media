SHELL := /bin/bash
PYTHON ?= python3

.PHONY: help test check smoke clean

help:
	$(PYTHON) m6media.py --help

test:
	$(PYTHON) -m unittest discover -s tests -v

check:
	$(PYTHON) -m py_compile m6media.py
	$(PYTHON) -m unittest discover -s tests -v

smoke:
	$(PYTHON) tests/smoke_test.py

clean:
	rm -rf __pycache__ tests/__pycache__ build dist ./*.egg-info
