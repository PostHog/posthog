// Differential fuzz corpus: runs the Node logs modules on seeded random inputs and writes
// `{ cases: [{ input, output }] }` per section for `tests/differential_fuzz.rs`.
// See the "Regenerating references" section of PORTING.md for the command.
import avro from "avsc";
import { createHash } from "crypto";
import { existsSync, readFileSync, writeFileSync } from "fs";
import { join } from "path";

import {
    decodeLogAttributeValue,
    encodeLogAttributeValue,
} from "../../../nodejs/src/logs/attribute-value";
import {
    InternalLogsVerifier,
    signInternalLogs,
} from "../../../nodejs/src/logs/internal-logs";
import {
    MESSAGE_KEYS,
    buildLogPattern,
} from "../../../nodejs/src/logs/log-pattern-mask";
import { scrubPlainStringWithStats } from "../../../nodejs/src/logs/log-pii-scrub";
import {
    type LogRecord,
    decodeLogRecords,
    encodeLogRecords,
    transformDecodedLogRecordsInPlace,
} from "../../../nodejs/src/logs/log-record-avro";
import { compileMetricRules } from "../../../nodejs/src/logs/metrics-rules/compile-metric-rules";
import { withDefaultMetricRules } from "../../../nodejs/src/logs/metrics-rules/default-metric-rules";
import { buildMetricRulesOtlpPayload } from "../../../nodejs/src/logs/metrics-rules/otlp-payload";
import {
    createBatchTallies,
    tallyRecords,
} from "../../../nodejs/src/logs/metrics-rules/tally";
import { compileRetentionRuleSet } from "../../../nodejs/src/logs/retention/compile-retention-rules";
import { evaluateRetentionDays } from "../../../nodejs/src/logs/retention/evaluate-retention";
import { compileRuleSet } from "../../../nodejs/src/logs/sampling/compile-rules";
import { evaluateLogRecord } from "../../../nodejs/src/logs/sampling/evaluate";
import {
    NUMBER_POOL,
    Rng,
    STRING_POOL,
    deepJson,
    randKey,
    randString,
    randValue,
    sprinkleEscapes,
    validJsonOrNull,
} from "./fuzz-common";

process.env.TZ = "UTC";

const OUT = process.env.FUZZ_OUT ?? join(__dirname, "../tests/fixtures/fuzz");
const NOW_MS = Date.UTC(2025, 0, 15, 12, 37, 13, 250);
const N = Number(process.env.FUZZ_N ?? "1");
// Bytes kept per section; 0 keeps every case. Cases over 1/50 of the budget are left out.
const BUDGET = Number(process.env.FUZZ_BUDGET ?? "120000");
const REGRESSIONS: { numbers: string[]; dates: string[]; avro: string[] } =
    existsSync(join(OUT, "regression-inputs.json"))
        ? JSON.parse(readFileSync(join(OUT, "regression-inputs.json"), "utf8"))
        : { numbers: [], dates: [], avro: [] };

// The PII rules need secret-shaped tokens, which secret scanners reject in a commit. U+E000 after the
// first character breaks each prefix in the file; tests/common/mod.rs removes it before parsing.
const SECRET_PREFIXES = /(sk|rk|pk)(_(?:live|test)_)|(gh)([pousr]_)|(xo)(x[abpr]-)|(AK|AS)(IA)|(AI)(za)|(gl)(pat-)|(-----)(BEGIN)/g

function defuseSecrets(text: string): string {
    return text.replace(SECRET_PREFIXES, (match) => match[0] + '\uE000' + match.slice(1))
}

function write(name: string, cases: unknown[], budget = BUDGET): void {
    let kept = cases;
    if (budget > 0) {
        kept = [];
        let total = 0;
        for (const c of cases) {
            const size = JSON.stringify(c).length;
            if (
                size > budget / 50 &&
                !(c as { regression?: boolean }).regression
            )
                continue;
            if (total + size > budget) break;
            kept.push(c);
            total += size;
        }
    }
    writeFileSync(
        join(OUT, `${name}.json`),
        defuseSecrets(JSON.stringify({ cases: kept })) + "\n",
    );
    console.log(name, kept.length, "of", cases.length);
}

function recordToJson(record: Record<string, unknown>): unknown {
    return Object.fromEntries(
        Object.entries(record).map(([key, value]) => [
            key,
            Buffer.isBuffer(value) ? { $bytes: value.toString("hex") } : value,
        ]),
    );
}

const lossy = (s: string): string => Buffer.from(s).toString();

/** The record as avsc would write it: strings and map keys lossy. `gap` marks merged keys. */
function recordToLossyJson(record: Record<string, unknown>): {
    json: unknown;
    gap: boolean;
} {
    let gap = false;
    const out: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(record)) {
        if (Buffer.isBuffer(v)) {
            out[k] = { $bytes: v.toString("hex") };
        } else if (typeof v === "string") {
            out[k] = lossy(v);
        } else if (v !== null && typeof v === "object") {
            const m: Record<string, string> = {};
            let n = 0;
            for (const [mk, mv] of Object.entries(
                v as Record<string, string>,
            )) {
                m[lossy(mk)] = lossy(mv);
                n++;
            }
            if (Object.keys(m).length !== n) {
                gap = true;
            }
            out[k] = m;
        } else {
            out[k] = v;
        }
    }
    return { json: out, gap };
}

function randomJsonText(rng: Rng): string {
    const r = rng.int(10);
    if (r < 5) {
        let t = JSON.stringify(randValue(rng, 0, { nodes: 40 }));
        if (rng.bool(0.5)) {
            t = sprinkleEscapes(rng, t);
        }
        return t;
    }
    if (r < 7) {
        const sign = rng.pick(["", "-", "+", "--"]);
        const int = rng.pick([
            "0",
            "1",
            "00",
            "01",
            "123456789012345678901234567890",
            "9007199254740993",
            "",
            "5",
        ]);
        const frac = rng.pick([
            "",
            ".",
            ".0",
            ".5",
            ".000001",
            ".12345678901234567890",
        ]);
        const exp = rng.pick([
            "",
            "e",
            "E5",
            "e+5",
            "e-5",
            "e308",
            "e309",
            "e-324",
            "e-323",
            "e-400",
            "E+0",
            "e21",
            "e-7",
        ]);
        return (
            rng.pick(["", " ", "\t", "\n", "\r", "\u000b", " ", "﻿"]) +
            sign +
            int +
            frac +
            exp +
            rng.pick(["", " ", " "])
        );
    }
    if (r < 8) {
        let t = JSON.stringify(randValue(rng, 0, { nodes: 15 }));
        const ops = rng.int(3) + 1;
        for (let i = 0; i < ops; i++) {
            const p = rng.int(t.length + 1);
            const ins = rng.pick([
                ",",
                "]",
                "}",
                '"',
                "\\",
                "\\u12",
                "\\x41",
                "\\u0041",
                "\n",
                "\u0001",
                " ",
                "nul",
                "tru",
                "1",
                ".",
                "-",
                "[",
                "{",
                ":",
            ]);
            t = rng.bool()
                ? t.slice(0, p) + ins + t.slice(p)
                : t.slice(0, p) + t.slice(p + 1);
        }
        return t;
    }
    if (r < 9) {
        return deepJson(rng);
    }
    const k = rng.pick([
        '"a"',
        '"0"',
        '"__proto__"',
        '"1"',
        '"01"',
        '"\\u0030"',
        '"\\ud800"',
    ]);
    return `{${k}:1,"b":2,${k}:${rng.pick(["3", '{"x":1}', "null", '"s"'])}}`;
}

function sectionJson(rng: Rng): void {
    const cases = [];
    for (let i = 0; i < 6000 * N; i++) {
        const text = randomJsonText(rng);
        let output: unknown;
        try {
            output = { ok: true, s: JSON.stringify(JSON.parse(text)) };
        } catch {
            output = { ok: false };
        }
        cases.push({ input: text, output });
    }
    write("json", cases);

    const buf = Buffer.alloc(8);
    const nums: unknown[] = REGRESSIONS.numbers.map((hex) => {
        const x = Buffer.from(hex, "hex").readDoubleBE(0);
        return { input: hex, output: String(x), regression: true };
    });
    const special = [
        0, 5e-324, 2.2250738585072014e-308, 2.225073858507201e-308, 1e21, 1e-7,
        1e-6, 999999999999999900000, 1e20, 0.000001, 123e-20,
        1.7976931348623157e308,
    ];
    for (let i = 0; i < 20000 * N; i++) {
        let x: number;
        const r = rng.int(6);
        if (r === 0) {
            for (let b = 0; b < 8; b++) buf[b] = rng.int(256);
            x = buf.readDoubleBE(0);
        } else if (r === 1) {
            x = rng.pick(special) * (rng.bool() ? 1 : -1);
            buf.writeDoubleBE(x);
            buf.writeBigUInt64BE(
                BigInt.asUintN(
                    64,
                    buf.readBigUInt64BE(0) + BigInt(rng.int(5) - 2),
                ),
            );
            x = buf.readDoubleBE(0);
        } else if (r === 2) {
            x = Number(
                (rng.next() * 10).toFixed(rng.int(17)) +
                    "e" +
                    (rng.int(60) - 30),
            );
        } else if (r === 3) {
            x = rng.int(2 ** 31) * 2 ** (rng.int(80) - 20);
        } else if (r === 4) {
            x = Number("0." + "0".repeat(rng.int(10)) + String(rng.int(1e9)));
        } else {
            x = 10 ** (rng.int(50) - 25) * (1 + rng.int(9));
        }
        buf.writeDoubleBE(x);
        nums.push({ input: buf.toString("hex"), output: String(x) });
    }
    write("numbers", nums);
}

const DATE_PIECES = [
    "2025",
    "2025-01-15",
    "2025-1-5",
    "+002025",
    "-000001",
    "275760-09-13",
    "+275760-09-13T00:00:00Z",
    "+275760-09-13T00:00:00.001Z",
    "1970",
    "T",
    " ",
    "12:00",
    "12:00:00",
    "12:00:00.123",
    "12:00:00.123456",
    "24:00",
    "24:00:00.001",
    "25:00",
    "23:59:60",
    "Z",
    "z",
    "+02:00",
    "-0800",
    "+2",
    "GMT",
    "UTC",
    "UT",
    "EST",
    "PDT",
    "Jan",
    "January",
    "jan",
    "Feb",
    "Wed,",
    "Wednesday",
    "am",
    "pm",
    "AM",
    "PM",
    "15",
    "1",
    "31",
    "32",
    "99",
    "49",
    "50",
    "(comment)",
    "(",
    ")",
    ",",
    ".",
    "/",
    "-",
    ":",
    "1/15/2025",
    "15/1/2025",
    "2025/01/15",
    "0",
    "00",
    "1736942400",
    "garbage",
    "T12",
    "-",
    "Z12",
    "2025-02-29",
    "2024-02-29",
    "2025-13-01",
    "2025-00-10",
    "2025-01-15T",
    "2025-01-15T12",
    "2025-01-15T12:00Z",
    "\t",
    "\n",
    " ",
    "﻿",
];

function sectionDate(rng: Rng): void {
    const cases: unknown[] = REGRESSIONS.dates.map((s) => {
        const v = Date.parse(s);
        return {
            input: s,
            output: Number.isNaN(v) ? null : v,
            regression: true,
        };
    });
    for (let i = 0; i < 20000 * N; i++) {
        let s = "";
        const n = rng.int(6) + 1;
        for (let j = 0; j < n; j++) {
            s += rng.pick(DATE_PIECES);
            if (rng.bool(0.3)) s += rng.pick([" ", "", "T", ",", "-"]);
        }
        if (rng.bool(0.15)) {
            s = new Date(
                rng.int(2 ** 40) * (rng.bool() ? 1 : -1),
            ).toISOString();
            if (rng.bool()) s = s.slice(0, rng.int(s.length + 1));
        }
        if (rng.bool(0.1)) {
            s = new Date(rng.int(2 ** 41)).toString();
            if (rng.bool()) s = s.replace(/ \(.*\)/, "");
        }
        if (rng.bool(0.05)) s = new Date(rng.int(2 ** 41)).toUTCString();
        const v = Date.parse(s);
        cases.push({ input: s, output: Number.isNaN(v) ? null : v });
    }
    write("date", cases);
}

const ATTR_KEYS = [
    "url.path",
    "http.path",
    "http.route",
    "path",
    "http.status_code",
    "http.response.status_code",
    "http.server.duration_ms",
    "duration_ms",
    "level",
    "severity_text",
    "service.name",
    "payload",
    "k",
    "1",
    "0",
    "01",
    "count",
    "ms",
    "user.email",
    "message",
    "constructor",
    "toString",
    "valueOf",
    "hasOwnProperty",
    "__defineGetter__",
    "name",
    "status_code",
    "kind",
    "a",
    "a.b",
    "payload.x",
    "payload.0",
    "k8s.pod.name",
    "🚀",
    "é",
    "",
];

function randAttrValue(rng: Rng): string {
    const r = rng.int(10);
    if (r < 3) return JSON.stringify(rng.pick(STRING_POOL));
    if (r < 5) return JSON.stringify(rng.pick(NUMBER_POOL));
    if (r < 6) return JSON.stringify(rng.pick([true, false, null]));
    if (r < 7) return rng.pick(STRING_POOL);
    if (r < 8) return JSON.stringify(randValue(rng, 3, { nodes: 8 }));
    if (r < 9)
        return JSON.stringify(JSON.stringify(randValue(rng, 3, { nodes: 8 })));
    return randString(rng, 3);
}

function randAttrs(rng: Rng, keys = ATTR_KEYS): Record<string, string> | null {
    if (rng.bool(0.1)) return null;
    const a: Record<string, string> = {};
    const n = rng.int(8);
    for (let i = 0; i < n; i++) {
        a[rng.bool(0.85) ? rng.pick(keys) : randKey(rng)] = randAttrValue(rng);
    }
    delete (a as any)["__proto__"];
    return a;
}

function bytes(rng: Rng, n: number): Buffer {
    return Buffer.from(Array.from({ length: n }, () => rng.int(256)));
}

function randLogRecord(rng: Rng, i: number, body?: string | null): LogRecord {
    return {
        uuid: `u${i}`,
        trace_id: rng.bool(0.85)
            ? bytes(rng, rng.pick([16, 16, 16, 0, 8]))
            : null,
        span_id: rng.bool(0.7) ? bytes(rng, 8) : null,
        trace_flags: null,
        timestamp: rng.bool(0.2)
            ? null
            : (NOW_MS - rng.int(40 * 60 * 1000)) * 1000,
        observed_timestamp: NOW_MS * 1000,
        body:
            body !== undefined
                ? body
                : rng.bool(0.1)
                  ? null
                  : randString(rng, 5),
        severity_text: rng.pick([
            "DEBUG",
            "INFO",
            "WARN",
            "ERROR",
            "info",
            "warning",
            "fatal",
            "trace",
            "Warn",
            "ERRor",
            "",
            null,
            "İnfo",
            "debug ",
        ]),
        severity_number: rng.pick([1, 5, 9, 12, 13, 17, 21, 0, -1, null]),
        service_name: rng.pick(["api", "worker", "web", "", "API", null]),
        resource_attributes: randAttrs(rng, [
            "service.name",
            "k8s.pod.name",
            "constructor",
            "a",
            "1",
            "host",
        ]),
        instrumentation_scope: null,
        event_name: rng.pick([null, "request", ""]),
        attributes: randAttrs(rng),
        bytes_uncompressed: rng.bool(0.8) ? rng.int(2000) : null,
    };
}

function randSpanRecord(rng: Rng, i: number): Record<string, unknown> {
    const ts = (NOW_MS - rng.int(40 * 60 * 1000)) * 1000;
    return {
        uuid: `s${i}`,
        trace_id: rng.bool(0.8) ? bytes(rng, 16) : null,
        span_id: rng.bool(0.7) ? bytes(rng, 8) : null,
        timestamp: rng.bool(0.1) ? null : ts,
        end_time: rng.bool(0.1)
            ? null
            : ts +
              rng.pick([
                  0,
                  1,
                  999,
                  1000,
                  1500,
                  7_250_125,
                  12_000_000_001,
                  -5000,
                  rng.int(1e9),
              ]),
        name: rng.pick([
            "GET /a",
            "db.query",
            "x".repeat(300),
            "",
            null,
            "🚀".repeat(200),
        ]),
        kind: rng.pick([0, 1, 2, 3, 4, 5, 6, 9, -1, null]),
        status_code: rng.pick([0, 1, 2, 3, 7, -1, null]),
        service_name: rng.pick(["api", "worker", null]),
        resource_attributes: randAttrs(rng, [
            "service.name",
            "k8s.pod.name",
            "a",
        ]),
        attributes: randAttrs(rng),
    };
}

function bigBody(rng: Rng): string {
    const r = rng.int(8);
    if (r === 0) {
        // Many keys mixing indices and names: eviction order.
        const o: Record<string, unknown> = {};
        const n = 40 + rng.int(80);
        for (let i = 0; i < n; i++) {
            const k = rng.bool(0.5)
                ? String(rng.int(200))
                : rng.bool(0.5)
                  ? `k${rng.int(100)}`
                  : rng.pick([
                        "4294967294",
                        "4294967295",
                        "01",
                        "-0",
                        "__proto__",
                    ]);
            o[k] = rng.bool(0.8)
                ? rng.int(100)
                : { x: rng.int(3), [String(rng.int(60))]: [1, 2] };
        }
        return JSON.stringify(o);
    }
    if (r === 1) {
        // Arrays near the node budget.
        const n = rng.pick([9997, 9998, 9999, 10000, 10001, 4999, 5000]);
        return JSON.stringify(
            rng.bool()
                ? Array.from({ length: n }, (_, i) => i % 7)
                : { a: Array.from({ length: n }, () => 0) },
        );
    }
    if (r === 2) {
        // Object keys near the node budget.
        const n = rng.pick([9997, 9998, 9999, 10000]);
        return JSON.stringify(
            Object.fromEntries(
                Array.from({ length: n }, (_, i) => [`k${i}`, i]),
            ),
        );
    }
    if (r === 3 && rng.bool(0.3)) {
        // Attribute bytes near 1 MiB.
        const total = 1024 * 1024 - rng.int(200);
        const n = rng.int(3) + 1;
        const o: Record<string, string> = {};
        for (let i = 0; i < n; i++)
            o[`k${i}`] = rng
                .pick(["x", "é", "🚀"])
                .repeat(Math.floor(total / n / 2) - rng.int(30));
        return JSON.stringify(o);
    }
    if (r === 4) {
        // Path bytes: deep keys.
        const k = "k".repeat(rng.pick([4000, 8000, 9000]));
        let v: unknown = 1;
        for (let i = 0; i < rng.pick([100, 120, 127, 128, 129]); i++)
            v = { [k]: v };
        return JSON.stringify(v);
    }
    if (r === 5) {
        return deepJson(rng);
    }
    if (r === 6) {
        // Array of objects: many flattened leaves.
        return JSON.stringify(
            Array.from({ length: rng.pick([3, 30, 60]) }, (_, i) => ({
                id: i,
                v: [i, String(i)],
            })),
        );
    }
    // Index keys around the eviction boundary.
    const o: Record<string, unknown> = {};
    for (let i = 0; i < 48 + rng.int(6); i++) o[`n${i}`] = i;
    for (let i = 0; i < 6; i++)
        o[String(rng.pick([0, 3, 49, 50, 51, 4294967294, 1000]))] = rng.pick([
            null,
            1,
            "x",
            [1],
        ]);
    return JSON.stringify(o);
}

function randBody(rng: Rng): string | null {
    const r = rng.int(20);
    if (r === 0) return null;
    if (r < 3) return randString(rng, 5);
    if (r < 4) return JSON.stringify(randString(rng, 3));
    if (r < 5 && rng.bool(0.25)) return bigBody(rng);
    let t = JSON.stringify(
        randValue(rng, 0, { nodes: rng.pick([10, 60, 200]) }),
    );
    if (rng.bool(0.4)) t = sprinkleEscapes(rng, t);
    if (rng.bool(0.1)) t = " " + t + "\n";
    return t;
}

function randSelected(rng: Rng): string {
    const v = randValue(rng, 0, { nodes: rng.pick([10, 60, 300]) });
    const obj =
        typeof v === "object" && v !== null && !Array.isArray(v)
            ? v
            : { a: v, arr: [1, [2, { b: null }]], s: "x" };
    let t = JSON.stringify(obj);
    if (rng.bool(0.3)) t = sprinkleEscapes(rng, t);
    const r = rng.int(5);
    if (r === 0) return JSON.stringify(t);
    if (r === 1) return t;
    if (r === 2) return JSON.stringify(JSON.stringify(t));
    if (r === 3 && rng.bool(0.25))
        return rng.bool() ? bigBody(rng) : JSON.stringify(bigBody(rng));
    return JSON.stringify(t.slice(0, rng.int(t.length)));
}

async function sectionNormalize(rng: Rng): Promise<void> {
    const cases = [];
    const settingsVariants = [
        { json_parse_logs: true },
        { pii_scrub_logs: true, json_parse_logs: true },
        { json_parse_logs_attribute_key: "payload" },
        { json_parse_logs: true, json_parse_logs_attribute_key: "payload" },
        {
            json_parse_logs: true,
            pii_scrub_logs: true,
            json_parse_logs_attribute_key: "payload",
        },
        { json_parse_logs: true, json_parse_logs_attribute_key: "a" },
        { json_parse_logs: true, json_parse_logs_attribute_key: "1" },
        { json_parse_logs: true, json_parse_logs_attribute_key: "constructor" },
        { pii_scrub_logs: true },
    ];
    for (let i = 0; i < 4000 * N; i++) {
        const settings = rng.pick(settingsVariants);
        const record = randLogRecord(rng, i, randBody(rng));
        if (record.attributes && rng.bool(0.6)) {
            const key =
                (settings as any).json_parse_logs_attribute_key ?? "payload";
            record.attributes[key] = randSelected(rng);
        }
        if (record.attributes && rng.bool(0.3)) {
            // Collide sender attributes with flattened keys.
            for (const k of [
                "a",
                "payload.a",
                "0",
                "k1",
                "n3",
                "message",
                "msg",
            ]) {
                if (rng.bool(0.3)) record.attributes[k] = '"sender"';
            }
        }
        const input = { settings, record: recordToJson(record as any) };
        const copy: LogRecord = {
            ...record,
            attributes: record.attributes ? { ...record.attributes } : null,
        };
        const pii = await transformDecodedLogRecordsInPlace([copy], settings);
        const { json, gap } = recordToLossyJson(copy as any);
        cases.push({
            input,
            output: {
                record: json,
                pii_replacements: pii.piiReplacements,
                gap,
            },
        });
    }
    write("normalize", cases);
}

const LOGLIKE = [
    "user alice.smith+tag@example.co.uk logged in",
    "Bearer\tabc",
    "bearer  x.y-z~+/==",
    "BEARER Kabc",
    "Bearer\u000bab",
    "token=eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.sig",
    "eyJabcdefghijk.abcd.",
    "sk" + "_live_" + "a".repeat(24),
    "sk" + "_test_" + "Z".repeat(19),
    "gh" + "p_" + "A1".repeat(18),
    "gho_short",
    "xo" + "xp-1234567890",
    "xo" + "xb-12345-",
    "AK" + "IA" + "A1B2C3D4E5F6G7H8",
    "ASIA" + "0".repeat(16) + "X",
    "é@example.com",
    "a@b.cd",
    "a@b.c",
    "_a@b.co",
    "x@y.z🚀",
    "4111 1111 1111 1111",
    "192.168.001.001",
    "10.0.0.256",
    "::1",
    "3fa85f64-5717-4562-b3fc-2c963f66afa6",
    "abc3fa85f64-5717-4562-b3fc-2c963f66afa6",
    "_12345_3fa85f64-5717-4562-b3fc-2c963f66afa6",
    "user_A1b2",
    "cus_ABCDEFGHIJKLMN",
    "sub_Abcdefghijklmnopqrstuvwx",
    "aes_128",
    "job_12345",
    "0xDEADbeef",
    "deadbeef12",
    "12345678",
    "api.example.com",
    "libssl.so",
    "deploy.sh",
    "host-1.internal",
    "I0827 11:39:40.307946",
    "E1231 23:59:59",
    "W1301 10:00:00",
    "15/Jan/2025:10:00:00 +0000",
    "Wed Jan 15 10:00:00 UTC 2025",
    "Wed, 15 Jan 2025 10:00:00 GMT",
    "Jan  5 10:00:00",
    "Mon Jan 5 10:00:00 2025",
    "2025-01-15T10:00:00.123Z",
    "2025-01-15 10:00:00,123+0100",
    "/api/users/12345/orders/987",
    "ms=12",
    "é12",
    "١٢٣",
    "１２３",
    "x_1234",
    "İstanbul",
    "ΣΑΣ",
    "straße",
    "ﬁ",
    "\r\n",
    " ",
    "\t",
    '"',
    "\\",
    "{",
    "}",
    "[",
    "]",
    ":",
    ",",
    "🚀",
    "日本",
    "ǅ",
];

function logLike(rng: Rng): string {
    let s = "";
    const n = rng.int(10) + 1;
    for (let i = 0; i < n; i++) {
        s += rng.bool(0.7) ? rng.pick(LOGLIKE) : randString(rng, 2);
        s += rng.pick([
            " ",
            "",
            "=",
            ":",
            "/",
            '"',
            ",",
            ".",
            "\n",
            "_",
            "-",
            "@",
        ]);
    }
    return s;
}

function sectionText(rng: Rng): void {
    const pii = [];
    for (let i = 0; i < 8000 * N; i++) {
        let s = logLike(rng);
        if (rng.bool(0.05)) s = s.repeat(1 + rng.int(200));
        pii.push({ input: s, output: scrubPlainStringWithStats(s) });
    }
    write("pii", pii);

    const pattern = [];
    for (let i = 0; i < 8000 * N; i++) {
        let body: string | null;
        const r = rng.int(10);
        if (r < 4) body = logLike(rng);
        else if (r < 6) {
            const o: Record<string, unknown> = {};
            const nk = rng.pick([0, 1, 3, 31, 32, 33, 40]);
            for (let k = 0; k < nk; k++)
                o[rng.bool() ? logLike(rng).slice(0, 20) : randKey(rng)] =
                    rng.bool(0.5) ? logLike(rng) : rng.int(10);
            if (rng.bool(0.5))
                o[rng.pick(["message", "msg", "event", "text"])] = rng.pick([
                    logLike(rng),
                    5,
                    null,
                    { a: 1 },
                ]);
            body = JSON.stringify(o);
            if (rng.bool(0.3)) body = sprinkleEscapes(rng, body);
        } else if (r < 7) body = JSON.stringify(logLike(rng));
        else if (r < 8) {
            // Around the input cap (8192) and output cap (1024), splitting pairs.
            const unit = rng.pick([
                "🚀",
                "x",
                "é",
                "12 ",
                "a@b.co ",
                '{"message":"',
            ]);
            body = unit.repeat(
                Math.ceil(
                    rng.pick([
                        1023, 1024, 1025, 2048, 4096, 8191, 8192, 8193, 9000,
                    ]) / unit.length,
                ),
            );
            if (rng.bool()) body = "x" + body;
            if (rng.bool(0.3))
                body = '{"message":' + JSON.stringify(body) + "}";
            if (rng.bool(0.2)) body = '{"a":1}' + " ".repeat(8190);
        } else if (r < 9)
            body = rng.pick([
                "",
                null,
                "12",
                "null",
                "true",
                '"x"',
                "[]",
                "{}",
                " {} ",
                "[1,2]",
                "1e400",
            ]);
        else body = randString(rng, 6);
        const keys = rng.pick([
            [...MESSAGE_KEYS],
            [...MESSAGE_KEYS],
            ["text", "nope"],
            [],
            ["__proto__"],
            ["constructor", "msg"],
        ]);
        pattern.push({
            input: { body, keys },
            output: buildLogPattern(body, keys),
        });
    }
    write("pattern", pattern);

    const attr = [];
    for (let i = 0; i < 6000 * N; i++) {
        const s = rng.bool(0.5)
            ? randAttrValue(rng)
            : sprinkleEscapes(rng, JSON.stringify(randString(rng, 3)));
        attr.push({
            input: s,
            output: {
                decoded: decodeLogAttributeValue(s),
                encoded: encodeLogAttributeValue(s),
            },
        });
    }
    write("attribute_value", attr);
}

const LEAF_KEYS = [
    "service_name",
    "service.name",
    "severity_text",
    "level",
    "severity_level",
    "message",
    "url.path",
    "http.method",
    "count",
    "ms",
    "status_code",
    "name",
    "kind",
    "k8s.pod.name",
    "constructor",
    "toString",
    "__proto__",
    "__defineGetter__",
    "1",
    "a",
    "payload",
    "missing",
];
const OPERATORS = [
    "exact",
    "is_not",
    "is_set",
    "is_not_set",
    "icontains",
    "not_icontains",
    "starts_with",
    "not_starts_with",
    "ends_with",
    "not_ends_with",
    "regex",
    "not_regex",
    "gt",
    "gte",
    "lt",
    "lte",
    "in",
    "not_in",
    "bogus",
    undefined,
];
const REGEXES = [
    "^/api",
    "GET|POST",
    "(?i)error",
    "\\d+",
    "^$",
    ".*",
    "[a-z]+",
    "(?=x)",
    "a{2,}",
    "a{,5}",
    "\\bfoo\\b",
    "\\w+@\\w+",
    "[[:alpha:]]",
    "\\p{L}+",
    "\\pL",
    "\\x{1F680}",
    "\\u0041",
    "🚀",
    "é",
    "(?s).",
    "^\\s*$",
    "\\Qa.b\\E",
    "a**",
    "(a{100}){11}",
    "[^\\x00-\\x7F]",
    "ǅ",
    "k",
    "ſ",
    "(?P<n>x)",
    "(?<n>x)",
    "\\0",
    "\\Z",
    "$",
    "^",
    "\\",
    "[",
    "(",
    "TRUE",
    "true",
];
const TYPES = [
    "log_attribute",
    "log",
    "log_resource_attribute",
    "span_attribute",
    "span_resource_attribute",
    "event",
    undefined,
];

function randLeafValue(rng: Rng, op: string | undefined): unknown {
    if (op === "regex" || op === "not_regex")
        return rng.bool(0.9)
            ? rng.pick(REGEXES)
            : rng.pick([null, 5, ["a", "b"], true]);
    const r = rng.int(10);
    if (r < 4)
        return rng.pick(
            STRING_POOL.concat([
                "true",
                "True",
                "false",
                "FALSE",
                "GET",
                "api",
                "ERROR",
                "İ",
                "i̇",
                "ς",
                "σ",
                "ΣΑΣ",
            ]),
        );
    if (r < 6)
        return rng.pick(NUMBER_POOL.concat([NaN, Infinity, 42, 500, 12.5]));
    if (r < 7) return rng.pick([true, false, null]);
    if (r < 9)
        return Array.from({ length: rng.int(4) }, () =>
            rng.pick<unknown>([
                "true",
                true,
                "x",
                1,
                "api",
                1e21,
                null,
                ["n"],
                "GET",
            ]),
        );
    return rng.pick<unknown>([
        { toString: 1 },
        ["x", { toString: 1 }],
        {},
        { a: 1 },
        [[1, 2], 3],
    ]);
}

function randLeaf(rng: Rng): Record<string, unknown> {
    const op = rng.pick(OPERATORS);
    const leaf: Record<string, unknown> = {
        key: rng.bool(0.95) ? rng.pick(LEAF_KEYS) : rng.pick([5, null, true]),
    };
    if (op !== undefined) leaf.operator = op;
    if (rng.bool(0.95)) leaf.value = randLeafValue(rng, op);
    const t = rng.pick(TYPES);
    if (t !== undefined) leaf.type = t;
    return leaf;
}

function randGroup(rng: Rng, depth = 0): unknown {
    if (rng.bool(0.03))
        return rng.pick([
            null,
            { type: "XOR", values: [] },
            { type: "AND", values: "x" },
            { type: "AND", values: [null] },
        ]);
    const n = rng.int(depth > 2 ? 3 : 4);
    const values = Array.from({ length: n }, () =>
        rng.bool(depth > 2 ? 0.95 : 0.7)
            ? randLeaf(rng)
            : randGroup(rng, depth + 1),
    );
    const g = { type: rng.pick(["AND", "OR"]), values };
    return rng.bool(0.5) ? { type: "AND", values: [g] } : g;
}

function samplingRow(rng: Rng, i: number): Record<string, unknown> {
    const ruleType = rng.pick([
        "severity_sampling",
        "path_drop",
        "path_drop",
        "rate_limit",
        "mystery",
    ]);
    const config: Record<string, unknown> = {};
    if (ruleType === "severity_sampling" || rng.bool(0.2)) {
        const actions: Record<string, unknown> = {};
        for (const lvl of ["DEBUG", "INFO", "WARN", "ERROR"]) {
            if (rng.bool(0.6)) {
                actions[lvl] = rng.pick<unknown>([
                    { type: "drop" },
                    { type: "keep" },
                    {
                        type: "sample",
                        rate: rng.pick([0, 0.5, 1, 1.5, -1, 0.25, "0.5"]),
                    },
                    { type: 5 },
                    null,
                ]);
            }
        }
        config.actions = actions;
    }
    if (ruleType === "path_drop" || ruleType === "mystery") {
        config.patterns = rng.bool(0.9)
            ? Array.from({ length: rng.int(3) }, () =>
                  rng.bool(0.9) ? rng.pick(REGEXES) : 5,
              )
            : "notarray";
        if (rng.bool(0.5))
            config.match_attribute_key = rng.pick([
                "url.path",
                " http.method ",
                "",
                "  ",
                "constructor",
                "toString",
                "level",
                5,
            ]);
        if (rng.bool(0.5)) config.filter_group = randGroup(rng);
    }
    if (ruleType === "rate_limit") {
        config.logs_per_second = rng.pick([1, 10, 0, 1.5, 2e6]);
        if (rng.bool(0.5)) config.filter_group = randGroup(rng);
    }
    if (rng.bool(0.3)) {
        config.always_keep = {
            status_gte: rng.pick([500, 400, null, "500"]),
            latency_ms_gt: rng.pick([1000, 0, null, -1]),
            attribute_predicates: Array.from({ length: rng.int(3) }, () => ({
                key: rng.pick(ATTR_KEYS),
                op: rng.pick(["exists", "eq", "ne", "bogus"]),
                value: rng.pick([undefined, '"GET"', "GET", 5, '"x"']),
            })),
        };
    }
    return {
        id: `r${i}`,
        rule_type: ruleType,
        scope_service: rng.pick([null, null, "api", "", "API"]),
        scope_path_pattern: rng.pick([
            null,
            null,
            null,
            "^/api",
            "(?=x)",
            "",
            ".*",
            "\\d",
            '"/api',
        ]),
        scope_attribute_filters: [],
        config,
    };
}

function sectionRules(rng: Rng): void {
    const sampling = [];
    for (let i = 0; i < 4000 * N; i++) {
        const rows = JSON.parse(
            JSON.stringify(
                Array.from({ length: rng.int(4) + 1 }, (_, j) =>
                    samplingRow(rng, j),
                ),
            ),
        );
        let ruleSet;
        try {
            ruleSet = compileRuleSet(rows as never);
        } catch (e) {
            sampling.push({
                input: { rules: rows, records: [] },
                output: { compile_error: true },
            });
            continue;
        }
        const records = Array.from({ length: 5 }, (_, j) =>
            randLogRecord(rng, j),
        );
        for (const r of records)
            if (!r.trace_id || r.trace_id.length === 0)
                r.trace_id = bytes(rng, 16);
        const outs = records.map((record) => {
            try {
                return evaluateLogRecord(ruleSet, record);
            } catch (e) {
                return { threw: String(e) };
            }
        });
        sampling.push({
            input: {
                rules: rows,
                records: records.map((r) => recordToJson(r as any)),
            },
            output: outs,
        });
    }
    write("sampling", sampling);

    const retention = [];
    for (let i = 0; i < 4000 * N; i++) {
        const rows = JSON.parse(
            JSON.stringify(
                Array.from({ length: rng.int(3) + 1 }, (_, j) => ({
                    id: `r${j}`,
                    config: rng.bool(0.97)
                        ? {
                              retention_days: rng.pick<unknown>([
                                  90,
                                  30,
                                  7,
                                  0,
                                  1,
                                  2580,
                                  2581,
                                  14.5,
                                  "30",
                                  -1,
                                  null,
                                  60,
                              ]),
                              filter_group: randGroup(rng),
                          }
                        : rng.pick<unknown>([null, {}, "x"]),
                })),
            ),
        );
        let ruleSet;
        try {
            ruleSet = compileRetentionRuleSet(rows as never);
        } catch (e) {
            retention.push({
                input: { rules: rows, records: [] },
                output: { compile_error: true },
            });
            continue;
        }
        const records = Array.from({ length: 5 }, (_, j) =>
            rng.bool(0.2) ? randSpanRecord(rng, j) : randLogRecord(rng, j),
        );
        const outs = records.map((record) => {
            try {
                return evaluateRetentionDays(ruleSet, record as never);
            } catch (e) {
                return { threw: String(e) };
            }
        });
        retention.push({
            input: { rules: rows, records: records.map(recordToJson) },
            output: outs,
        });
    }
    write("retention", retention);
}

const GROUP_KEYS = [
    "service_name",
    "severity_text",
    "event_name",
    "name",
    "status_code",
    "kind",
    "attributes.ms",
    "attributes.http.method",
    "attributes.level",
    "attributes.payload",
    "attributes.1",
    "attributes.constructor",
    "attributes.__proto__",
    "attributes.toString",
    "resource_attributes.k8s.pod.name",
    "resource_attributes.service.name",
    "attributes.",
    "body",
    "",
    "attributes.🚀",
];
const VALUE_KEYS = [
    "attributes.ms",
    "attributes.count",
    "attributes.duration_ms",
    "duration_ms",
    "attributes.payload",
    "resource_attributes.a",
    "attributes.valueOf",
    "ms",
    null,
    null,
];

const NUMERIC_STRINGS = [
    " 12 ",
    "0x10",
    "1e3",
    "Infinity",
    "-Infinity",
    "",
    "12.5abc",
    ".5",
    "5.",
    "-0",
    "1e400",
    "1e-400",
    " 12",
    "﻿3",
    "\u008512",
    "᠎1",
    "+7",
    "++7",
    "1_0",
    "0b1",
    "1e",
    "1e+",
    "00012",
    "9007199254740993",
    "123456789012345678901234567890",
    "0.1",
    "-.5e-2",
    "NaN",
    "e5",
];

function metricAttrs(rng: Rng): Record<string, string> | null {
    const a = randAttrs(rng);
    if (!a) return a;
    for (const k of ["ms", "count", "duration_ms", "payload"]) {
        if (rng.bool(0.5)) {
            a[k] = rng.pick([
                JSON.stringify(rng.pick(NUMERIC_STRINGS)),
                rng.pick(NUMERIC_STRINGS),
                JSON.stringify(
                    rng.pick(
                        NUMBER_POOL.concat([
                            1e21, -5, 0.1, 12345.678, 7500, 10000, 10001,
                        ]),
                    ),
                ),
                JSON.stringify([1, 2]),
            ]);
        }
    }
    if (rng.bool(0.2))
        a["http.method"] = JSON.stringify(
            rng.pick([
                "🚀".repeat(129),
                "x".repeat(257),
                "é".repeat(256),
                "a".repeat(255) + "🚀",
                "deny",
            ]),
        );
    return a;
}

function sectionMetrics(rng: Rng): void {
    const cases = [];
    for (let i = 0; i < 2500 * N; i++) {
        let rows = Array.from({ length: rng.int(4) + 1 }, (_, j) => {
            const row: Record<string, unknown> = {
                id: process.env.FUZZ_UNIQUE_IDS
                    ? `m${j}`
                    : rng.pick([`m${j}`, "m0", "same"]),
                metric_name: rng.pick([
                    "count_all",
                    "m." + j,
                    "",
                    "posthog.log.records",
                    "x y",
                ]),
                filter_group: rng.bool(0.6) ? null : randGroup(rng),
                value_attribute: rng.pick(VALUE_KEYS),
                group_by: rng.bool(0.95)
                    ? Array.from({ length: rng.int(7) }, () =>
                          rng.bool(0.95) ? rng.pick(GROUP_KEYS) : 5,
                      )
                    : "notarray",
            };
            if (rng.bool(0.4))
                row.source = rng.pick(["spans", "logs", "other"]);
            return row;
        });
        rows = JSON.parse(JSON.stringify(rows));
        const defaults = rng.pick([null, null, "logs", "spans"]);
        const spans = rng.bool(0.3);
        const records = Array.from({ length: rng.int(30) + 1 }, (_, j) => {
            const r = spans
                ? randSpanRecord(rng, j)
                : (randLogRecord(rng, j) as unknown as Record<string, unknown>);
            r.attributes = metricAttrs(rng);
            return r;
        });
        let compiled;
        try {
            compiled = compileMetricRules(rows as never);
        } catch (e) {
            cases.push({
                input: { rules: rows, defaults, now_ms: NOW_MS, records: [] },
                output: { compile_error: String(e) },
            });
            continue;
        }
        if (defaults)
            compiled = withDefaultMetricRules(compiled, defaults as never);
        const tallies = createBatchTallies();
        let threw: string | null = null;
        try {
            tallyRecords(
                compiled,
                records as never[],
                tallies,
                NOW_MS,
                (_r, labelKey) => !labelKey.includes("deny"),
            );
        } catch (e) {
            threw = String(e);
        }
        const payload = buildMetricRulesOtlpPayload(compiled, tallies, NOW_MS);
        cases.push({
            input: {
                rules: rows,
                defaults,
                now_ms: NOW_MS,
                records: records.map(recordToJson),
            },
            output: {
                payload_json: payload === null ? null : JSON.stringify(payload),
                value_skipped: tallies.valueSkipped,
                eval_errors: tallies.evalErrors,
                series_overflow: Object.fromEntries(tallies.seriesOverflow),
                threw,
            },
        });
    }
    write("metrics", cases);
}

function sectionInternal(rng: Rng): void {
    const cases = [];
    const policies = {
        hog_flow: { billed: false, teamRules: false },
        billed_src: { billed: true, teamRules: true },
    };
    for (let i = 0; i < 6000 * N; i++) {
        const keys = rng.pick([
            "k1,k0",
            " k1 , k0 ",
            "",
            ",",
            "k1",
            " ",
            "k0,,k1",
        ]);
        const teams = rng.pick([
            "1,2",
            "*",
            " * ",
            "",
            " ",
            "0x1",
            "1.9",
            " 2,abc",
            "1e3",
            "-1",
            "01",
            "+1",
            "1,",
            " 1",
            "﻿1",
            "2 3",
        ]);
        const teamId = rng.pick([1, 2, 3, 1000, -1, 0]);
        const signedAtMs =
            NOW_MS +
            rng.pick([
                -301_000, -300_000, -299_999, -2000, 0, 299_000, 300_999,
                301_000, -1, 999,
            ]);
        const source = rng.pick([
            "hog_flow",
            "billed_src",
            "constructor",
            "HOG",
            "a.b",
            "",
            "x".repeat(64),
            "x".repeat(65),
            "__proto__",
        ]);
        let signature: string | undefined;
        const r = rng.int(10);
        if (r < 6) {
            try {
                signature = signInternalLogs(
                    rng.pick(["k1", "k0", "k2"]),
                    source,
                    teamId,
                    new Date(signedAtMs),
                );
            } catch {
                signature = `v1.${source}.${Math.floor(signedAtMs / 1000)}.00`;
            }
            if (rng.bool(0.2)) signature += rng.pick([".", "x", ".extra", ""]);
        } else if (r < 8) {
            signature = rng.pick([
                undefined,
                "",
                "garbage",
                "v1..",
                "v1.hog_flow.1736944631",
                "v1.hog_flow.0736944631.ab",
                ".hog_flow.1736944631.ab",
            ]);
        } else {
            signature = `v1.hog_flow.${rng.pick(["1736944631", " 1736944631", "1736944631\n", "17369446310", "1.73694463e9", "１736944631"])}.00`;
        }
        const createdAt = rng.pick<string | undefined>([
            new Date(NOW_MS).toISOString(),
            undefined,
            new Date(NOW_MS + rng.int(700_000) - 350_000).toUTCString(),
            String(NOW_MS),
            "2025-01-15T12:37:13.250+00:00",
            "2025-01-15 12:37:13",
            "Jan 15 2025 12:37:13 GMT+0000",
            "2025-01-15T12:37:13.250",
            "garbage",
            "",
        ]);
        const verifier = new InternalLogsVerifier(keys, teams, policies);
        const out = verifier.verify(signature, teamId, createdAt);
        cases.push({
            input: {
                keys,
                teams,
                signature: signature ?? null,
                team_id: teamId,
                created_at: createdAt ?? null,
            },
            output: out ?? null,
        });
    }
    write("internal", cases);
}

function canonical(value: unknown): unknown {
    if (Buffer.isBuffer(value)) return { $bytes: value.toString("hex") };
    if (Array.isArray(value)) return value.map(canonical);
    if (value !== null && typeof value === "object") {
        const out: Record<string, unknown> = {};
        for (const key of Object.keys(value).sort())
            out[key] = canonical((value as any)[key]);
        return out;
    }
    return value;
}

const SCHEMA_DIR = join(
    __dirname,
    "../../../nodejs/src/logs/parity/fixtures/schemas",
);

function avroMap(rng: Rng): Record<string, string> | null {
    if (rng.bool(0.15)) return null;
    const m: Record<string, string> = {};
    for (let i = 0; i < rng.int(10); i++) {
        const k = rng.pick([
            "",
            "0",
            "1",
            "01",
            "4294967295",
            "4294967294",
            "a",
            "b",
            "__proto__",
            "é",
            "🚀",
            "k".repeat(300),
            String(rng.int(100)),
        ]);
        if (k === "__proto__") continue;
        m[k] = rng.bool(0.1)
            ? "v".repeat(rng.pick([0, 1, 127, 128, 70_000]))
            : randAttrValue(rng);
    }
    return m;
}

function avroLogRecord(rng: Rng, i: number): Record<string, unknown> {
    const opt = <T>(v: T): T | null => (rng.bool(0.2) ? null : v);
    return {
        uuid: opt(`u${i}`),
        trace_id: opt(bytes(rng, rng.pick([0, 16]))),
        span_id: opt(bytes(rng, 8)),
        trace_flags: opt(rng.pick([0, 1, -1, 2147483647, -2147483648])),
        timestamp: opt(
            rng.pick([
                0,
                -1,
                2 ** 53 - 2,
                -(2 ** 53 - 2),
                1736944633250000,
                63,
            ]),
        ),
        observed_timestamp: opt(1736944633250000),
        body: opt(
            rng.bool(0.05)
                ? "b".repeat(rng.pick([65536, 70000]))
                : randString(rng, 5),
        ),
        severity_text: opt(rng.pick(["INFO", ""])),
        severity_number: opt(rng.int(25)),
        service_name: opt("api"),
        resource_attributes: avroMap(rng),
        instrumentation_scope: opt(""),
        event_name: opt("e"),
        attributes: avroMap(rng),
        bytes_uncompressed: opt(rng.pick([0, 123, 2 ** 40])),
        retention_days: opt(rng.pick([30, 0])),
        pattern: opt("<N>"),
        pattern_version: opt(6),
    };
}

function avroSpanRecord(rng: Rng, i: number): Record<string, unknown> {
    const opt = <T>(v: T): T | null => (rng.bool(0.2) ? null : v);
    return {
        uuid: opt(`s${i}`),
        trace_id: opt(bytes(rng, 16)),
        span_id: opt(bytes(rng, 8)),
        parent_span_id: opt(bytes(rng, rng.pick([0, 8]))),
        trace_state: opt(rng.pick(["", "a=b"])),
        name: opt(randString(rng, 2)),
        kind: opt(rng.int(6)),
        flags: opt(1),
        timestamp: opt(1736944633250000),
        end_time: opt(1736944633250001),
        observed_timestamp: opt(1736944633250000),
        service_name: opt("api"),
        resource_attributes: avroMap(rng),
        instrumentation_scope: opt("s"),
        attributes: avroMap(rng),
        dropped_attributes_count: opt(0),
        events: opt(
            Array.from({ length: rng.pick([0, 1, 3, 200]) }, () =>
                randString(rng, 2),
            ),
        ),
        dropped_events_count: opt(rng.int(3)),
        links: opt(
            Array.from({ length: rng.pick([0, 1, 2]) }, () =>
                JSON.stringify({ trace_id: "x" }),
            ),
        ),
        dropped_links_count: opt(0),
        status_code: opt(rng.int(3)),
        status_message: opt(rng.pick(["", "err"])),
        bytes_uncompressed: opt(77),
        retention_days: opt(14),
    };
}

let lastUncaught: string | null = null;
process.on("uncaughtException", (e) => {
    lastUncaught = (e as Error).message;
});

async function decodeOutcome(buf: Buffer): Promise<unknown> {
    try {
        lastUncaught = null;
        const timeout = new Promise<never>((_, reject) =>
            setTimeout(
                () => reject(new Error(`HANG uncaught=${lastUncaught}`)),
                200,
            ),
        );
        const [, codec, records] = await Promise.race([
            decodeLogRecords(buf),
            timeout,
        ]);
        return {
            codec,
            count: records.length,
            sha256: createHash("sha256")
                .update(JSON.stringify(records.map(canonical)))
                .digest("hex"),
        };
    } catch (e) {
        return { error: (e as Error).message };
    }
}

async function sectionAvro(rng: Rng): Promise<void> {
    const schemas = {
        logs: JSON.parse(
            readFileSync(join(SCHEMA_DIR, "logs.avsc.json"), "utf8"),
        ),
        traces: JSON.parse(
            readFileSync(join(SCHEMA_DIR, "traces.avsc.json"), "utf8"),
        ),
    };
    const types = {
        logs: avro.Type.forSchema(schemas.logs),
        traces: avro.Type.forSchema(schemas.traces),
    };
    const cases: unknown[] = [];
    for (const b64 of REGRESSIONS.avro) {
        const output = await decodeOutcome(Buffer.from(b64, "base64"));
        cases.push({
            input: {
                b64,
                label: "regression",
                which: "logs",
                schema_intact: true,
            },
            output,
            regression: true,
        });
    }
    for (let i = 0; i < 1500 * N; i++) {
        const which = rng.bool(0.6) ? "logs" : "traces";
        const n = rng.pick([0, 1, 2, 5, 20, 100]);
        const records = Array.from({ length: n }, (_, j) =>
            which === "logs" ? avroLogRecord(rng, j) : avroSpanRecord(rng, j),
        );
        let buf: Buffer;
        try {
            buf = await encodeLogRecords(
                types[which],
                "zstandard",
                records as never,
            );
        } catch {
            continue;
        }
        const mutation = rng.int(10);
        let label = "clean";
        if (mutation >= 6 && buf.length > 0) {
            const b = Buffer.from(buf);
            const m = rng.int(5);
            if (m === 0) {
                label = "truncate";
                buf = b.subarray(0, rng.int(b.length));
            } else if (m === 1) {
                label = "flip";
                for (let k = 0; k < 1 + rng.int(3); k++)
                    b[rng.int(b.length)] ^= 1 << rng.int(8);
                buf = b;
            } else if (m === 2) {
                label = "append";
                buf = Buffer.concat([b, bytes(rng, rng.int(40))]);
            } else if (m === 3) {
                label = "flip-tail";
                const p = b.length - 1 - rng.int(Math.min(b.length, 60));
                b[p] ^= 1 << rng.int(8);
                buf = b;
            } else {
                label = "header-flip";
                const p = rng.int(Math.min(b.length, 40));
                b[p] ^= 1 << rng.int(8);
                buf = b;
            }
        }
        const outcome = await decodeOutcome(buf);
        // A changed writer schema hits avsc's schema validation, which the port does not reproduce.
        const schemaIntact = buf.includes(
            Buffer.from(
                JSON.stringify(types[which].schema({ exportAttrs: true })),
            ),
        );
        cases.push({
            input: {
                b64: buf.toString("base64"),
                label,
                which,
                schema_intact: schemaIntact,
            },
            output: outcome,
        });
    }
    write("avro", cases, BUDGET * 3);
}

async function main(): Promise<void> {
    const sections = process.argv.slice(2);
    const want = (s: string): boolean =>
        sections.length === 0 || sections.includes(s);
    const seed = Number(process.env.FUZZ_SEED ?? "1");
    if (want("json")) sectionJson(new Rng(seed * 101));
    if (want("date")) sectionDate(new Rng(seed * 103));
    if (want("normalize")) await sectionNormalize(new Rng(seed * 107));
    if (want("text")) sectionText(new Rng(seed * 109));
    if (want("rules")) sectionRules(new Rng(seed * 113));
    if (want("metrics")) sectionMetrics(new Rng(seed * 127));
    if (want("internal")) sectionInternal(new Rng(seed * 131));
    if (want("avro")) await sectionAvro(new Rng(seed * 137));
    process.exit(0);
}

void main();
