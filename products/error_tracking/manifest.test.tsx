import { manifest } from './manifest'

type RedirectFn = (params: Record<string, string>, searchParams: Record<string, string>, hashParams: object) => string

describe('error tracking routes', () => {
    it('registers alert routes before the generic issue route', () => {
        const routes = Object.keys(manifest.routes)
        const alertsIdRoute = '/error-tracking/alerts/:id'
        const alertsNewRoute = '/error-tracking/alerts/new/:templateId'
        const genericIdRoute = '/error-tracking/:id'

        expect(routes).toEqual(expect.arrayContaining([alertsIdRoute, alertsNewRoute, genericIdRoute]))
        expect(routes.indexOf(alertsIdRoute)).toBeLessThan(routes.indexOf(genericIdRoute))
        expect(routes.indexOf(alertsNewRoute)).toBeLessThan(routes.indexOf(alertsIdRoute))
    })

    it('opens fingerprint management from the legacy fingerprints route', () => {
        const redirect = manifest.redirects!['/error_tracking/:id/fingerprints'] as RedirectFn

        expect(redirect({ id: 'issue-id' }, {}, {})).toBe('/error-tracking/issue-id?manageFingerprints=true')
    })

    // Old underscore and /errors links must land on the canonical page and keep their query and hash.
    it.each([
        ['/errors', {}, '/error-tracking'],
        ['/error_tracking', {}, '/error-tracking'],
        ['/error_tracking/:id', { id: 'issue-id' }, '/error-tracking/issue-id'],
        ['/error_tracking/alerts/:id', { id: 'alert-id' }, '/error-tracking/alerts/alert-id'],
        ['/error_tracking/alerts/new/:templateId', { templateId: 'tpl' }, '/error-tracking/alerts/new/tpl'],
        ['/error_tracking/fingerprint/*', { _: 'Error%3A%20x' }, '/error-tracking/fingerprint/Error%3A%20x'],
    ])('redirects %s to the canonical error-tracking path', (path, params, expectedPath) => {
        const redirect = manifest.redirects![path] as RedirectFn

        expect(redirect(params, { dateRange: '7d' }, { foo: 'bar' })).toBe(`${expectedPath}?dateRange=7d#foo=bar`)
    })

    // Legacy settings links (from docs, bookmarks, and old onboarding) used to dead-end on a blank
    // issue page. Each must now land on its tab in the configuration panel.
    it.each([
        ['/error_tracking/symbol_sets', {}, {}, 'error-tracking-symbol-sets'],
        ['/error_tracking/symbol-sets', {}, {}, 'error-tracking-symbol-sets'],
        ['/error_tracking/configuration/:tab', { tab: 'symbol_sets' }, {}, 'error-tracking-symbol-sets'],
        ['/error_tracking/configuration/:tab', { tab: 'alerting' }, {}, 'error-tracking-alerting'],
        ['/error_tracking/settings/:tab', { tab: 'symbol-sets' }, {}, 'error-tracking-symbol-sets'],
        // Legacy links also carried the tab in the query string, so it must survive the redirect.
        ['/error_tracking/settings', {}, { tab: 'symbol_sets' }, 'error-tracking-symbol-sets'],
    ])('redirects %s to the configuration tab with the right setting', (path, params, searchParams, settingId) => {
        const redirect = manifest.redirects![path] as RedirectFn
        const url = redirect(params as Record<string, string>, searchParams as Record<string, string>, {})

        expect(url).toContain('activeTab=configuration')
        expect(url).toContain(`selectedSetting=${settingId}`)
    })
})
