root_dir := $(shell dirname $(realpath $(lastword $(MAKEFILE_LIST))))

all: coverage flake

flake:
ifneq (, $(shell which black))
	black --check .
endif
	flake8 tests markdowndiff --ignore="E231,E501,W503" --exclude="markdowndiff/diff_match_patch.py"

coverage:
	coverage run pytest tests
	coverage html
	coverage report

test:
	python -m pytest tests
