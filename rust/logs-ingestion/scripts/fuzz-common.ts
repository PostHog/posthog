// Shared generators for the differential fuzz. Deterministic per seed.
export class Rng {
    constructor(private state: number) {}
    next(): number {
        this.state = (this.state + 0x6d2b79f5) | 0;
        let t = this.state;
        t = Math.imul(t ^ (t >>> 15), t | 1);
        t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
        return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    }
    int(n: number): number {
        return Math.floor(this.next() * n);
    }
    bool(p = 0.5): boolean {
        return this.next() < p;
    }
    pick<T>(items: readonly T[]): T {
        return items[this.int(items.length)];
    }
}

export const KEY_POOL = [
    "",
    "0",
    "1",
    "2",
    "10",
    "01",
    "-1",
    "1.5",
    "1e3",
    "4294967294",
    "4294967295",
    "4294967296",
    "9007199254740993",
    "__proto__",
    "constructor",
    "toString",
    "valueOf",
    "hasOwnProperty",
    "__defineGetter__",
    "length",
    "a",
    "b",
    "a.b",
    "a.",
    ".a",
    "..",
    "message",
    "msg",
    "event",
    "level",
    "user.email",
    "http.method",
    "é",
    "日本",
    "🚀",
    "�",
    "￿",
    "\u{10000}",
    "ｆｕｌｌ",
    "K",
    "k",
    "payload",
    " ",
    "\t",
    "\n",
    '"',
    "\\",
    "uuid_3fa85f64-5717-4562-b3fc-2c963f66afa6",
    "user_123",
    "12345678",
    "deadbeef",
    "192.168.0.1",
    "host.example.com",
];

// JSON text pieces (escapes included) that a body can carry verbatim.
export const RAW_KEY_ESCAPES = [
    "\\ud800",
    "\\udfff",
    "\\ud83d\\ude80",
    "\\u0000",
    "\\u2028",
    '\\"',
    "\\\\",
    "\\/",
    "\\ud83d",
    "x\\ude80",
];

export const STRING_POOL = [
    "",
    " ",
    "x",
    "null",
    "true",
    "12",
    " 12 ",
    "0x10",
    "1e3",
    "1e400",
    "-1e400",
    "Infinity",
    "-Infinity",
    "NaN",
    "-0",
    "0",
    "00",
    ".5",
    "5.",
    "1_000",
    "12.5abc",
    " 12",
    "﻿12",
    "​12",
    "1,5",
    "+5",
    "0b11",
    "0o7",
    "alice@example.com",
    "Bearer abc.def-ghi",
    "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.abc123",
    // Built by concatenation so secret scanners do not flag the source.
    "AK" + "IAIOSFODNN7EXAMPLE",
    "sk" + "_live_0123456789abcdefghijkl",
    "gh" + "p_0123456789abcdefghij0123456789abcdef",
    "xo" + "xb-1234567890-abc",
    "3fa85f64-5717-4562-b3fc-2c963f66afa6",
    "192.168.1.1",
    "2001:db8::1",
    "/api/v1/users/123",
    "GET",
    "POST",
    "é",
    "🚀",
    "日本語",
    " ",
    "\u0085",
    "\u000b",
    "\r\n",
    "ERROR",
    "error",
    "warn",
    "INFO",
    "debug",
    "fatal",
    "2025-01-15T10:00:00Z",
    "Wed, 15 Jan 2025 12:00:00 GMT",
    "x".repeat(300),
    "🚀".repeat(130),
    "é".repeat(200),
    "[1,2]",
    '{"a":1}',
    '"quoted"',
    "\\",
    '"',
    "a\\nb",
];

export const NUMBER_POOL = [
    0,
    -0,
    1,
    -1,
    0.1,
    0.30000000000000004,
    1e21,
    1e-7,
    1e-6,
    123456789012345680000,
    5e-324,
    1.7976931348623157e308,
    2 ** 53,
    2 ** 53 + 2,
    -(2 ** 53),
    4294967295,
    4294967294,
    1.5,
    -1.5,
    12.5,
    999.9999999,
    1e100,
    2.5e-8,
    100,
    7,
];

export function randString(rng: Rng, maxParts = 6): string {
    const n = rng.int(maxParts) + 1;
    let s = "";
    for (let i = 0; i < n; i++) {
        const r = rng.int(10);
        if (r < 6) {
            s += rng.pick(STRING_POOL);
        } else if (r < 8) {
            s += rng.pick(KEY_POOL);
        } else if (r < 9) {
            s += String(rng.pick(NUMBER_POOL));
        } else {
            s += String.fromCodePoint(
                rng.pick([
                    0x20 + rng.int(95),
                    0x80 + rng.int(0x780),
                    0x800 + rng.int(0xd000),
                    0xe000 + rng.int(0x2000),
                    0x10000 + rng.int(0x10000),
                ]),
            );
        }
        if (rng.bool(0.3)) {
            s += " ";
        }
    }
    return s;
}

export function randKey(rng: Rng): string {
    return rng.bool(0.8) ? rng.pick(KEY_POOL) : randString(rng, 2);
}

export function randValue(
    rng: Rng,
    depth: number,
    budget: { nodes: number },
): unknown {
    budget.nodes--;
    const r = rng.int(depth > 6 || budget.nodes <= 0 ? 5 : 8);
    switch (r) {
        case 0:
            return null;
        case 1:
            return rng.bool();
        case 2:
            return rng.bool(0.7)
                ? rng.pick(NUMBER_POOL)
                : (rng.next() - 0.5) * 10 ** (rng.int(40) - 20);
        case 3:
        case 4:
            return randString(rng, 3);
        case 5:
        case 6: {
            const o: Record<string, unknown> = {};
            const n = rng.pick([0, 1, 2, 3, 5, 8, 20, 49, 50, 51, 60]);
            for (let i = 0; i < n && budget.nodes > 0; i++) {
                const k = rng.bool(0.3)
                    ? String(
                          rng.pick([
                              0, 1, 2, 3, 5, 9, 10, 49, 50, 51, 100, 4294967294,
                              4294967295,
                          ]),
                      )
                    : randKey(rng);
                if (k === "__proto__") {
                    Object.defineProperty(o, k, {
                        value: randValue(rng, depth + 1, budget),
                        enumerable: true,
                        writable: true,
                        configurable: true,
                    });
                } else {
                    o[k] = randValue(rng, depth + 1, budget);
                }
            }
            return o;
        }
        default: {
            const n = rng.pick([0, 1, 2, 3, 10, 49, 50, 51, 60, 120]);
            return Array.from({ length: n }, () =>
                budget.nodes > 0 ? randValue(rng, depth + 1, budget) : 1,
            );
        }
    }
}

/** Insert a raw JSON escape into some string literal of a JSON text, or into a key. */
export function sprinkleEscapes(rng: Rng, text: string): string {
    const times = rng.int(3);
    for (let t = 0; t < times; t++) {
        const positions: number[] = [];
        for (let i = 0; i < text.length; i++) {
            if (text[i] === '"' && text[i - 1] !== "\\") {
                positions.push(i);
            }
        }
        if (positions.length === 0) {
            break;
        }
        const p = rng.pick(positions);
        text =
            text.slice(0, p + 1) +
            rng.pick(RAW_KEY_ESCAPES) +
            text.slice(p + 1);
    }
    return text;
}

export function validJsonOrNull(text: string): boolean {
    try {
        JSON.parse(text);
        return true;
    } catch {
        return false;
    }
}

/** Deep JSON text, arrays or objects, close to MAX_JSON_DEPTH. */
export function deepJson(rng: Rng): string {
    const depth = rng.pick([126, 127, 128, 129, 130, 200]);
    let open = "";
    let close = "";
    for (let i = 0; i < depth; i++) {
        if (rng.bool()) {
            open += "[";
            close = "]" + close;
        } else {
            const k = rng.pick(["a", "0", "", "b.c"]);
            open += `{"${k}":`;
            close = "}" + close;
        }
    }
    return open + JSON.stringify(rng.pick(["v", 1, null, true])) + close;
}
