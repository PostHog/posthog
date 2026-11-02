# Porting notes: logs ingestion, Node to Rust

This crate ports the Node logs consumer in `nodejs/src/logs`.
The two must give the same messages out for the same messages in.
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
| `log-pii-scrub.ts`                                                                            | `pii`             | Stub                                        |
| `log-pattern-mask.ts`, `log-pattern-stage.ts`                                                 | `pattern`         | Stub                                        |
| `log-record-avro.ts` (normalize, flatten, enrich), `log-record-size.ts`                       | `normalize`       | Stub                                        |
| `sampling/filter-group-match.ts`                                                              | `filter_group`    | Stub                                        |
| `sampling/property-filter-match.ts`                                                           | `property_filter` | Stub                                        |
| `sampling/compile-rules.ts`, `sampling/evaluate.ts`, `sampling/logs-sampling.service.ts`     | `sampling`        | Stub                                        |
| `retention/*.ts`                                                                              | `retention`       | Stub                                        |
| `metrics-rules/*.ts`                                                                          | `metric_rules`    | Stub                                        |
| `internal-logs.ts`                                                                            | `internal_logs`   | Stub                                        |
| `pipeline/log-processing-pipeline.ts`                                                         | `content_weights` | Stub                                        |
| `services/logs-rate-limiter.service.ts`, `common/services/keyed-rate-limiter.service.ts`     | `rate_limiter`    | Stub                                        |
| `pipeline/*.ts`, `logs-ingestion-consumer.ts`, `traces-ingestion-consumer.ts`                 | `pipeline`        | Stub (needs `rust/ingestion-framework`)     |

## API

### `js`

- `JsValue`: `Null`, `Bool`, `Number(f64)`, `String(JsString)`, `Array(Vec<JsValue>)`, `Object(JsObject)`. It is what `JSON.parse` returns.
- `JsObject`: an object in own-property key order.
  - `insert(JsString, JsValue)` and `insert_str` are `obj[k] = v` for a data property. A repeated key keeps its position.
  - It also has `get`, `contains_key` (`Object.hasOwn`), `remove` (`delete`), `iter`, `keys` and `len`.
  - Equality includes key order.
- `JsString`: a JavaScript string. It is WTF-8, so it can hold a lone surrogate.
  - `as_str()` gives `Some(&str)` when there is no lone surrogate.
  - `to_utf8_lossy()` gives the bytes `Buffer.from` writes: U+FFFD for each lone surrogate.
  - `utf16_len()` is `str.length`.
  - `utf16_slice(start, end)` is `str.slice`. It can split a surrogate pair.
  - `push_code_unit` joins a low surrogate onto a trailing high one, as concatenation does.
  - `utf8_byte_len()` is `Buffer.byteLength`.
- `json_parse(&str) -> Result<JsValue, JsonError>` is `JSON.parse`. The error text is not part of any output.
- `json_stringify(&JsValue) -> String` is `JSON.stringify`. `quote_js_string` quotes one string.
- `number_to_string(f64)` is `String(n)`.
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
- `AvroValue` covers `Null`, `Boolean`, `Int(i64)`, `Long(i64)`, `Float(f64)`, `Double(f64)`, `Bytes`, `String`, `Record(Vec<(Arc<str>, AvroValue)>)`, `Enum`, `Fixed`, `Array` and `Map(AvroMap)`. Unions are unwrapped: the value carries its own branch.
- `AvroMap` is a map with plain-object semantics.
  - `assign` is `obj[k] = v`, and drops `__proto__`.
  - `define` defines an own property, as spread does.
  - It also has `get`, `contains_key`, `remove`, `iter`, `iter_strings` and `len`.

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
   - Known gap: the pattern input cap feeds regexes before encoding. A regex that treats a lone surrogate differently from U+FFFD could then disagree. No current mask rule does.
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
8. **avsc decode.** `decodeLogRecords` registers only `zstandard`, which replaces avsc's built-in codecs. The errors and silent cases:

   | Input | Result |
   | --- | --- |
   | Under 4 bytes, or a header that runs past the end | "No metadata found" (the stream ends with no metadata) |
   | Bad magic | "invalid magic bytes" |
   | Any other codec | "unknown codec: X", so `null` and `deflate` containers go to the DLQ |
   | A bad sync marker in any complete block | "invalid sync marker" (avsc checks all blocks before it decompresses any) |
   | Bad zstd | "zstandard codec decompression error" |
   | A record past its block | "truncated block" |
   | Bad union index | "invalid union index: N" |
   | Bad enum index | "invalid NAME enum index: N" |
   | A long outside ±(2^53 - 2) | "potential precision loss" |
   | An incomplete trailing block, or trailing garbage | Ignored, with no error |
   | A block whose count is below its data | Reads only the counted records |
   | A block with count 0 | Skipped |
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

## Not reproduced

- **Writer schemas that fail to parse.** avsc's error text comes from `JSON.parse` or `Type.forSchema`. Capture always writes a valid schema.
- **A block with a negative record count.** avsc reads records until one fails; this port skips the block.
- **Decode error precedence across blocks.** When an early block has a bad record and a later block fails to decompress, avsc's async order decides which error comes first. This port reports the first block in order.
- **Encode error text.** It follows avsc's `invalid <schema>: <value>` shape, but the value is printed with Rust `Debug`. Only a hog transformation that writes a wrongly typed value can reach it. Port it with the transformations.

## Regenerating references

`tests/fixtures/input-decodes.json` comes from `scripts/node-decode-reference.js`. Run it from the repository root after a corpus re-record:

```bash
NODE_PATH=nodejs/node_modules node rust/logs-ingestion/scripts/node-decode-reference.js
```
