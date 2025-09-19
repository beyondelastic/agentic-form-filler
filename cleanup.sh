#!/bin/bash

# Cleanup script for agentic-form-filler project
# Removes temporary files, logs, caches, and generated outputs

echo "🧹 Cleaning up agentic-form-filler workspace..."

# Remove Python cache files
echo "  - Removing Python cache files..."
find . -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
find . -name "*.pyc" -delete 2>/dev/null || true
find . -name "*.pyo" -delete 2>/dev/null || true

# Remove generated output files but keep .gitkeep
echo "  - Cleaning output directory..."
find ./output -name "*.pdf" -o -name "*.json" | grep -v ".gitkeep" | xargs rm -f 2>/dev/null || true

# Remove LangGraph state/checkpoint files
echo "  - Clearing LangGraph state files..."
rm -f .langgraph_api/*.pckl 2>/dev/null || true

# Remove system files
echo "  - Removing system files..."
find . -name ".DS_Store" -delete 2>/dev/null || true

# Remove temporary and backup files
echo "  - Removing temporary files..."
find . -name "*.tmp" -delete 2>/dev/null || true
find . -name "*.temp" -delete 2>/dev/null || true
find . -name "*~" -delete 2>/dev/null || true
find . -name "*.bak" -delete 2>/dev/null || true

# Remove log files
echo "  - Removing log files..."
find . -name "*.log" -delete 2>/dev/null || true

echo "✅ Cleanup complete!"

# Show what's left in key directories
echo ""
echo "📂 Current state:"
echo "Output directory: $(ls -1 output/ | wc -l | tr -d ' ') files"
echo "LangGraph API directory: $(ls -1 .langgraph_api/ 2>/dev/null | wc -l | tr -d ' ') files"
echo "Python cache directories: $(find . -name "__pycache__" -type d | wc -l | tr -d ' ') found"