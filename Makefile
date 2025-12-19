.PHONY: test run ship clean build remove-install reset-install

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

remove-install:
	-uvx iuselinux service uninstall
	rm -rf ~/Library/Application\ Support/iuselinux/
	rm -rf ~/Library/Logs/iuselinux/
	rm -rf ~/Applications/iUseLinux.app/

reset-install: remove-install
	uv tool install -e .
	uvx iuselinux service install
