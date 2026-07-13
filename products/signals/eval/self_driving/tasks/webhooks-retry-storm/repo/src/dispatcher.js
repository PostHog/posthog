const analytics = require("./analytics");

function defaultSleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/**
 * Deliver one webhook payload to a subscriber endpoint, retrying failures.
 * `deliver` performs a single delivery attempt and resolves to `{ status }`.
 */
async function dispatchWebhook(deliver, payload, options = {}) {
  const { maxRetries = 5, baseDelayMs = 500, sleep = defaultSleep, endpointId = "unknown" } = options;
  let attempt = 0;
  let status = 0;
  while (attempt <= maxRetries || status === 429) {
    const response = await deliver(payload);
    status = response.status;
    analytics.capture(endpointId, "webhook_delivery_attempt", { endpoint_id: endpointId, status });
    if (status >= 200 && status < 300) {
      analytics.capture(endpointId, "webhook_delivered", { endpoint_id: endpointId, attempts: attempt + 1 });
      return { delivered: true, attempts: attempt + 1 };
    }
    if (status !== 429) {
      attempt += 1;
      await sleep(baseDelayMs);
    }
    // Throttled targets recover quickly.
  }
  throw new Error(`Delivery to endpoint ${endpointId} failed after ${attempt} attempts`);
}

module.exports = { dispatchWebhook };
