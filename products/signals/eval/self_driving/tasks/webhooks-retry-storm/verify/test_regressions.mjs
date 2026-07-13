// Catches: regressions in pre-existing delivery behavior — immediate success without sleeping, and bounded retry-then-reject for non-429 failures.
import test from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const { dispatchWebhook } = require("../src/dispatcher.js");

function makeTarget(statuses, { maxCalls = 50 } = {}) {
  const calls = [];
  const deliver = async () => {
    if (calls.length >= maxCalls) {
      throw new Error("runaway_target: dispatcher exceeded the test call budget");
    }
    const status = calls.length < statuses.length ? statuses[calls.length] : statuses[statuses.length - 1];
    calls.push(status);
    return { status };
  };
  return { deliver, calls };
}

test("successful first delivery returns immediately without sleeping", async () => {
  const target = makeTarget([200]);
  const sleeps = [];
  const result = await dispatchWebhook(
    target.deliver,
    { body: "{}", signature: "sig" },
    {
      maxRetries: 5,
      baseDelayMs: 100,
      sleep: async (ms) => {
        sleeps.push(ms);
      },
    }
  );
  assert.equal(result.delivered, true);
  assert.equal(target.calls.length, 1);
  assert.equal(sleeps.length, 0);
});

test("persistent 5xx failures retry up to the bound then reject", async () => {
  const target = makeTarget([503]);
  const sleeps = [];
  await assert.rejects(
    dispatchWebhook(
      target.deliver,
      { body: "{}", signature: "sig" },
      {
        maxRetries: 2,
        baseDelayMs: 100,
        sleep: async (ms) => {
          sleeps.push(ms);
        },
      }
    ),
    /failed after/
  );
  assert.equal(target.calls.length, 3, "maxRetries=2 means one initial attempt plus two retries");
  assert.ok(sleeps.length >= 1, "retries must be spaced out by a delay");
});
