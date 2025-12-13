.PHONY: test run ship clean build

test:
	uv run pytest

run:
	uv run iuselinux

build:
	uv build

ship: clean build
	uv publish

clean:
	rm -rf dist/
