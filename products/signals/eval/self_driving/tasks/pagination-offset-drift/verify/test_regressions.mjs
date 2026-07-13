// Catches: regressions in pagination metadata (total, page echo, hasMore), empty-collection handling, and query param parsing/clamping.
import test from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const { paginate } = require("../src/pagination.js");
const { parseListParams, MAX_PAGE_SIZE } = require("../src/validation.js");

function makeItems(n) {
  return Array.from({ length: n }, (_, i) => ({ id: `item_${i + 1}` }));
}

test("pagination metadata echoes page, pageSize, and total", () => {
  const result = paginate(makeItems(25), 1, 10);
  assert.equal(result.page, 1);
  assert.equal(result.pageSize, 10);
  assert.equal(result.total, 25);
});

test("hasMore is true when items remain beyond the current page", () => {
  assert.equal(paginate(makeItems(25), 1, 10).hasMore, true);
});

test("an empty collection yields an empty page with hasMore=false", () => {
  const result = paginate([], 1, 10);
  assert.deepEqual(result.items, []);
  assert.equal(result.total, 0);
  assert.equal(result.hasMore, false);
});

test("query params are parsed with defaults and clamped", () => {
  assert.deepEqual(parseListParams({}), { page: 1, pageSize: 20 });
  assert.deepEqual(parseListParams({ page: "0", page_size: "10" }), { page: 1, pageSize: 10 });
  assert.deepEqual(parseListParams({ page: "abc" }), { page: 1, pageSize: 20 });
  assert.equal(parseListParams({ page_size: "500" }).pageSize, MAX_PAGE_SIZE);
});
