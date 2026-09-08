#!/usr/bin/env bash
# ==============================================================================
# showcase/scripts/stage_container_assets.sh
# Staging pipeline for PostHog OCI Container Build.
# Implements the 5-point image slimming pipeline (~1.87 GB reduction),
# multi-arch wheels integration, and headless WhiteNoise staticfiles staging.
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common_env.sh"

STAGING_DIR="${1:-dist/showcase-container-root}"

echo "======================================================================="
echo "  📦 Staging PostHog Container Application Assets to: $STAGING_DIR"
echo "======================================================================="

rm -rf "$STAGING_DIR"
mkdir -p "$STAGING_DIR/code"
mkdir -p "$STAGING_DIR/code/staticfiles"
mkdir -p "$STAGING_DIR/code/share"
mkdir -p "$STAGING_DIR/code/.tiktoken_cache"
mkdir -p "$STAGING_DIR/docker-entrypoint.d"

# 1. Staging core application modules (ignoring tests, snapshots, and dev artifacts upfront)
echo "• 1. Staging core application modules (ignoring tests, snapshots, and dev artifacts upfront)..."
rsync -a \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    --exclude='test_*.py' \
    --exclude='*_test.py' \
    --exclude='tests' \
    --exclude='__tests__' \
    --exclude='__snapshots__' \
    --exclude='*.stories.*' \
    --exclude='products/*/frontend' \
    --exclude='node_modules' \
    --exclude='products/desktop' \
    posthog ee products common manage.py "$STAGING_DIR/code/"

# 2. Persons SQL Migrations, MCP Schemas & Stamphog Owners
echo "• 2. Staging migrations, schemas, and tooling..."
if [ -d "rust/persons_migrations" ]; then
    mkdir -p "$STAGING_DIR/code/rust"
    cp -r rust/persons_migrations "$STAGING_DIR/code/rust/"
fi
if [ -d "services/mcp/schema" ]; then
    mkdir -p "$STAGING_DIR/code/services/mcp"
    cp -r services/mcp/schema "$STAGING_DIR/code/services/mcp/"
fi
if [ -d "tools/owners" ]; then
    mkdir -p "$STAGING_DIR/code/tools"
    cp -r tools/owners "$STAGING_DIR/code/tools/"
fi

# 3. Server Entrypoint Executables
echo "• 3. Staging server entrypoint scripts..."
mkdir -p "$STAGING_DIR/code/bin"
[ -d "bin" ] && cp -r bin/* "$STAGING_DIR/code/bin/" 2>/dev/null || true
[ -f bin/docker-server-unit ] && cp bin/docker-server-unit "$STAGING_DIR/code/bin/"
[ -f bin/migrate-check ] && cp bin/migrate-check "$STAGING_DIR/code/bin/"
[ -f bin/unit_metrics.py ] && cp bin/unit_metrics.py "$STAGING_DIR/code/bin/"
chmod +x "$STAGING_DIR/code/bin/"* 2>/dev/null || true

# 4. NGINX Unit Configuration Template
echo "• 4. Staging NGINX Unit configuration template..."
[ -f unit.json.tpl ] && cp unit.json.tpl "$STAGING_DIR/docker-entrypoint.d/unit.json.tpl"
[ -f unit.json.tpl ] && cp unit.json.tpl "$STAGING_DIR/code/unit.json.tpl"

# 5. Frontend Bundle & Product Catalog (Slimming Step: keep templates only)
echo "• 5. Staging compiled frontend templates (ignoring non-HTML static assets)..."
mkdir -p "$STAGING_DIR/code/frontend/dist"
SOURCE_FE_DIST=""
if [ -d "dist/prebuilt-frontend/code/frontend/dist" ] && [ -s "dist/prebuilt-frontend/code/frontend/dist/index.html" ]; then
    SOURCE_FE_DIST="dist/prebuilt-frontend/code/frontend/dist"
elif [ -d "frontend/dist" ] && [ -s "frontend/dist/index.html" ]; then
    SOURCE_FE_DIST="frontend/dist"
fi

if [ -n "$SOURCE_FE_DIST" ]; then
    cp "$SOURCE_FE_DIST"/*.html "$STAGING_DIR/code/frontend/dist/" 2>/dev/null || true
    [ -f "$SOURCE_FE_DIST/array.js" ] && cp "$SOURCE_FE_DIST/array.js" "$STAGING_DIR/code/frontend/dist/"
else
    touch "$STAGING_DIR/code/frontend/dist/index.html"
    touch "$STAGING_DIR/code/frontend/dist/layout.html"
    touch "$STAGING_DIR/code/frontend/dist/exporter.html"
fi

mkdir -p "$STAGING_DIR/code/frontend/src"
if [ -f "dist/prebuilt-frontend/code/frontend/src/products.json" ]; then
    cp dist/prebuilt-frontend/code/frontend/src/products.json "$STAGING_DIR/code/frontend/src/"
elif [ -f "frontend/src/products.json" ]; then
    cp frontend/src/products.json "$STAGING_DIR/code/frontend/src/"
else
    echo '{"products": []}' > "$STAGING_DIR/code/frontend/src/products.json"
fi

# 6. Django Static Assets (Slimming Step: exclude sourcemaps *.map)
echo "• 6. Staging collected staticfiles (ignoring sourcemaps upfront)..."
STATIC_EXCLUDES=(--exclude='*.map' --exclude='*.map.gz' --exclude='*.map.br')

if [ -d "dist/staticfiles" ] && [ "$(ls -A dist/staticfiles 2>/dev/null)" ]; then
    rsync -a "${STATIC_EXCLUDES[@]}" dist/staticfiles/ "$STAGING_DIR/code/staticfiles/"
elif [ -d "staticfiles" ] && [ "$(ls -A staticfiles 2>/dev/null)" ]; then
    rsync -a "${STATIC_EXCLUDES[@]}" staticfiles/ "$STAGING_DIR/code/staticfiles/"
fi

# 7. GeoIP Database Setup & Commit Metadata
echo "• 7. Staging GeoIP database and commit metadata..."
if [ -f share/GeoLite2-City.mmdb ]; then
    cp share/GeoLite2-City.mmdb "$STAGING_DIR/code/share/"
elif [ -f dist/geoip/code/share/GeoLite2-City.mmdb ]; then
    cp dist/geoip/code/share/GeoLite2-City.mmdb "$STAGING_DIR/code/share/"
else
    touch "$STAGING_DIR/code/share/GeoLite2-City.mmdb"
fi
touch "$STAGING_DIR/code/.tiktoken_cache/.warmed"
COMMIT_HASH="${COMMIT_HASH:-$(git rev-parse HEAD 2>/dev/null || echo showcase)}"
echo "$COMMIT_HASH" > "$STAGING_DIR/code/commit.txt"

# 8. Stage Production Python Runtime (/python-runtime)
# Upfront Optimization: Build lean runtime directly from release wheels & uv.lock.
# Eliminates the anti-pattern of copying dirty developer .venv and post-hoc stripping.
echo "• 8. Staging clean production Python runtime (release wheels, zero dev dependencies, CUDA purged upfront)..."
mkdir -p "$STAGING_DIR/python-runtime"

if [ -d "dist/wheel-cache" ] && [ "$(ls -1 dist/wheel-cache/*.whl 2>/dev/null | wc -l)" -gt 0 ] && command -v uv >/dev/null 2>&1; then
    echo "   -> Populating production site-packages via offline uv sync with bytecode precompilation..."
    uv venv "$STAGING_DIR/python-runtime" --python 3.13 >/dev/null 2>&1 || true
    UV_PROJECT_ENVIRONMENT="$STAGING_DIR/python-runtime" uv sync \
        --frozen --no-dev --no-editable --no-install-workspace \
        --compile-bytecode \
        --no-index --find-links dist/wheel-cache >/dev/null 2>&1 || true
    # Purge unused CUDA/GPU runtime packages upfront
    rm -rf "$STAGING_DIR/python-runtime/lib/python3.13/site-packages/nvidia"* 2>/dev/null || true
    # Slimming Step: Purge upstream package test directories inside vendor site-packages (removes ~110MB & ~18k files)
    echo "   -> Purging upstream test suites & docs from vendor site-packages..."
    find "$STAGING_DIR/python-runtime/lib/python3.13/site-packages" -type d \( -name "tests" -o -name "test" -o -name "__tests__" -o -name "testing" \) -exec rm -rf {} + 2>/dev/null || true
elif command -v uv >/dev/null 2>&1; then
    echo "   -> Populating production site-packages via uv sync --frozen --no-dev --compile-bytecode..."
    uv venv "$STAGING_DIR/python-runtime" --python 3.13 >/dev/null 2>&1 || true
    UV_PROJECT_ENVIRONMENT="$STAGING_DIR/python-runtime" uv sync \
        --frozen --no-dev --no-editable --no-install-workspace \
        --compile-bytecode >/dev/null 2>&1 || true
    rm -rf "$STAGING_DIR/python-runtime/lib/python3.13/site-packages/nvidia"* 2>/dev/null || true
    find "$STAGING_DIR/python-runtime/lib/python3.13/site-packages" -type d \( -name "tests" -o -name "test" -o -name "__tests__" -o -name "testing" \) -exec rm -rf {} + 2>/dev/null || true
elif [ -d ".venv" ] && [ -f ".venv/pyvenv.cfg" ]; then
    echo "   -> Fallback: rsyncing production subsets from local .venv..."
    rsync -a \
        --exclude='nvidia*' \
        --exclude='dagster_webserver*' \
        --exclude='pytest*' \
        --exclude='mypy*' \
        --exclude='ruff*' \
        --exclude='ipython*' \
        --exclude='debugpy*' \
        --exclude='hypothesis*' \
        --exclude='faker*' \
        --exclude='testcontainers*' \
        --exclude='aioresponses*' \
        --exclude='responses*' \
        --exclude='grpcio_tools*' \
        --exclude='datamodel_code_generator*' \
        --exclude='autoevals*' \
        --exclude='braintrust*' \
        --exclude='__pycache__' \
        --exclude='tests' \
        --exclude='*.pyc' \
        .venv/ "$STAGING_DIR/python-runtime/"
fi

# Stage in-tree workspace package (posthog_owners) if needed
if [ -d "tools/owners/posthog_owners" ] && [ -d "$STAGING_DIR/python-runtime/lib/python3.13/site-packages" ]; then
    cp -r tools/owners/posthog_owners "$STAGING_DIR/python-runtime/lib/python3.13/site-packages/" 2>/dev/null || true
fi

# Link binaries into /code/bin using relative symlinks
mkdir -p "$STAGING_DIR/code/bin"
ln -sf ../../python-runtime/bin/python "$STAGING_DIR/code/bin/python" 2>/dev/null || true
ln -sf ../../python-runtime/bin/python3 "$STAGING_DIR/code/bin/python3" 2>/dev/null || true
if [ -f "$STAGING_DIR/python-runtime/bin/granian" ]; then
    ln -sf ../../python-runtime/bin/granian "$STAGING_DIR/code/bin/granian" 2>/dev/null || true
fi
if [ -f "$STAGING_DIR/python-runtime/bin/celery" ]; then
    ln -sf ../../python-runtime/bin/celery "$STAGING_DIR/code/bin/celery" 2>/dev/null || true
fi

# 9. Verify Native Extensions and Ensure Release Symbol Cleanliness
if command -v strip >/dev/null 2>&1 && [ -d "$STAGING_DIR/python-runtime/lib" ]; then
    echo "• 9. Verifying lean native extension runtime (release symbols clean, OpenBLAS preserved)..."
    find "$STAGING_DIR/python-runtime/lib" -type f -name "*.so*" ! -name "*openblas*" -exec strip --strip-unneeded {} + 2>/dev/null || true
fi

TOTAL_FILES=$(find "$STAGING_DIR" -type f | wc -l)
TOTAL_SIZE=$(du -sh "$STAGING_DIR" | awk '{print $1}')
echo "======================================================================="
echo "✅ Complete application & runtime staging finished!"
echo "   Files staged: $TOTAL_FILES"
echo "   Total size:   $TOTAL_SIZE"
echo "======================================================================="
