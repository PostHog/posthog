# Porting notes: logs ingestion, Node to Rust

This crate ports the Node logs consumer in `nodejs/src/logs`.

## Parity contract

For the same messages in, the two must give semantically equivalent output: the same records and field values, numbers equal as doubles, the same sampling, retention and rate-limit decisions, the same headers, the same billing and usage counts, and the same DLQ routing.
Byte layout, the spelling of a number (`1706.7781372070312` or `...313`), and error message text may differ.

The contract is the shared corpus in `nodejs/src/logs/parity/fixtures`:

- `scenarios/*.json` hold end-to-end inputs and the outputs that Node produced.
- `modules/*.json` hold per-function vectors, recorded from Node with `LOGS_PARITY_RECORD=1`.

Read the fixtures with `logs_ingestion::js::json_parse`, not serde_json.
Node writes lone surrogates as `\udXXX`, and serde_json rejects them.

## Status

| TypeScript                                                                                    | Rust module       | Status                                      |
| --------------------------------------------------------------------------------------------- | ----------------- | ------------------------------------------- |
| JavaScript built-ins (`JSON`, object key order, UTF-16 strings, `Date.parse`, `Number#toString`) | `js`              | Done                                        |
| avsc 5.7.9 container codec as `log-record-avro.ts` registers it                               | `avro`            | Done                                        |
| `LogRecord` shape in `log-record-avro.ts`                                                     | `record`          | Done                                        |
| `attribute-value.ts`                                                                          | `attribute_value` | Done                                        |
| `log-body-parse.ts`                                                                           | `body_parse`      | Done                                        |
| `log-pii-scrub.ts`                                                                            | `pii`             | Done                                        |
| `log-pattern-mask.ts`, `log-pattern-stage.ts`                                                 | `pattern`         | Done (stage wiring waits for `pipeline`)    |
| `log-record-avro.ts` (normalize, flatten, enrich), `log-record-size.ts`                       | `normalize`       | Done                                        |
| `sampling/filter-group-match.ts`                                                              | `filter_group`    | Done                                        |
| `sampling/property-filter-match.ts`, node-re2 `new RE2(p, flags).test`                        | `property_filter` | Done                                        |
| `sampling/compile-rules.ts`, `sampling/evaluate.ts`, `sampling/logs-sampling.service.ts`     | `sampling`        | Done                                        |
| `retention/*.ts` except the rules and tracing-config caches                                    | `retention`       | Done                                        |
| `metrics-rules/*.ts`                                                                          | `metric_rules`    | Done (POST and cache in `service`)          |
| `internal-logs.ts`                                                                            | `internal_logs`   | Done                                        |
| `pipeline/log-processing-pipeline.ts`                                                         | `content_weights` | Done                                        |
| `services/logs-rate-limiter.service.ts`, `common/services/keyed-rate-limiter.service.ts`     | `rate_limiter`    | Done (Redis behind `TokenBucketRedis`)      |
| `pipeline/*.ts`, `logs-ingestion-consumer.ts`, `traces-ingestion-consumer.ts`, `processLogMessageBuffer`, `app-metrics-aggregator.ts` | `pipeline` | Done (hog transformations: trait slot only) |
| `servers/ingestion-logs-server.ts`, `servers/ingestion-traces-server.ts`, `logs/config.ts`, `logs/outputs/*`, `common/kafka/consumer/consumer-v2.ts` (batch loop) | `service`, `bin/logs-ingestion.rs` | Done, with shadow mode |
| `common/utils/team-manager.ts`, `common/utils/lazy-loader.ts`, `quota-limiting.service.ts`, `sampling-rules-cache.ts`, `retention-rules-cache.ts`, `tracing-config-cache.ts`, `metric-rules-cache.ts`, `pattern-message-keys-cache.ts`, `metrics-emitter.ts` (POST), `usage-ingestion/*` | `service` | Done |

## API

### `js`

- `JsValue`: `Null`, `Bool`, `Number(f64)`, `String(JsString)`, `Array(Vec<JsValue>)`, `Object(JsObject)`. It is what `JSON.parse` returns.
- `JsObject`: an object in own-property key order.
  - `insert(JsString, JsValue)` and `insert_str` are `obj[k] = v` for a data property. A repeated key keeps its position.
  - It also has `get`, `contains_key` (`Object.hasOwn`), `remove` (`delete`), `iter`, `keys` and `len`.
  - Equality includes key order.
  - `entries` lists the keys as `JsKey` (an index or a named key) without allocating them.
- `JsString`: a JavaScript string. It is WTF-8, so it can hold a lone surrogate.
  - `as_str()` gives `Some(&str)` when there is no lone surrogate.
  - `to_utf8_lossy()` gives the bytes `Buffer.from` writes: U+FFFD for each lone surrogate.
  - `utf16_len()` is `str.length`.
  - `utf16_slice(start, end)` is `str.slice`. It can split a surrogate pair.
  - `push_code_unit` joins a low surrogate onto a trailing high one, as concatenation does.
  - `utf8_byte_len()` is `Buffer.byteLength`.
- `json_parse(&str) -> Result<JsValue, JsonError>` is `JSON.parse`. The error text is not part of any output.
- `json_stringify(&JsValue) -> String` is `JSON.stringify`. `quote_js_string` quotes one string.
- `json_parse_shape(&str, keep_value)` accepts exactly what `json_parse` accepts, but only reports the top-level kind, the top-level keys, and the string values of the keys that `keep_value` names. Pattern selection uses it, so it builds no tree.
- `number_to_string(f64)` is `String(n)`. `write_number` appends the same text to a buffer.
- `utf16_len(&str)` is `str.length`.
- `utf16_slice_lossy(&str, start, end) -> String` slices and writes a split pair as U+FFFD. Use it only where the slice goes straight to bytes.
- `date_parse(&str) -> Option<f64>` is `Date.parse` in epoch milliseconds. `None` is NaN.
- `is_array_index(&str) -> Option<u32>`.

### `avro`

- `decode_container(&[u8]) -> Result<Container, AvroError>` is `decodeLogRecords`.
  - `Container` has `schema_json` (the exact header text), `schema`, `codec` and `records: Vec<AvroValue>`.
  - The `AvroError` `Display` text is the DLQ `error_message`.
- `encode_container(&Schema, codec, &[AvroValue]) -> Result<Vec<u8>, AvroError>` is `encodeLogRecords`.
  - It supports `zstandard` (level 1) and `null`.
  - The header schema is `Schema::to_avsc_json()`.
  - The sync marker is random, so the bytes never match Node's. Compare decoded records.
- `Schema::parse_json(&str)` and `Schema::to_avsc_json()`.
  - `decode_container` parses the header schema through `Schema::parse_json_cached`, a process-wide cache keyed by the exact schema text.
  - A record schema computes its `to_avsc_json` text once.
- `AvroValue` covers `Null`, `Boolean`, `Int(i64)`, `Long(i64)`, `Float(f64)`, `Double(f64)`, `Bytes`, `String`, `Record(Vec<(Arc<str>, AvroValue)>)`, `Enum`, `Fixed`, `Array` and `Map(AvroMap)`. Unions are unwrapped: the value carries its own branch.
- `AvroMap` is a map with plain-object semantics.
  - `assign` is `obj[k] = v`, and drops `__proto__`.
  - `define` defines an own property, as spread does.
  - It also has `get`, `contains_key`, `remove`, `iter`, `iter_strings`, `values_mut`, `into_entries` and `len`.

### `record`

`LogRecord::from_value(AvroValue)` wraps a decoded record, and `into_value()` gives it back for encoding.

- `get`, `get_mut` and `set(name, value)` read and write a property.
  - A name outside the writer schema goes to `extra`.
  - Later stages can read it, as in JavaScript.
  - `into_value` drops it, as avsc ignores unknown properties.
- `has_field` checks the writer schema.
- Typed getters return `None` for null or missing:
  - log fields: `body`, `severity_text`, `attributes`, `retention_days`, `pattern`, and the others;
  - span fields: `name`, `kind`, `status_code`, `end_time`.

## JavaScript rules the port reproduces

Each rule has evidence in Node, and a test that pins it.

1. **Object key order.** Canonical array-index keys come first in ascending order. These are integers from 0 to 2^32 - 2 with no leading zero. Other keys follow in insertion order.
   - Evidence: an avsc map decode of `b, 1, __proto__, dup, dup, 0, 4294967295, 01` gives `0, 1, b, dup, 4294967295, 01`.
   - `flattenJson` keeps or evicts attributes by this order (`lastRetainedKey = Object.keys(result)[n - 1]`).
   - Tests: `avro::value::tests`, `js::object::tests`.
2. **avsc map decode assigns keys onto `{}`.**
   - A `__proto__` key is not an own property and disappears.
   - A duplicate key keeps its first position and takes the last value.
   - Evidence: the edge `map-proto-and-dups`.
3. **`JSON.parse`.**
   - Numbers are f64: `12345678901234567890` becomes `12345678901234567000`.
   - A duplicate key gives the last value at the first position.
   - `__proto__` is an ordinary own key.
   - The only whitespace is space, tab, LF and CR. A BOM, a trailing comma, single quotes, NaN and a leading `+` are errors.
   - A `🚀` pair joins. A lone `\uD83D` stays a lone surrogate.
   - V8 accepts any nesting depth, and so does the port. An array or object deeper than `MAX_BUILT_DEPTH` (512) is checked without a stack and kept as an empty array, so a deep body cannot overflow the stack. No reader goes that deep: the flatten stops past depth 128 and a filter group past depth 16. A filter group nested past 512 levels with a `null` below that level throws in Node and is rejected without the throw here.
   - Tests: `js::json::tests`, `module_vectors::body_parse_matches_node`.
4. **`JSON.stringify` numbers** follow ECMAScript `Number::toString`.
   - Examples: `1e+21`, `1e-7`, `0.30000000000000004`, `-0` becomes `0`, `5e-324`, `1.23e+22`, and `9007199254740993` becomes `9007199254740992`.
   - NaN and Infinity become `null`.
5. **`JSON.stringify` strings.**
   - It escapes `" \ \b \f \n \r \t`, and any other character below 0x20 as `\u00xx` in lowercase hex.
   - It does not escape U+2028, U+2029 or U+007F.
   - It writes a lone surrogate as `\udxxx`.
6. **Lone surrogates.** `str.slice` counts UTF-16 units and can split an emoji.
   - `Buffer.from`, and avsc's string encode, write each lone surrogate as `EF BF BD`. Evidence: `'a\ud83d'` round-trips through avsc as `61 ef bf bd`.
   - TypeScript call sites that can split a pair:
     - `log-pattern-mask.ts` input cap (`body.slice(0, maxInputChars)`) and output cap (`pattern.slice(0, maxOutputChars)`). Use `utf16_slice_lossy`: the output goes straight to Avro bytes.
     - `metrics-rules/tally.ts` label truncation (`value.slice(0, MAX_LABEL_VALUE_LENGTH)`). Use `JsString::utf16_slice`: the label reaches `JSON.stringify` in the OTLP payload, which keeps `\udxxx`.
     - `.length` comparisons against caps. Use `utf16_len`.
   - The pattern input cap is not a gap: node-re2's `replace` writes every lone surrogate as U+FFFD (rule 15), so the masker sees the lossy text in Node too.
7. **`Date.parse`.** V8 tries the ES5 ISO format first, then falls back to a legacy parser.
   - The port follows V8's `dateparser-inl.h`: tokenizer, keyword table, day, time and zone composers, and `TimeClip`.
   - Evidence from `date_parse.json`:
     - Leading whitespace before an ISO string gives NaN.
     - `2025-02-30` is March 2.
     - `T25:00` is NaN. `T24:00` is the next day.
     - Fractions keep 3 digits.
     - `2025-1-5` and `15 January 2025` parse through the legacy path.
     - A bare number gives NaN, because its year falls outside V8's small-integer range.
     - `garbage 2025` is 2025-01-01, but `garbage2025` is NaN.
   - Local time is read as UTC, as the pods run with `TZ=UTC`.
8. **avsc decode.** `decodeLogRecords` registers only `zstandard`, which replaces avsc's built-in codecs.
   The Node consumer carries a pnpm patch to avsc 5.7.9: `Tap.prototype.readLong` reads at most 10 varint bytes, and an 11th byte invalidates the tap and returns 0.
   Without it, a long varint gives a NaN or infinite `bytes` length, and avsc's shared buffer pool then empties every later `bytes` value in the process.
   `Tap::read_long` follows the patched code. The errors and silent cases:

   | Input | Result |
   | --- | --- |
   | Under 4 bytes, or a header that runs past the end | "No metadata found" (the stream ends with no metadata) |
   | Bad magic | "invalid magic bytes" |
   | Any other codec | "unknown codec: X", so `null` and `deflate` containers go to the DLQ |
   | A bad sync marker in any complete block | "invalid sync marker" (avsc checks all blocks before it decompresses any) |
   | Bad zstd | "zstandard codec decompression error" |
   | A record past its block, a string or bytes length that is negative or past the end, or a varint longer than 10 bytes | "truncated block" |
   | A block count outside ±(2^53 - 2), also in trailing bytes | "potential precision loss" (Node rejects since `decodeLogRecords` writes to the decoder directly; through a pipe the throw was uncaught and the promise never settled) |
   | A first array count over 2^32 - 1 | "Invalid array length" |
   | Bad union index | "invalid union index: N" |
   | Bad enum index | "invalid NAME enum index: N" |
   | A long outside ±(2^53 - 2) | "potential precision loss" |
   | An incomplete trailing block, or trailing garbage | Ignored, with no error |
   | A block whose count is below its data | Reads only the counted records |
   | A block with count 0 | Skipped |
   | A block count | Taken as `count \| 0`; a negative count reads records until one fails |
   | Invalid UTF-8 | U+FFFD per maximal invalid subpart |

   - `int` is read with the `long` reader and no range check.
   - Evidence: `tests/fixtures/input-decodes.json` (`edges`).
9. **avsc schema export** (`getSchema({ exportAttrs: true })`) is the header of every re-encoded message.
   - Keeps: field `doc`, `default`, a non-ascending `order`, and `aliases`.
   - Moves: the record `doc` goes last.
   - Drops: unregistered `logicalType` (`timestamp-micros` becomes plain `long`) and custom attributes.
   - Names are written in full, and a named type is referenced by name after its first definition.
   - Test: `schema_export_matches_avsc_for_the_production_schemas`.
10. **avsc encode.**
    - Properties that are not schema fields are ignored. A missing nullable field encodes as null.
    - Blocks hold up to 64 KiB of serialized records. A larger record gets its own block and doubles the size.
11. **`parseFloat`** (`metrics-rules/tally.ts` value attributes).
    - It skips ECMAScript whitespace first: Rust's `char::is_whitespace` adds U+0085 and lacks U+FEFF.
    - It reads the longest decimal prefix: `12.5abc` is 12.5, `1e` is 1, `.5` and `5.` parse, `0x10` is 0, `Infinity` is accepted (and then fails `Number.isFinite`).
    - Port: `metric_rules::js_parse_float`. Tests: its unit test, checked against Node.
12. **`Buffer.from(s, 'base64')` and `buf.toString('ascii')`** (`idToHex`).
    - `'ascii'` clears the high bit of each byte, so `0xC1` reads as `A`.
    - The decoder skips characters outside the alphabet, accepts `-` and `_`, and stops at the first `=`. Bytes after a padded id are ignored.
    - Evidence and test: `id_to_hex` in `tests/fixtures/metric-rules-reference.json`.
13. **`Map` order.** Tallies, the service partition and the overflow map iterate in insertion order, and that order is the OTLP payload order. Rules that share an `id` share one tally map: the first such rule serializes all its entries. Port: `metric_rules::InsertionMap`. Test: `payload_bytes_match_node`.
14. **RE2, not JavaScript `RegExp`.** `log-pii-scrub.ts` and `log-pattern-mask.ts` compile their rules with `createTrackedRE2` (node-re2 1.22.1, UTF-8 mode, flags `gu`).
    - `\d`, `\w` and `\b` are ASCII: `\bab\b` on `'éab abé'` gives `'éX Xé'`.
    - `\s` is `[\t\n\f\r ]`. It excludes `\v`, so `'Bearer\vab'` is not redacted. The `regex` crate's ASCII `\s` includes `\v`.
    - `(?i:` uses Unicode simple case folding: `(?i:[-A-Za-z0-9._~+/])` also matches U+017F and U+212A, so `'bearer \u212Aabc'` is redacted. Nothing else outside ASCII matches, by a scan of every code point.
    - Alternation is leftmost-first in both engines.
    - Port: `pii::translate_re2` rewrites `\d`, `\w`, `\s` and `\b`, and keeps `(?i:` in Unicode mode. Tests: `pii::tests`, and two differential runs against Node of 3,000 random inputs each for `pii` and for `pattern`.
15. **node-re2 `replace` writes a lone surrogate as U+FFFD**, also when nothing matches: `'x\ud800'.replace(re, f)` is `'x\ufffd'`. `exec` indexes stay in UTF-16 units.
    - So `maskString` output is always valid UTF-8, and JSON key-set keys that differ only by a lone surrogate merge: `{"\ud800":1,"\ud801":2,"b":3}` gives `<JSON:b,\ufffd>`.
    - Port: `pattern` masks the lossy UTF-8 form of its input. Test: `pattern::tests::lone_surrogate_keys_merge_after_the_mask`.
16. **`flattenJsonWithBudget` eviction.** Past 50 attributes, a new array-index key evicts the last key in object order, unless that key is an index no greater than the new one. Named keys past the cap are dropped.
    - The last key is the last named key, or else the greatest index. `normalize` keeps the two groups apart, so eviction is a pop.
    - A JSON `null` leaf becomes the string `"null"`, stored as `"\"null\""`. In `string` array mode an array leaf is `JSON.stringify`d after a node-count check.
    - Tests: `normalize_matches_node`, and a differential run of 8,000 random records against Node with no difference outside the gap below.
17. **Prototype members as metric labels.** `tally.ts` reads `map?.[key]` for `attributes.*` and `resource_attributes.*` group-by and value keys, so it also finds `Object.prototype` members (`filter_group::lookup_attribute`).
    - A member with `length >= 2` (`__defineGetter__`) makes `decodeLogAttributeValue` throw. `tallyRecords` does not catch it, so `tally_records` returns `Err` and keeps what the earlier records added.
    - Any other method is a function label: `null` in the label key, and `stringValue` is omitted, so the attribute value is `{}`.
    - `__proto__` gives `{}` in the label key and `"stringValue":{}`.
    - As a value attribute, each one gives NaN, so the record counts in `value_skipped`.
    - Port: `metric_rules::LabelValue`. Evidence and test: the `payloads` cases in `tests/fixtures/metric-rules-reference.json`.
18. **`compileMetricRules` throws when `parseFilterGroup` throws**, so `compile_metric_rules` returns `Result`.
19. **RE2 in filter leaves and sampling patterns.** Regex leaves use `createTrackedRE2(p, 'is')`; `scope_path_pattern` and `path_drop` patterns use no flags.
    - node-re2 first rewrites the pattern text: `\uXXXX` and `\u{...}` become `\x{...}` (any ASCII letter counts as a hex digit, so `\uZZZZ` fails), `\cJ` becomes `\x0A`, long `\p{...}` names map to short ones, `/` becomes `\/`, and `(?<` becomes `(?P<`. The rewrite also runs inside classes: `[(?<a]` matches `P`.
    - RE2 then accepts its own syntax only. It rejects look-around, `\1`-`\9`, `\Z`, `(?x)`, `(?#`, stacked repetition (`a**`, `a{1,2}{3}`, `a???`), a count above 1000, and nested counts whose quotient chain from 1000 reaches 0 (`(a{100}){11}`).
    - It reads as literal what the `regex` crate does not: a `{` that does not start a valid count (`a{,5}`, `a{01}`, `{"a"`), `[` inside a class (`[a[b]]`), and `&&`, `--`, `~~` in a class. `\Q...\E` quotes. `\0dd` is octal.
    - A surrogate code point (`\x{D800}`, or a lone surrogate in the pattern, which V8 writes in its 3-byte form) compiles and never matches. A lone surrogate in the input is U+FFFD.
    - `\p{C}` has no unassigned code points. `\p{Cs}` matches nothing.
    - Port: `property_filter::re2` parses RE2 grammar and writes an equivalent `regex::bytes` pattern. Evidence and test: `tests/fixtures/re2-reference.json` (354 pattern and flag cases, 18,060 `test` results) in `re2_parity`.
20. **`String()` of a rule value can throw.** A filter value object with an own `toString` key makes `String(value)` throw, because JSON cannot make it callable and `valueOf` returns the object. Array elements convert in order, so `['x', {toString: 1}]` matches `x` before it reaches the throw. `classifySamplingRecord` and `evaluateRetentionDays` callers catch it and keep the record. Port: `property_filter::coerce::js_to_string`, returning `JsTypeError`.
21. **Prototype members as filter keys.** `decodedAttr` and `getAttribute` read `map[key]`, so `constructor` or `toString` read a function (`is_set` matches, and `String()` gives `function toString() { [native code] }`), `__proto__` reads `[object Object]`, and `__defineGetter__` makes the decode throw. A non-string `key` converts with `String()`: a missing key reads `attributes['undefined']`. Evidence: a Node probe of `matchFilterGroup`. Test: `filter_group::tests`.
22. **Filter group compile throws on a null child.** `filterGroupDepth` reads `.values` of each child, so a null child anywhere in a group throws, and `compileRuleSet` and `compileRetentionRuleSet` throw with it. A null `config` on any sampling row also throws (`parseAlwaysKeep`). Port: both compilers return `Result`.
23. **Rule quirks kept.** An unknown `rule_type` compiles as `path_drop` with no patterns, but its `always_keep` still keeps records. `applyRateLimits` looks a rule up in `new Map(rules.map(r => [r.id, r]))`, so the last rule with an id wins. Comparisons with `<` on strings use UTF-16 order.
24. **Lost Lua scripts.** ioredis 4 sends `SCRIPT EXISTS` and `SCRIPT LOAD` only for a script it has not seen in the last 60 seconds (`maxScriptsCachingTime`). After a `SCRIPT FLUSH`, each call of a pipeline replies `NOSCRIPT` and counts as a missing reply until that cache clears. The port gives the same missing replies, but it forgets the script on the first `NOSCRIPT` and loads it again in the next pipeline. Test: `rate_limiter::redis::tests`.
25. **ioredis integer replies.** redis-parser 3 reads an integer reply one decimal digit at a time in floating point, so `-9223372036854775808` (Lua's overflow for `1e21`) reads as `-9223372036854778000`. Port: `rate_limiter::redis::ioredis_integer`. Evidence: `rate-limiter-reference.json`.
26. **Content weights key on object identity.** A stage that puts a new record object in the batch gets weight 0 for it. Port: `content_weights::StagedRecord::fresh`. Test: `content_weights::tests`.

### `metric_rules` wiring

`compile_metric_rules` parses filter groups through `metric_rules::parse_filter_group`, which calls `sampling::parse_filter_group`.
A parsed `FilterGroupNode` implements `metric_rules::FilterGroupMatcher` with `filter_group::match_filter_group`.
`compile_metric_rules_with` takes another `FilterGroupParser`.

### `pipeline`

- `LogsIngestionConsumer::new(identity, config, deps)` with `LogsConsumerIdentity::logs()` or `::traces()`, and `LogsIngestionConsumerConfig::from_logs_config` or `::from_traces_config` (the overrides `TracesIngestionConsumer` applies).
- `process_kafka_batch(messages) -> ProcessedBatch { messages, background_task }` is `processKafkaBatch`: parse and admission run before it returns, processing and finalize run in the background task.
- The pipelines match the Node shapes: parse is `per_element(settled parse)` then a fail-on-parse-error chunk step; admission is five chunk steps; processing is `per_element(process, 50)` then a fail-pass chunk step. Each is built per batch.
- A `logs` output produce that fails with a `KafkaProduceError` is `rethrowKafkaOutageAsDependency` (`logs-produce-errors.ts`). A code in `PER_MESSAGE_KAFKA_ERROR_CODES` quarantines the message. Any other code becomes `DependencyUnavailableError`, so it retries in place and then fails the batch. node-rdkafka delivery reports lose the code, so Node also matches the librdkafka text; rdkafka keeps the code. Scenario: `faults-kafka-delivery`.
- Dependencies are traits in `pipeline::deps`. The caller passes the token-bucket transport, the Redis key root and the clock, so a test can pin all three.
- `pipeline::scenario` builds a consumer from a parity scenario with the in-memory dependencies of `parity-harness.ts`. `tests/parity_corpus.rs` replays all scenarios with it; `PARITY_SCENARIO=<name>` runs one.
- `src/bin/logs-ingestion-bench.rs` runs a workload in the same format and prints the Node benchmark's result JSON.
- `scenario_parts` returns the consumer inputs of a scenario before they become a consumer, so a test can swap the outputs.
- `LogsIngestionConsumerDeps::source_offset_header` stamps `source_offset` on `logs` outputs. Only shadow mode sets it.
- `KeyRoot::Shadow` (`@posthog-logs-rust-shadow`) is the shadow's Redis key root.

### `service`

[README.md](README.md) covers configuration, the modes and the shadow guards.

- `config::ServiceConfig::from_env(&Env)` reads the Node keys with `overrideConfigWithEnv` semantics (`node_env`), and in shadow mode (`LOGS_RUST_SHADOW_MODE`, default true) appends the shadow suffixes to the group and the output topics.
- `KAFKA_CONSUMER_*` parses as `parseEnvToRdkafkaConfig` with `skipKeysInDefaultConfig` (`config::NODE_DEFAULT_CONFIG_CONSUMER_KEYS`). `kafka_source::consumer_client_config` adds Node's `auto.offset.reset=earliest` default and applies `stripClassicProtocolConfig` last.
- `consumer_loop::run_consumer_loop(source, processor, config, shutdown, on_tick)` is the batch loop. `BatchSource` (Kafka: `kafka_source::KafkaBatchSource`) and `BatchProcessor` (implemented by `LogsIngestionConsumer`) are its seams.
- `kafka_outputs::KafkaOutputs` implements `IngestionOutputs` and awaits each delivery report.
- `postgres` holds `PgTeamManager` and the rule caches, `redis_deps` holds `RedisQuotaLimiting` and a reconnecting Redis connection, `usage::GrpcUsageRecordBatch` the usage client, `lazy_loader::LazyLoader` the `LazyLoader` port.
- `build_deps` builds what the Node server builds. `shadow_deps` applies the shadow rules to any deps.
- Postgres errors from a lost connection, a pool timeout or one of Node's `POSTGRES_UNAVAILABLE_ERROR_MESSAGES` become `DependencyUnavailableError`.
- `kafka_outputs::classify_produce_error` keeps the rdkafka code as a `KafkaProduceError`, named `MessageSizeTooLarge` for code 10 and `Error` otherwise, so the `logs` output rule applies to real delivery errors. An error with no code is a plain `Error`.

## Not reproduced

- **Writer schemas that fail to parse.** avsc's error text comes from `JSON.parse` or `Type.forSchema`. Capture always writes a valid schema.
- **Writer-schema validation.** avsc's `Type.forSchema` checks are not ported, so accept and reject decisions differ, not only error text. A corrupted record `name` key makes an anonymous record, which avsc decodes and this port rejects. A name with invalid characters (`LogRec\u007frd`) is rejected by avsc and decoded here. Ambiguous unions, field defaults and enum symbols are not validated either.
- **Counts that run far past the data.** For an array or map count in the millions whose items run past the end, avsc keeps reading empty items and Node can throw "Invalid array length" or run out of memory; this port stops at the end with "truncated block". Values that read no bytes, at any depth, share a cap of 2^20 per container ("too many empty records"); Node holds them all or runs out of memory.
- **An `int` that decodes past i64.** avsc keeps the float; this port stores an `i64`.
- **Decode error precedence across blocks.** When an early block has a bad record and a later block fails to decompress, avsc's async order decides which error comes first. This port reports the first block in order.
- **Encode error text.** It follows avsc's `invalid <schema>: <value>` shape, but the value is printed with Rust `Debug`. Only a hog transformation that writes a wrongly typed value can reach it. Port it with the transformations.
- **Flattened JSON keys that differ only by a lone surrogate.** A body such as `{"\ud800":1,"\ud801":2}` gives two attribute keys in Node, and avsc writes both as U+FFFD, so the map holds a duplicate key. `AvroMap` keys are Rust strings, so this port keeps one entry. The same holds for such a key next to a sender key `\ufffd`.
- **The OpenTelemetry skip counter** (`recordJsonEnrichmentSkipped`). `normalize` emits only the Prometheus `logs_ingestion_json_enrichment_skipped_total`.
- **`logs_ingestion_pattern_stage_error_total`.** The Rust stamping cannot fail, so it has no catch path.

- **`hash01FromTraceId` with no trace id.** Node uses `Math.random()`; the port uses `rand`. No vector can pin it.
- **RE2 program size limits.** RE2 rejects a program over `max_mem` (8 MiB) and the `regex` crate has its own size and nesting limits (nesting set to 1000; RE2 has none), so a very large pattern can compile in one engine only. The parser stops at the same nesting of 1000 groups or nested counted repetitions, so a deep pattern fails before it can overflow the stack. The Unicode table versions of the vendored RE2 and the `regex` crate can also differ.
- **Hog log transformations.** `LogsTransformer` is the stage slot; no implementation runs hog yet, and no scenario covers transformations.
- **A Kafka header with a null value.** `parseKafkaHeaders` would throw on it in Node; this port reads it as an empty string.
- **The OpenTelemetry usage counters** (`recordLogsReceived` and the others in `ingestion-otel-metrics.ts`). The Prometheus counters are ported.
- **`re2_objects_created_total`.** The tracked-RE2 allocation counter and its LRU cache are not ported; they do not change a result.

### Service gaps

- **`first team event ingested`.** `setTeamIngestedEvent` captures a PostHog analytics event to every organization member after the first `ingested_event` write. `PgTeamManager` writes the flag and refreshes the cache, but captures nothing.
- **Hog transformations in primary mode.** No `LogsTransformer` exists, so primary mode refuses to start when `LOGS_TRANSFORMATIONS_ENABLED_TEAMS` is not empty.
- **Offsets after a failed background task.** Node's default consumer (`consumer-v1.ts`, `CONSUMER_USE_V2=false`) stores a batch's offsets in a `finally`, so a failed task's offsets can still commit before the process exits. The port follows `consumer-v2.ts`: a failed task stores nothing from it or any later batch.
- **Drain on revoke.** `consumer-v2.ts` waits for in-flight tasks inside the revoke callback. The port fences their offset stores by the same per-partition epoch, but does not wait, so the new owner can process a revoked partition while an old task still runs. That costs duplicates, not data.
- **Consumer telemetry.** The node-rdkafka statistics, loop-stall health check and batch histograms are not ported. Liveness is the lifecycle heartbeat on every loop turn.
- **A full producer queue.** node-rdkafka fails the produce at once; the port waits up to 10 s for queue space first. Both then retry in place and fail the batch, so the wait runs once per retry attempt.
- **`USAGE_INGESTION_TLS=true`.** The workspace `tonic` has no TLS feature, so the service refuses to start with it.
- **`LazyLoader` instrumentation.** The OpenTelemetry spans and the hit and miss counters are not ported; `lazy_loader_cache_size` is. Loader retries are not ported, because the logs servers build their loaders without `loaderRetry`.
- **Rule-cache spans.** The `logs.sampling.*`, `logs.retention.*`, `traces.retention.*` and `logs.patterns.*` span attributes are not ported.
- **The logs Redis password.** Node never passes `LOGS_REDIS_PASSWORD` to the logs Redis client, and neither does the port.

## Regenerating references

`tests/fixtures/input-decodes.json` comes from `scripts/node-decode-reference.js`. Run it from the repository root after a corpus re-record:

```bash
NODE_PATH=nodejs/node_modules node rust/logs-ingestion/scripts/node-decode-reference.js
```

`tests/fixtures/metric-rules-reference.json` comes from `scripts/node-metric-rules-reference.ts`:

```bash
cd nodejs && npx tsx --tsconfig tsconfig.json ../rust/logs-ingestion/scripts/node-metric-rules-reference.ts
```

`tests/fixtures/re2-reference.json` comes from `scripts/node-re2-reference.js`:

```bash
NODE_PATH=nodejs/node_modules node rust/logs-ingestion/scripts/node-re2-reference.js
```

`tests/fixtures/fuzz/` comes from `scripts/fuzz-generate.ts`, a seeded generator over every module. `tests/differential_fuzz.rs` replays it semantically. Inputs that once differed are in `regression-inputs.json`. `FUZZ_SEED`, `FUZZ_N` and `FUZZ_BUDGET=0` (keep every case) with `FUZZ_OUT` write a larger corpus, and `FUZZ_DIR` replays it.

```bash
cd nodejs && FUZZ_UNIQUE_IDS=1 NODE_PATH=node_modules DATABASE_URL=postgres://x:x@127.0.0.1:1/x npx tsx --tsconfig tsconfig.json ../rust/logs-ingestion/scripts/fuzz-generate.ts
```

`tests/fixtures/rate-limiter-reference.json` comes from `scripts/node-rate-limiter-reference.ts`. It needs Redis at 127.0.0.1:6379 and deletes only its own keys (`@posthog-test/logs-parity-rl*` and the sampling keys of team 987654321). `tests/rate_limiter_redis.rs` replays it against the same Redis and skips when Redis is down.

```bash
cd nodejs && NODE_ENV=test npx tsx --tsconfig tsconfig.json ../rust/logs-ingestion/scripts/node-rate-limiter-reference.ts
```
