import { beforeEach, describe, expect, it } from "vitest";
import { clearCapturedLogs, formatCapturedLogs, recordLog } from "./logCapture";

beforeEach(() => {
  clearCapturedLogs();
});

describe("recordLog", () => {
  it("keeps only the newest 500 entries", () => {
    for (let i = 0; i < 505; i++) recordLog("info", null, [`line ${i}`]);
    const lines = formatCapturedLogs().split("\n");
    expect(lines).toHaveLength(500);
    expect(lines[0]).toMatch(/line 5$/);
    expect(lines.at(-1)).toMatch(/line 504$/);
  });

  it("joins arguments, rendering Errors with their stack and objects as JSON", () => {
    recordLog("error", "auth", ["failed", new Error("kaput"), { code: 500 }]);
    const output = formatCapturedLogs();
    expect(output).toContain("[error] [auth] failed");
    expect(output).toContain("Error: kaput");
    expect(output).toContain('{"code":500}');
  });

  it("falls back to name and message when an Error has no stack", () => {
    const err = new Error("bare");
    err.stack = undefined;
    recordLog("error", null, [err]);
    expect(formatCapturedLogs()).toContain("Error: bare");
  });

  it("elides circular references and coerces bigints", () => {
    const obj: Record<string, unknown> = { id: 10n };
    obj.self = obj;
    recordLog("info", null, [obj]);
    const output = formatCapturedLogs();
    expect(output).toContain('"self":"[circular]"');
    expect(output).toContain('"id":"10"');
  });
});

describe("formatCapturedLogs", () => {
  it("returns a placeholder when nothing was captured", () => {
    expect(formatCapturedLogs()).toBe("(no logs captured this session)");
  });

  it("prefixes entries with timestamp and level, omitting a null scope", () => {
    recordLog("warn", null, ["careful"]);
    expect(formatCapturedLogs()).toMatch(
      /^\d{4}-\d{2}-\d{2}T[\d:.]+Z \[warn\] careful$/,
    );
  });

  it("limits output to the most recent maxEntries", () => {
    for (let i = 0; i < 5; i++) recordLog("info", null, [`line ${i}`]);
    const lines = formatCapturedLogs({ maxEntries: 2 }).split("\n");
    expect(lines).toHaveLength(2);
    expect(lines[0]).toMatch(/line 3$/);
    expect(lines[1]).toMatch(/line 4$/);
  });

  it("returns the placeholder, not everything, for maxEntries: 0", () => {
    recordLog("info", null, ["line"]);
    expect(formatCapturedLogs({ maxEntries: 0 })).toBe(
      "(no logs captured this session)",
    );
  });
});

describe("clearCapturedLogs", () => {
  it("empties the buffer", () => {
    recordLog("info", null, ["x"]);
    clearCapturedLogs();
    expect(formatCapturedLogs()).toBe("(no logs captured this session)");
  });
});
