# Build universal binary for contact_lookup

BINARY = contact_lookup
SOURCE = ContactLookup.swift
BUILD_DIR = build

# Target directories
X86_BINARY = $(BUILD_DIR)/$(BINARY)_x86_64
ARM_BINARY = $(BUILD_DIR)/$(BINARY)_arm64
UNIVERSAL = $(BUILD_DIR)/$(BINARY)

# Install location (inside the Python package)
INSTALL_DIR = ../imessage_gateway/bin

.PHONY: all clean install

all: $(UNIVERSAL)

$(BUILD_DIR):
	mkdir -p $(BUILD_DIR)

# Intel slice (macOS 10.11+)
$(X86_BINARY): $(SOURCE) | $(BUILD_DIR)
	swiftc -O -target x86_64-apple-macosx10.11 $(SOURCE) -o $(X86_BINARY)

# Apple Silicon slice (macOS 11.0+)
$(ARM_BINARY): $(SOURCE) | $(BUILD_DIR)
	swiftc -O -target arm64-apple-macosx11.0 $(SOURCE) -o $(ARM_BINARY)

# Universal binary
$(UNIVERSAL): $(X86_BINARY) $(ARM_BINARY)
	lipo -create -output $(UNIVERSAL) $(X86_BINARY) $(ARM_BINARY)
	@echo "Built universal binary: $(UNIVERSAL)"
	@lipo -info $(UNIVERSAL)

install: $(UNIVERSAL)
	mkdir -p $(INSTALL_DIR)
	cp $(UNIVERSAL) $(INSTALL_DIR)/$(BINARY)
	chmod +x $(INSTALL_DIR)/$(BINARY)
	@echo "Installed to $(INSTALL_DIR)/$(BINARY)"

clean:
	rm -rf $(BUILD_DIR)
