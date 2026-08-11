import { manifest } from './manifest'

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
})
