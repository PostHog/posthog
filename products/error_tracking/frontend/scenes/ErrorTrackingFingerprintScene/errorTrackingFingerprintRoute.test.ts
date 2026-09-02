import { kea, path } from 'kea'
import { router, urlToAction } from 'kea-router'

import { productRoutes } from '~/products'
import { initKeaTests } from '~/test/init'

const fingerprintRoute = Object.entries(productRoutes).find(
    ([, [scene]]) => scene === 'ErrorTrackingFingerprint'
)?.[0] as string

describe('error tracking fingerprint route', () => {
    // A fingerprint is arbitrary exception text, and kea-router matches routes against
    // `decodeURI(pathname)` — which unescapes `%5B` to `[`, `%20` to a space, and every non-ASCII
    // escape to its character. Those fall outside the router's global `segmentValueCharset`, so
    // while this route used a named `:fingerprint` segment an alert link such as
    // /error_tracking/fingerprint/Error%3A%20%5BcashFlowDrilldown%5D matched no route at all and the
    // app rendered its 404 scene instead of resolving the fingerprint. A wildcard skips the charset.
    let matched = false

    const routeLogic = kea([
        path(['products', 'error_tracking', 'scenes', 'errorTrackingFingerprintRouteTest']),
        urlToAction(() => ({
            [fingerprintRoute]: () => {
                matched = true
            },
        })),
    ])

    beforeEach(() => {
        matched = false
        initKeaTests(false)
        routeLogic.mount()
    })

    afterEach(() => routeLogic.unmount())

    it.each([
        ['Error: [cashFlowDrilldown] FDQL row validation failed'],
        ['Błąd podczas ładowania 中文 🙂'],
        ['TypeError: {"a":1} <html> `tpl` (500)'],
        ['fp-1'],
    ])('routes an alert link for the fingerprint %s', (fingerprint) => {
        router.actions.push(`/error_tracking/fingerprint/${encodeURIComponent(fingerprint)}`)

        expect(matched).toBe(true)
    })
})
