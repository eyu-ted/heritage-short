# One command runs the whole pipeline.
# Windows without make: use `python -m pipeline all` instead (same thing).

PY ?= python

.PHONY: film validate test smoke clean-cache

film:
	$(PY) -m pipeline all

validate:
	$(PY) -m pipeline validate

smoke:
	$(PY) -m pipeline smoke

test:
	$(PY) -m pytest -q

clean-cache:
	$(PY) -m pipeline clean-cache
