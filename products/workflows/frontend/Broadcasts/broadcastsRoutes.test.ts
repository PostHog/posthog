import { kea, path } from 'kea'
import { router, urlToAction } from 'kea-router'

import { productRoutes } from '~/products'
import { initKeaTests } from '~/test/init'

describe('broadcasts routes', () => {
    // The tab paths are literal segments under /broadcasts, and kea-router takes the first route that
    // matches. Listed after '/broadcasts/:id', a tab would open as a broadcast with that id.
    let resolvedScene: string | null = null

    const routeLogic = kea([
        path(['products', 'workflows', 'frontend', 'Broadcasts', 'broadcastsRoutesTest']),
        urlToAction(() =>
            Object.fromEntries(
                Object.entries(productRoutes)
                    .filter(([route]) => route.startsWith('/broadcasts'))
                    .map(([route, [scene]]) => [
                        route,
                        () => {
                            resolvedScene = scene
                        },
                    ])
            )
        ),
    ])

    beforeEach(() => {
        resolvedScene = null
        initKeaTests(false)
        routeLogic.mount()
    })

    afterEach(() => routeLogic.unmount())

    it.each([
        ['/broadcasts', 'Broadcasts'],
        ['/broadcasts/library', 'Broadcasts'],
        ['/broadcasts/channels', 'Broadcasts'],
        ['/broadcasts/opt-outs', 'Broadcasts'],
        ['/broadcasts/suppression', 'Broadcasts'],
        ['/broadcasts/reputation', 'Broadcasts'],
        ['/broadcasts/new', 'Broadcast'],
        ['/broadcasts/01a05e5e-38c2-0000-b81a-21fe48581914', 'Broadcast'],
    ])('opens %s in the %s scene', (url, scene) => {
        router.actions.push(url)

        expect(resolvedScene).toBe(scene)
    })
})
