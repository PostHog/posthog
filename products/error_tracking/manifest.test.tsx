import { router } from 'kea-router'

import { initKeaTests } from '~/test/init'

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

    it.each(['configuration', 'settings', 'symbol_sets', 'symbol-sets'])(
        'registers the legacy /error_tracking/%s redirect before the /error_tracking/:id catch-all',
        (slug) => {
            const redirects = Object.keys(manifest.redirects!)

            expect(redirects.indexOf(`/error_tracking/${slug}`)).toBeGreaterThanOrEqual(0)
            expect(redirects.indexOf(`/error_tracking/${slug}`)).toBeLessThan(redirects.indexOf('/error_tracking/:id'))
        }
    )

    it('opens fingerprint management from the legacy fingerprints route', () => {
        const redirect = manifest.redirects!['/error_tracking/:id/fingerprints'] as RedirectFn

        expect(redirect({ id: 'issue-id' }, {}, {})).toBe('/error-tracking/issue-id?manageFingerprints=true')
    })

    it.each([
        ['/errors', {}, '/error-tracking'],
        ['/error_tracking', {}, '/error-tracking'],
        ['/error_tracking/:id', { id: 'issue-id' }, '/error-tracking/issue-id'],
        ['/error_tracking/alerts/:id', { id: 'alert-id' }, '/error-tracking/alerts/alert-id'],
        ['/error_tracking/alerts/new/:templateId', { templateId: 'tpl' }, '/error-tracking/alerts/new/tpl'],
    ])('redirects %s to the canonical error-tracking path and keeps query and hash', (path, params, expectedPath) => {
        const redirect = manifest.redirects![path] as RedirectFn

        expect(redirect(params, { dateRange: '7d' }, { foo: 'bar' })).toBe(`${expectedPath}?dateRange=7d#foo=bar`)
    })

    it.each(['Error%3A%20x', '100%25', 'a%252Fb'])(
        'rebuilds the legacy fingerprint link from the raw path for %s',
        (raw) => {
            initKeaTests()
            router.actions.push(`/error_tracking/fingerprint/${raw}`)
            const redirect = manifest.redirects!['/error_tracking/fingerprint/*'] as RedirectFn

            expect(redirect({ _: decodeURI(raw) }, {}, {})).toBe(`/error-tracking/fingerprint/${raw}`)
        }
    )

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

        expect(url).toMatch(/^\/error-tracking\?/)
        expect(url).toContain('activeTab=configuration')
        expect(url).toContain(`selectedSetting=${settingId}`)
    })
})
