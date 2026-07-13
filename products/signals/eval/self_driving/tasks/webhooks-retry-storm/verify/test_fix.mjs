// Catches: 429 responses bypassing the retry budget and backoff — a throttling endpoint must not trigger an unbounded tight redelivery loop.
import test from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const { dispatchWebhook } = require("../src/dispatcher.js");

function makeTarget(statuses, { maxCalls = 50 } = {}) {
  const calls = [];
  const deliver = async (payload) => {
    if (calls.length >= maxCalls) {
      throw new Error("runaway_target: dispatcher exceeded the test call budget");
    }
    const status = calls.length < statuses.length ? statuses[calls.length] : statuses[statuses.length - 1];
    calls.push({ at: Date.now(), status });
    return { status };
  };
  return { deliver, calls };
}

function makeSleepRecorder() {
  const sleeps = [];
  return {
    sleeps,
    sleep: async (ms) => {
      sleeps.push(ms);
    },
  };
}

test("sustained 429s give up after the maxRetries bound instead of looping", async () => {
  const target = makeTarget([429]);
  const { sleeps, sleep } = makeSleepRecorder();
  await assert.rejects(
    dispatchWebhook(target.deliver, { body: "{}", signature: "sig" }, { maxRetries: 3, baseDelayMs: 100, sleep })
  );
  assert.ok(
    target.calls.length <= 4,
    `expected at most 4 delivery attempts for maxRetries=3, got ${target.calls.length}`
  );
  assert.ok(sleeps.length >= 1, "expected backoff sleeps between retries");
  assert.ok(
    sleeps.every((ms) => ms > 0),
    "every backoff delay must be positive"
  );
});

test("429 twice then 200 delivers exactly once, with backoff before each retry", async () => {
  const target = makeTarget([429, 429, 200]);
  const { sleeps, sleep } = makeSleepRecorder();
  const result = await dispatchWebhook(
    target.deliver,
    { body: "{}", signature: "sig" },
    { maxRetries: 5, baseDelayMs: 100, sleep }
  );
  assert.equal(result.delivered, true);
  assert.equal(target.calls.length, 3, "the event must be delivered exactly 3 times, no duplicate flood");
  assert.ok(sleeps.length >= 2, "expected a backoff pause before each 429 retry");
  assert.ok(
    sleeps.every((ms) => ms > 0),
    "every backoff delay must be positive"
  );
});

test("maxRetries=0 means exactly one attempt, even under throttling", async () => {
  const target = makeTarget([429]);
  const { sleep } = makeSleepRecorder();
  await assert.rejects(
    dispatchWebhook(target.deliver, { body: "{}", signature: "sig" }, { maxRetries: 0, baseDelayMs: 100, sleep })
  );
  assert.equal(target.calls.length, 1, "maxRetries=0 must mean a single delivery attempt");
});
