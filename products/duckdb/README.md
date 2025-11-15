# PostHog DuckDB Extension

Query your PostHog data directly from DuckDB using HogQL!

## Features

- 🔍 Query PostHog data using HogQL directly from DuckDB
- 🔄 Automatic type mapping from PostHog/ClickHouse types to DuckDB types
- 🔗 Join PostHog data with local data
- 📊 Export PostHog data to Parquet, CSV, or any DuckDB-supported format
- ⚡ Full support for HogQL features (events, persons, properties, etc.)
- 🔐 Environment variable configuration for easy setup

## Quick Start

### 1. Build the Extension

```bash
# Clone with submodules
git clone --recurse-submodules https://github.com/PostHog/posthog-duckdb.git
cd posthog-duckdb

# Set up vcpkg (for dependencies)
cd /tmp
git clone https://github.com/Microsoft/vcpkg.git
./vcpkg/bootstrap-vcpkg.sh -disableMetrics

# Build the extension
cd -
export VCPKG_TOOLCHAIN_PATH=/tmp/vcpkg/scripts/buildsystems/vcpkg.cmake
GEN=ninja make
```

The extension will be built to: `build/release/extension/posthog/posthog.duckdb_extension`

### 2. Configure PostHog Credentials

```bash
export POSTHOG_HOST="https://us.posthog.com"  # or https://eu.posthog.com
export POSTHOG_PROJECT_ID="YOUR_PROJECT_ID"
export POSTHOG_API_KEY="YOUR_PERSONAL_API_KEY"
```

### 3. Use in DuckDB

```sql
-- Load the extension
LOAD 'build/release/extension/posthog/posthog.duckdb_extension';

-- Query your PostHog data
SELECT * FROM posthog_query('
    SELECT event, COUNT() as count
    FROM events
    GROUP BY event
    ORDER BY count DESC
    LIMIT 10
');
```

## Usage Examples

### Get Events from Last 7 Days

```sql
SELECT
    event,
    timestamp,
    distinct_id
FROM posthog_query('
    SELECT event, timestamp, distinct_id
    FROM events
    WHERE timestamp > now() - interval 7 day
')
ORDER BY timestamp DESC;
```

### Join with Local Data

```sql
CREATE TABLE user_segments (distinct_id VARCHAR, segment VARCHAR);
INSERT INTO user_segments VALUES ('user123', 'premium'), ('user456', 'free');

SELECT
    e.event,
    s.segment,
    COUNT(*) as event_count
FROM posthog_query('SELECT event, distinct_id FROM events') e
JOIN user_segments s ON e.distinct_id = s.distinct_id
GROUP BY e.event, s.segment;
```

### Export to Parquet

```sql
COPY (
    SELECT * FROM posthog_query('
        SELECT * FROM events
        WHERE timestamp > today() - interval 30 day
    ')
) TO 'last_30_days_events.parquet';
```

### Work with JSON Properties

```sql
SELECT
    event,
    json_extract_string(properties, '$.url') as url,
    json_extract_string(properties, '$.browser') as browser
FROM posthog_query('SELECT event, properties FROM events LIMIT 100');
```

## Documentation

For detailed documentation, see [USAGE.md](USAGE.md) including:

- Complete API reference
- Type mapping details
- HogQL examples
- Configuration options

## Type Mapping

The extension automatically maps PostHog/ClickHouse types to DuckDB types:

| PostHog Type | DuckDB Type | Notes |
|--------------|-------------|-------|
| DateTime64   | TIMESTAMP   | Automatically parsed from ISO strings |
| String       | VARCHAR     | |
| UUID         | VARCHAR     | |
| Int64        | BIGINT      | |
| Array(T)     | VARCHAR     | As JSON - use `json_extract()` |
| Properties   | VARCHAR     | As JSON - use `json_extract_string()` |

See [USAGE.md](USAGE.md) for the complete type mapping table.

## Requirements

- CMake >= 3.5
- C++ compiler with C++11 support
- DuckDB v1.4.2+
- PostHog account with Personal API Key

## Finding Your Credentials

**PostHog Instance URL:**

- US Cloud: `https://us.posthog.com`
- EU Cloud: `https://eu.posthog.com`
- Self-hosted: Your custom domain

**Project ID:**

- Found in PostHog project settings
- Visible in the URL when viewing your project

**Personal API Key:**

1. Go to Settings
2. Navigate to "Personal API Keys"
3. Click "+ Create a Personal API Key"

## Limitations

- Rate limits: 120 HogQL queries/hour (PostHog limit)
- Max result size: 50,000 rows per query (PostHog limit)
- Results are cached in memory during query execution

## License

MIT License - see LICENSE file for details
