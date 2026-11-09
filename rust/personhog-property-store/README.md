# personhog-property-store

Person properties in SlateDB on object storage, one SlateDB database per shard. A person's shard is `person_hash(team_id, person_id) % PROPERTY_STORE_SHARDS`, and shard `s` belongs to changelog partition `s % partitions`, so the writer that owns a partition owns its shards. Values carry the person version; a merge keeps the higher one, so writes converge in any order and a delete is a versioned marker.

The writer (`PropertyWriter`) opens a partition's shards when it is assigned the partition and fences any earlier opener. Readers (`PropertyReader`) open shards read-only and follow the writer's manifest. Express directory buckets hold copies of every SST for low-latency reads; the writer copies as it uploads, and the writer's `express-repair` command fills gaps.

## Configuration

Every service that uses the store reads these. The leader refuses `PROPERTY_STORE_READER_SKIP_WAL=true`.

| Variable | Default | Description |
|----------|---------|-------------|
| `PROPERTY_STORE_URL` | (required) | Object store URL, such as `s3://bucket` or `file:///path` |
| `PROPERTY_STORE_PREFIX` | `tmp/personhog-properties` | Key prefix under the URL; shards live at `<prefix>/shard-NNNNN` |
| `PROPERTY_STORE_SHARDS` | `64` | Shard count. Must be a multiple of every changelog partition count; The writer registers it in etcd; a leader or replica refuses to start when nothing is registered or its own count or location differs |
| `PROPERTY_STORE_S3_ENDPOINT` | (unset) | S3 endpoint override, for a local S3 |
| `PROPERTY_STORE_S3_REGION` | (unset) | S3 region override |
| `PROPERTY_STORE_S3_ACCESS_KEY_ID` | (unset) | S3 credentials override; unset uses the ambient AWS credentials |
| `PROPERTY_STORE_S3_SECRET_ACCESS_KEY` | (unset) | See above |
| `PROPERTY_STORE_L0_SST_BYTES` | `4194304` | Size of the SST a memtable flush writes |
| `PROPERTY_STORE_MAX_UNFLUSHED_BYTES` | `8388608` | Writes block once this much is waiting on a flush |
| `PROPERTY_STORE_MEMTABLE_FLUSH_SECS` | `60` | How often the writer flushes memtables to SSTs; bounds the WAL a reopen or a reader replays, and how far a reader that skips the WAL lags. 0 disables |
| `PROPERTY_STORE_FULL_COMPACTION_SECS` | `86400` | How often each shard is fully rewritten, which removes deleted persons and replaced versions. 0 disables |
| `PROPERTY_STORE_MAX_FULL_COMPACTIONS` | `4` | Full compactions one writer runs at once |
| `PROPERTY_STORE_COMPRESSION` | `zstd` | SST compression: `none`, `lz4` or `zstd` |
| `PROPERTY_STORE_MIN_FILTER_KEYS` | `1` | Smallest SST that gets a bloom filter |
| `PROPERTY_STORE_FILTER_BITS_PER_KEY` | `10` | Bloom filter size |
| `PROPERTY_STORE_BLOCK_CACHE_BYTES` | `0` | In-memory block cache, shared by a process's shards. Off by default; the leader's person cache already holds what it would |
| `PROPERTY_STORE_META_CACHE_BYTES` | `67108864` | In-memory cache of SST indexes and filters |
| `PROPERTY_STORE_READER_POLL_MS` | `5000` | How often a reader checks for new data, and how far it can lag |
| `PROPERTY_STORE_READER_SKIP_WAL` | `false` | Readers skip WAL files and see a write only after the next memtable flush. Replicas only |
| `PROPERTY_STORE_READER_MEMTABLE_BYTES` | `8388608` | Largest in-memory table a reader buffers replayed WAL in |
| `PROPERTY_STORE_READER_IDLE_SECS` | `300` | A shard reader no owned partition needs closes after this long without a read |
| `PROPERTY_STORE_READ_TIMEOUT_MS` | `1000` | Bound on one point read, including a reader open it triggers |
| `PROPERTY_STORE_OPEN_TIMEOUT_MS` | `10000` | Bound on opening a partition's shards at a leader warm, which replays the WAL |
| `PROPERTY_STORE_MAX_FRESH_READS` | `8` | One-off reads of the latest state in flight at once; more are refused |
| `PROPERTY_STORE_EXPRESS_BUCKETS` | (empty) | Comma-separated Express buckets the writer copies SSTs into, one per zone |
| `PROPERTY_STORE_EXPRESS_READ_BUCKET` | (empty) | The Express bucket this pod reads SSTs from, normally its own zone's. A miss, error or timeout falls back to the URL above |
| `PROPERTY_STORE_EXPRESS_COPY_TIMEOUT_MS` | `5000` | Bound on one copy during an upload; a slow copy is dropped and left to the repair command |
| `PROPERTY_STORE_EXPRESS_READ_TIMEOUT_MS` | `100` | Bound on an Express read before falling back |

## Metrics

Writer side:

| Metric | Type | Description |
|--------|------|-------------|
| `personhog_property_store_puts_total{outcome}` | counter | Persons written (`written`) |
| `personhog_property_store_put_failures_total{kind}` | counter | Shard writes that failed, `data` or `unavailable`. Fences are under `ownership_total` |
| `personhog_property_store_durable_write_ms` | histogram | A shard write from merge to durable WAL |
| `personhog_property_store_ownership_total{event}` | counter | Partition shards `assigned`, `revoked`, `fenced` by another writer, or `reopened` after a fence while still assigned |
| `personhog_property_store_shard_open_ms` | histogram | Opening one shard for writing |
| `personhog_property_store_shard_open_failures_total{kind}` | counter | Shard opens that failed, `data` or `unavailable` |
| `personhog_property_store_memtable_flushes_total{outcome}` | counter | Timed memtable flushes: `flushed`, `failed`, `timed_out` |
| `personhog_property_store_full_compactions_total{stage, outcome}` | counter | Full compaction stages (`l0`, `runs`) `submitted`, `completed`, `failed`, or `submit_failed` |
| `personhog_property_store_full_compaction_stage_seconds{stage, outcome}` | histogram | How long a stage ran, to about one maintenance tick |
| `personhog_property_store_full_compaction_age_seconds` | gauge | Time since the stalest owned shard's last full compaction. Alert when it passes `PROPERTY_STORE_FULL_COMPACTION_SECS` by a margin |
| `personhog_property_store_express_copies_total{op, bucket, outcome}` | counter | SST copies into Express buckets: `put`, `multipart` and `delete` ops, `copied`, `deleted` or `failed`. Failed copies are read misses until the repair command runs |

Reader side:

| Metric | Type | Description |
|--------|------|-------------|
| `personhog_property_store_readers_opened_total` | counter | Shard readers opened |
| `personhog_property_store_reader_open_failures_total{kind}` | counter | Shard reader opens that failed: `data`, `unavailable`, or `timeout` at a leader warm |
| `personhog_property_store_reader_open_ms` | histogram | Opening one shard reader, including WAL replay |
| `personhog_property_store_open_readers` | gauge | Shard readers open on this pod |
| `personhog_property_store_readers_closed_total{reason}` | counter | Readers closed: `idle`, `stale` (behind a one-off read), or `missing_data` (a table garbage collection removed) |
| `personhog_property_store_read_timeouts_total` | counter | Reads that hit `PROPERTY_STORE_READ_TIMEOUT_MS` |
| `personhog_property_store_fresh_reads_total{outcome}` | counter | One-off reads of the latest state: `found`, `missing`, `error`, or `refused` above `PROPERTY_STORE_MAX_FRESH_READS` |
| `personhog_property_store_fresh_read_ms` | histogram | One-off read latency, including its open |
| `personhog_property_store_express_reads_total{outcome}` | counter | SST reads from the Express bucket: `hit`, or fell back because `missing`, `error` or `timeout` |
| `personhog_property_store_express_read_ms` | histogram | Express read latency on hits |

SlateDB's own metrics are published as `slatedb_*` without a shard label; gauges are summed across a process's open shards, except epochs, timestamps, heartbeats and `slatedb_db_l0_sst_count`, which take the maximum. `slatedb_db_l0_sst_count` rising is compaction falling behind. `slatedb_object_store_request_duration_seconds` is object store request latency.
