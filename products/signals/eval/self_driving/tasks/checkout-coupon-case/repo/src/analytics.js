let client = null;

function getClient() {
  if (!client) {
    const { PostHog } = require("posthog-node");
    client = new PostHog(process.env.POSTHOG_API_KEY, {
      host: process.env.POSTHOG_HOST || "https://us.i.posthog.com",
    });
  }
  return client;
}

// Analytics is disabled (no-op) unless POSTHOG_API_KEY is configured.
function capture(distinctId, event, properties = {}) {
  if (!process.env.POSTHOG_API_KEY) return;
  getClient().capture({ distinctId, event, properties });
}

module.exports = { capture };
