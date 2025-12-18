.PHONY: test run ship clean build reset-install

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

reset-install:
	-uvx iuselinux service uninstall
	rm -rf ~/Library/Application\ Support/iuselinux/
	rm -rf ~/Library/Logs/iuselinux/
