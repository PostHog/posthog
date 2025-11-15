# PostHog DuckDB Extension

A DuckDB extension that enables querying PostHog data directly from DuckDB using HogQL.

## Features

- Query PostHog data using HogQL directly from DuckDB
- Automatic type mapping from PostHog/ClickHouse types to DuckDB types
- Combine PostHog data with local data using SQL joins
- Export PostHog data to Parquet, CSV, or other formats
- Full support for HogQL features (events, persons, properties, etc.)

## Installation

### Prerequisites

- CMake >= 3.5
- C++ compiler with C++11 support
- vcpkg (automatically set up during build)

### Building from Source

```bash
git clone --recurse-submodules https://github.com/PostHog/posthog-duckdb.git
cd posthog-duckdb

# Set up vcpkg
cd /tmp
git clone https://github.com/Microsoft/vcpkg.git
./vcpkg/bootstrap-vcpkg.sh -disableMetrics

# Build the extension
cd -
export VCPKG_TOOLCHAIN_PATH=/tmp/vcpkg/scripts/buildsystems/vcpkg.cmake
GEN=ninja make

# The extension will be built to: build/release/extension/posthog/posthog.duckdb_extension
```

## Usage

### Loading the Extension

```sql
LOAD 'build/release/extension/posthog/posthog.duckdb_extension';
-- Note: you might need to use the absolute path here
```

### Configuration

The extension supports two methods of configuration:

**Method 1: Environment Variables (Recommended)**

```bash
export POSTHOG_HOST="https://us.posthog.com"
export POSTHOG_PROJECT_ID="YOUR_PROJECT_ID"
export POSTHOG_API_KEY="YOUR_PERSONAL_API_KEY"
```

Then in DuckDB:

```sql
SELECT * FROM posthog_query('SELECT event, COUNT() FROM events GROUP BY event LIMIT 10');
```

**Method 2: Explicit Parameters**

```sql
SELECT * FROM posthog_query(
    'https://us.posthog.com',          -- PostHog instance URL
    'YOUR_PROJECT_ID',                  -- Your PostHog project ID
    'YOUR_PERSONAL_API_KEY',            -- Your personal API key
    'SELECT event, COUNT() FROM events GROUP BY event LIMIT 10'  -- HogQL query
);
```

### Finding Your Credentials

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

## Examples

> **Note:** The following examples assume you've set the environment variables (`POSTHOG_HOST`, `POSTHOG_PROJECT_ID`, `POSTHOG_API_KEY`). You can also use the explicit 4-parameter syntax if you prefer.

### Get Most Common Events

```sql
SELECT * FROM posthog_query(
    'SELECT event, COUNT() as count FROM events GROUP BY event ORDER BY count DESC LIMIT 10'
);
```

### Query Events with Timestamp Filtering

```sql
-- Types are automatically mapped: timestamp becomes TIMESTAMP in DuckDB
SELECT
    event,
    timestamp,
    distinct_id
FROM posthog_query(
    'SELECT event, timestamp, distinct_id FROM events WHERE timestamp > now() - interval 7 day'
)
ORDER BY timestamp DESC;
```

### Save Results to a Table

```sql
CREATE TABLE my_posthog_events AS
SELECT * FROM posthog_query(
    'SELECT * FROM events LIMIT 10000'
);
```

### Join with Local Data

```sql
CREATE TABLE user_segments (distinct_id VARCHAR, segment VARCHAR);
INSERT INTO user_segments VALUES ('user123', 'premium'), ('user456', 'free');

SELECT
    e.event,
    s.segment,
    COUNT(*) as event_count
FROM posthog_query(
    'SELECT event, distinct_id FROM events'
) e
JOIN user_segments s ON e.distinct_id = s.distinct_id
GROUP BY e.event, s.segment;
```

### Export to Parquet

```sql
COPY (
    SELECT * FROM posthog_query(
        'SELECT * FROM events WHERE timestamp > today() - interval 30 day'
    )
) TO 'last_30_days_events.parquet';
```

## Type Mapping

The extension automatically maps PostHog/ClickHouse types to DuckDB types:

| PostHog/ClickHouse Type | DuckDB Type | Notes |
|------------------------|-------------|-------|
| String                 | VARCHAR     | |
| LowCardinality(String) | VARCHAR     | PostHog's optimized string type |
| UUID                   | VARCHAR     | |
| UInt64                 | UBIGINT     | |
| UInt32                 | UINTEGER    | |
| UInt16                 | USMALLINT   | |
| UInt8                  | UTINYINT    | |
| Int64                  | BIGINT      | |
| Int32                  | INTEGER     | |
| Int16                  | SMALLINT    | |
| Int8                   | TINYINT     | |
| Float64                | DOUBLE      | |
| Float32                | FLOAT       | |
| DateTime               | TIMESTAMP   | Parsed from ISO strings |
| DateTime64(N)          | TIMESTAMP   | N = precision (0-9) |
| Date                   | DATE        | |
| Date32                 | DATE        | |
| Bool, Boolean          | BOOLEAN     | |
| Nullable(T)            | Same as T   | Automatically unwrapped |

**Note:** All `Nullable()` wrapper types are automatically handled - the extension strips the wrapper and maps the inner type, with full NULL value support.

## HogQL Reference

HogQL is PostHog's SQL dialect based on ClickHouse SQL. See [PostHog HogQL documentation](https://posthog.com/docs/hogql) for more details.

## Limitations

- Rate limits: 120 HogQL queries/hour (PostHog limit)
- Max result size: 50,000 rows per query (PostHog limit)
- The extension fetches all results during the bind phase (results are cached in memory)
- For large result sets, consider using pagination in your HogQL query

## Dependencies

- **cpp-httplib**: HTTP client for API requests
- **OpenSSL**: HTTPS support
- **yyjson**: JSON parsing (DuckDB's built-in library)
