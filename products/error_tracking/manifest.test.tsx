import { manifest } from './manifest'

type RedirectFn = (params: Record<string, string>, searchParams: Record<string, string>, hashParams: object) => string

describe('error tracking routes', () => {
    it('registers alert routes before the generic issue route', () => {
        const routes = Object.keys(manifest.routes)
        const alertsIdRoute = '/error_tracking/alerts/:id'
        const alertsNewRoute = '/error_tracking/alerts/new/:templateId'
        const genericIdRoute = '/error_tracking/:id'

        expect(routes).toEqual(expect.arrayContaining([alertsIdRoute, alertsNewRoute, genericIdRoute]))
        expect(routes.indexOf(alertsIdRoute)).toBeLessThan(routes.indexOf(genericIdRoute))
        expect(routes.indexOf(alertsNewRoute)).toBeLessThan(routes.indexOf(alertsIdRoute))
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
