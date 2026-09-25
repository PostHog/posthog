import ROUNDHOG_MEDIUM from '@posthog/brand/fonts/RoundHog-Medium.woff2'
import ROUNDHOG_SEMIBOLD from '@posthog/brand/fonts/RoundHog-SemiBold.woff2'
import ROUNDHOG_REGULAR from '@posthog/brand/fonts/RoundHog.woff2'

// Bundled into the Worker and served from this origin, so the authentication path depends on no
// third-party font host. Only the weights the picker uses are here: 400 body, 500 buttons, 700
// headings.
const FONTS: Record<string, ArrayBuffer> = {
    '/static/fonts/RoundHog.woff2': ROUNDHOG_REGULAR,
    '/static/fonts/RoundHog-Medium.woff2': ROUNDHOG_MEDIUM,
    '/static/fonts/RoundHog-SemiBold.woff2': ROUNDHOG_SEMIBOLD,
}

export const FONT_PATHS = Object.keys(FONTS)

export function handleFont(request: Request): Response {
    const font = FONTS[new URL(request.url).pathname.replace(/\/$/, '')]
    if (!font) {
        return new Response('Not found', { status: 404 })
    }
    return new Response(font, {
        headers: {
            'Content-Type': 'font/woff2',
            // A face only changes when @posthog/brand ships a new one, which needs a redeploy.
            // A week of caching keeps the picker cheap without pinning a stale face forever.
            'Cache-Control': 'public, max-age=604800, stale-while-revalidate=604800',
            'X-Content-Type-Options': 'nosniff',
        },
    })
}
