SHELL := /bin/bash

.PHONY: help test check smoke clean

help:
	./m6media.py --help

test:
	python3 -m unittest discover -s tests -v

check:
	python3 -m py_compile m6media.py
	python3 -m unittest discover -s tests -v

smoke:
	./tests/smoke_test.sh

clean:
	rm -rf __pycache__ tests/__pycache__ build dist ./*.egg-info
