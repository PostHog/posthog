// Catches: 1-indexed pages being shifted one full page forward (offset = page * pageSize), which makes the first pageSize items unreachable on any page.
import test from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const { paginate } = require("../src/pagination.js");

function makeItems(n) {
  return Array.from({ length: n }, (_, i) => ({ id: `item_${String(i + 1).padStart(3, "0")}` }));
}

test("page 1 returns the first pageSize items in collection order", () => {
  const items = makeItems(25);
  const page1 = paginate(items, 1, 10);
  assert.deepEqual(
    page1.items.map((item) => item.id),
    items.slice(0, 10).map((item) => item.id)
  );
});

test("pages 1 and 2 of a 25-item collection cover the first 20 items with no overlap or gap", () => {
  const items = makeItems(25);
  const page1 = paginate(items, 1, 10);
  const page2 = paginate(items, 2, 10);
  const combined = [...page1.items, ...page2.items].map((item) => item.id);
  assert.equal(combined.length, 20);
  assert.equal(new Set(combined).size, 20, "pages must not overlap");
  assert.deepEqual(
    combined,
    items.slice(0, 20).map((item) => item.id),
    "pages must preserve collection order with no gaps"
  );
});

test("the final page returns the remainder and reports hasMore=false", () => {
  const items = makeItems(25);
  const page3 = paginate(items, 3, 10);
  assert.deepEqual(
    page3.items.map((item) => item.id),
    items.slice(20).map((item) => item.id)
  );
  assert.equal(page3.hasMore, false);
});
