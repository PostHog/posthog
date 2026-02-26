type CloudRegion = 'us' | 'eu'

const REGION_BASE_URLS: Record<CloudRegion, string> = {
    us: 'https://us.posthog.com',
    eu: 'https://eu.posthog.com',
}

interface Env {
    POSTHOG_REGION: string
    POSTHOG_API_BASE_URL?: string
}

export function getOrigin(env: Env): string {
    if (env.POSTHOG_API_BASE_URL) {
        return env.POSTHOG_API_BASE_URL
    }
    const region: CloudRegion = env.POSTHOG_REGION?.toLowerCase() === 'eu' ? 'eu' : 'us'
    return REGION_BASE_URLS[region]
}

export default {
    async fetch(request: Request, env: Env): Promise<Response> {
        const url = new URL(request.url)
        const domain = url.hostname
        const path = url.pathname.replace(/^\/+|\/+$/g, '')

        if (!path) {
            return new Response('Not found', { status: 404 })
        }

        const origin = new URL(getOrigin(env))
        origin.pathname = `/external_surveys/${path}/`

        url.searchParams.forEach((value, key) => {
            origin.searchParams.set(key, value)
        })
        origin.searchParams.set('domain', domain)

        const headers = new Headers(request.headers)
        headers.set('Host', origin.hostname)

        return fetch(origin.toString(), {
            method: request.method,
            headers,
            body: request.method !== 'GET' && request.method !== 'HEAD' ? request.body : undefined,
        })
    },
}
