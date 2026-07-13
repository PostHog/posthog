let config = null

export function initAnalytics({ apiKey, host = 'https://us.i.posthog.com' }) {
  if (!apiKey) {
    return
  }
  config = { apiKey, host }
}

export function capture(distinctId, event, properties = {}) {
  if (!config || typeof fetch !== 'function') {
    return
  }
  fetch(`${config.host}/i/v0/e/`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({
      api_key: config.apiKey,
      event,
      distinct_id: distinctId,
      properties,
    }),
    keepalive: true,
  }).catch(() => {})
}
