import { manifest } from './manifest'

describe('error tracking routes', () => {
    it('registers alert routes before the generic issue route', () => {
        const routes = Object.keys(manifest.routes)

        expect(routes.indexOf('/error_tracking/alerts/:id')).toBeLessThan(routes.indexOf('/error_tracking/:id'))
        expect(routes.indexOf('/error_tracking/alerts/new/:templateId')).toBeLessThan(
            routes.indexOf('/error_tracking/alerts/:id')
        )
    })
})
