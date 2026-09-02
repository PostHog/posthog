#!/bin/bash

# Clean PostHog app data from macOS
#
# Usage:
#   ./scripts/clean-posthog-code-macos.sh           # Clean dev data only
#   ./scripts/clean-posthog-code-macos.sh --all     # Clean all data (dev + production + legacy)
#   ./scripts/clean-posthog-code-macos.sh --app     # Clean all data and delete app

set -e

DELETE_APP=false
CLEAN_ALL=false

for arg in "$@"; do
  case $arg in
    --all)
      CLEAN_ALL=true
      shift
      ;;
    --app)
      DELETE_APP=true
      CLEAN_ALL=true
      shift
      ;;
    -h|--help)
      echo "Usage: $0 [--all] [--app]"
      echo ""
      echo "Options:"
      echo "  --all    Clean all data (dev + production + legacy). Without this, only dev data is cleaned."
      echo "  --app    Clean all data and delete PostHog.app from /Applications"
      echo ""
      echo "By default (no flags), only dev data is cleaned:"
      echo "  - ~/Library/Application Support/@posthog/posthog-code-dev"
      echo ""
      echo "With --all, also removes:"
      echo "  - ~/Library/Application Support/@posthog/posthog-code"
      echo "  - ~/Library/Application Support/@posthog/Array (legacy)"
      echo "  - ~/Library/Application Support/@posthog/Twig (legacy)"
      echo "  - ~/Library/Application Support/@posthog/twig-dev (legacy)"
      echo "  - ~/Library/Preferences/com.posthog.array.plist"
      echo "  - ~/Library/Caches/com.posthog.array"
      echo "  - ~/.posthog-code (logs and cache)"
      echo "  - ~/Library/Logs/PostHog"
      echo "  - ~/Library/Logs/PostHog Code (legacy)"
      echo "  - ~/Library/Saved Application State/com.posthog.array.savedState"
      exit 0
      ;;
  esac
done

if [ "$CLEAN_ALL" = true ]; then
  echo "Cleaning all PostHog data from macOS..."
else
  echo "Cleaning PostHog dev data from macOS..."
fi
echo ""

# Dev data (always cleaned)
if [ -d "$HOME/Library/Application Support/@posthog/posthog-code-dev" ]; then
  echo "Removing ~/Library/Application Support/@posthog/posthog-code-dev"
  rm -rf "$HOME/Library/Application Support/@posthog/posthog-code-dev"
fi

if [ "$CLEAN_ALL" = true ]; then
  # Application Support - production
  if [ -d "$HOME/Library/Application Support/@posthog/posthog-code" ]; then
    echo "Removing ~/Library/Application Support/@posthog/posthog-code"
    rm -rf "$HOME/Library/Application Support/@posthog/posthog-code"
  fi

  # Application Support - legacy locations
  if [ -d "$HOME/Library/Application Support/@posthog/Array" ]; then
    echo "Removing ~/Library/Application Support/@posthog/Array"
    rm -rf "$HOME/Library/Application Support/@posthog/Array"
  fi

  if [ -d "$HOME/Library/Application Support/@posthog/Twig" ]; then
    echo "Removing ~/Library/Application Support/@posthog/Twig"
    rm -rf "$HOME/Library/Application Support/@posthog/Twig"
  fi

  if [ -d "$HOME/Library/Application Support/@posthog/twig-dev" ]; then
    echo "Removing ~/Library/Application Support/@posthog/twig-dev"
    rm -rf "$HOME/Library/Application Support/@posthog/twig-dev"
  fi

  if [ -d "$HOME/Library/Application Support/twig" ]; then
    echo "Removing ~/Library/Application Support/twig"
    rm -rf "$HOME/Library/Application Support/twig"
  fi

  if [ -d "$HOME/Library/Application Support/Twig" ]; then
    echo "Removing ~/Library/Application Support/Twig"
    rm -rf "$HOME/Library/Application Support/Twig"
  fi

  # Preferences
  if [ -f "$HOME/Library/Preferences/com.posthog.array.plist" ]; then
    echo "Removing ~/Library/Preferences/com.posthog.array.plist"
    rm -f "$HOME/Library/Preferences/com.posthog.array.plist"
  fi

  if [ -f "$HOME/Library/Preferences/com.posthog.twig.plist" ]; then
    echo "Removing ~/Library/Preferences/com.posthog.twig.plist"
    rm -f "$HOME/Library/Preferences/com.posthog.twig.plist"
  fi

  # Caches
  if [ -d "$HOME/Library/Caches/com.posthog.array" ]; then
    echo "Removing ~/Library/Caches/com.posthog.array"
    rm -rf "$HOME/Library/Caches/com.posthog.array"
  fi

  if [ -d "$HOME/Library/Caches/com.posthog.twig" ]; then
    echo "Removing ~/Library/Caches/com.posthog.twig"
    rm -rf "$HOME/Library/Caches/com.posthog.twig"
  fi

  if [ -d "$HOME/Library/Caches/twig" ]; then
    echo "Removing ~/Library/Caches/twig"
    rm -rf "$HOME/Library/Caches/twig"
  fi

  if [ -d "$HOME/Library/Caches/Twig" ]; then
    echo "Removing ~/Library/Caches/Twig"
    rm -rf "$HOME/Library/Caches/Twig"
  fi

  # Home directory data (logs and cache)
  if [ -d "$HOME/.posthog-code" ]; then
    echo "Removing ~/.posthog-code"
    rm -rf "$HOME/.posthog-code"
  fi

  # Logs
  if [ -d "$HOME/Library/Logs/PostHog" ]; then
    echo "Removing ~/Library/Logs/PostHog"
    rm -rf "$HOME/Library/Logs/PostHog"
  fi

  if [ -d "$HOME/Library/Logs/PostHog Code" ]; then
    echo "Removing ~/Library/Logs/PostHog Code"
    rm -rf "$HOME/Library/Logs/PostHog Code"
  fi

  if [ -d "$HOME/Library/Logs/twig" ]; then
    echo "Removing ~/Library/Logs/twig"
    rm -rf "$HOME/Library/Logs/twig"
  fi

  if [ -d "$HOME/Library/Logs/Twig" ]; then
    echo "Removing ~/Library/Logs/Twig"
    rm -rf "$HOME/Library/Logs/Twig"
  fi

  # Saved Application State
  if [ -d "$HOME/Library/Saved Application State/com.posthog.array.savedState" ]; then
    echo "Removing ~/Library/Saved Application State/com.posthog.array.savedState"
    rm -rf "$HOME/Library/Saved Application State/com.posthog.array.savedState"
  fi

  if [ -d "$HOME/Library/Saved Application State/com.posthog.twig.savedState" ]; then
    echo "Removing ~/Library/Saved Application State/com.posthog.twig.savedState"
    rm -rf "$HOME/Library/Saved Application State/com.posthog.twig.savedState"
  fi
fi

# Clean up empty @posthog parent folder if it exists and is empty
if [ -d "$HOME/Library/Application Support/@posthog" ]; then
  rmdir "$HOME/Library/Application Support/@posthog" 2>/dev/null || true
fi

# App (optional, implies --all)
if [ "$DELETE_APP" = true ]; then
  if [ -d "/Applications/PostHog.app" ]; then
    echo "Removing /Applications/PostHog.app"
    rm -rf "/Applications/PostHog.app"
  fi
  if [ -d "/Applications/PostHog Code.app" ]; then
    echo "Removing /Applications/PostHog Code.app"
    rm -rf "/Applications/PostHog Code.app"
  fi
  if [ -d "/Applications/Twig.app" ]; then
    echo "Removing /Applications/Twig.app"
    rm -rf "/Applications/Twig.app"
  fi
  if [ -d "/Applications/Array.app" ]; then
    echo "Removing /Applications/Array.app"
    rm -rf "/Applications/Array.app"
  fi
fi

echo ""
echo "Done!"

if [ "$CLEAN_ALL" = false ]; then
  echo ""
  echo "Note: Only dev data was cleaned. Use --all to clean everything, or --app to also remove the app."
fi
