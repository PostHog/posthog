const { dispatchWebhook } = require("./dispatcher");
const { deliverToEndpoint } = require("./transport");
const { signPayload } = require("./signatures");
const analytics = require("./analytics");

const pending = [];
let draining = false;

function enqueue(endpoint, event) {
  const body = JSON.stringify(event);
  pending.push({ endpoint, payload: { body, signature: signPayload(endpoint.secret, body) } });
  drain();
}

async function drain() {
  if (draining) return;
  draining = true;
  while (pending.length > 0) {
    const job = pending.shift();
    try {
      await dispatchWebhook((payload) => deliverToEndpoint(job.endpoint, payload), job.payload, {
        endpointId: job.endpoint.id,
      });
    } catch (err) {
      analytics.capture(job.endpoint.id, "$exception", {
        $exception_type: "Error",
        $exception_message: err.message,
        $exception_source: "src/dispatcher.js",
      });
    }
  }
  draining = false;
}

module.exports = { enqueue, pendingCount: () => pending.length };
