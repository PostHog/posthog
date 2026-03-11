import { env } from 'cloudflare:workers'
import { PostHog } from 'posthog-node'

const POSTHOG_API_KEY = 'sTMFPsFhdP1Ssg'
const POSTHOG_HOST = 'https://us.i.posthog.com'

const DEV_POSTHOG_API_KEY = env.POSTHOG_ANALYTICS_API_KEY ?? POSTHOG_API_KEY
const DEV_POSTHOG_HOST = env.POSTHOG_ANALYTICS_HOST ?? POSTHOG_HOST

let _client: PostHog | undefined

export const getPostHogClient = (devMode?: boolean): PostHog => {
    if (!_client) {
        const apiKey = devMode ? DEV_POSTHOG_API_KEY : POSTHOG_API_KEY
        const host = devMode ? DEV_POSTHOG_HOST : POSTHOG_HOST
        _client = new PostHog(apiKey, {
            host,
            flushAt: 1,
            flushInterval: 0,
        })
    }

    return _client
}
