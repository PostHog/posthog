let client = null

export async function initAnalytics() {
  const apiKey = process.env.POSTHOG_API_KEY
  if (!apiKey) {
    return
  }
  const { PostHog } = await import('posthog-node')
  client = new PostHog(apiKey, { host: process.env.POSTHOG_HOST ?? 'https://us.i.posthog.com' })
}

export function capture(distinctId, event, properties = {}) {
  client?.capture({ distinctId, event, properties })
}

export async function shutdownAnalytics() {
  await client?.shutdown()
  client = null
}
