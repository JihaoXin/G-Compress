#!/bin/bash
# Fix for Markdown PDF extension - adds stub libasound.so.2 to library path

# Add local lib directory to LD_LIBRARY_PATH
export LD_LIBRARY_PATH="$HOME/.local/lib:$LD_LIBRARY_PATH"

echo "✅ Fixed: Added stub libasound.so.2 to library path"
echo ""
echo "To make this permanent, add this line to your ~/.bashrc:"
echo "export LD_LIBRARY_PATH=\"\$HOME/.local/lib:\$LD_LIBRARY_PATH\""
echo ""
echo "Or run this script before using the Markdown PDF extension:"
echo "  source $(pwd)/fix_markdown_pdf.sh"
