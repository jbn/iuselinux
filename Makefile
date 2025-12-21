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
	-launchctl unload ~/Library/LaunchAgents/com.iuselinux.server.plist 2>/dev/null
	-launchctl unload ~/Library/LaunchAgents/com.iuselinux.tray.plist 2>/dev/null
	-uvx iuselinux service uninstall
	rm -f ~/Library/LaunchAgents/com.iuselinux.server.plist
	rm -f ~/Library/LaunchAgents/com.iuselinux.tray.plist
	rm -rf ~/.local/share/uv/tools/iuselinux
	rm -f ~/.local/bin/iuselinux
	rm -rf ~/Library/Application\ Support/iuselinux/
	rm -rf ~/Library/Logs/iuselinux/
	rm -rf ~/Applications/iUseLinux.app/

reset-install: remove-install
	uv tool install --force -e .
	uvx iuselinux service install --force
