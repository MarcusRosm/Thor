#!/usr/bin/env bash
# Fix uv 0.9.28 bug: .pth files missing trailing newline
# This prevents Python from loading editable package paths into sys.path

set -euo pipefail

echo "🔍 Fixing uv .pth file bug..."

# Find the virtual environment's site-packages directory
VENV_DIR=".venv"
if [ ! -d "$VENV_DIR" ]; then
    echo "❌ Error: Virtual environment not found at $VENV_DIR"
    exit 1
fi

PYTHON_VERSION=$(ls "$VENV_DIR/lib/" | grep -E '^python3\.[0-9]+$' | head -1)
if [ -z "$PYTHON_VERSION" ]; then
    echo "❌ Error: Could not determine Python version"
    exit 1
fi

SITE_PACKAGES="$VENV_DIR/lib/$PYTHON_VERSION/site-packages"
if [ ! -d "$SITE_PACKAGES" ]; then
    echo "❌ Error: site-packages directory not found at $SITE_PACKAGES"
    exit 1
fi

echo "📁 Found site-packages: $SITE_PACKAGES"

# Find and fix all .pth files missing trailing newlines
FIXED_COUNT=0
for PTH_FILE in "$SITE_PACKAGES"/*.pth; do
    if [ ! -f "$PTH_FILE" ]; then
        continue
    fi
    
    # Check if file is missing trailing newline
    if [ -s "$PTH_FILE" ] && [ "$(tail -c 1 "$PTH_FILE" | od -An -tx1)" != " 0a" ]; then
        echo "🔧 Fixing: $(basename "$PTH_FILE")"
        echo "" >> "$PTH_FILE"
        FIXED_COUNT=$((FIXED_COUNT + 1))
    fi
done

if [ $FIXED_COUNT -eq 0 ]; then
    echo "✅ No .pth files needed fixing"
else
    echo "✅ Fixed $FIXED_COUNT .pth file(s)"
fi

# Verify the fix works
echo ""
echo "🧪 Testing import..."
if uv run python -c "import thor; print('✅ Success! thor module importable')" 2>/dev/null; then
    echo "🎉 Fix applied successfully!"
else
    echo "❌ Import still failing. You may need to recreate the venv:"
    echo "   rm -rf .venv && uv sync"
    exit 1
fi
