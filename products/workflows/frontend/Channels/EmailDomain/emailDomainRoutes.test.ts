import { kea, path } from 'kea'
import { router, urlToAction } from 'kea-router'

import { productRoutes } from '~/products'
import { initKeaTests } from '~/test/init'

describe('email domain routes', () => {
    // The sending domain page sits under /workflows/channels/email, next to the '/workflows/:id/:tab'
    // workflow route. kea-router takes the first match, so the page must never resolve as a workflow.
    let resolvedScene: string | null = null

    const routeLogic = kea([
        path(['products', 'workflows', 'frontend', 'Channels', 'EmailDomain', 'emailDomainRoutesTest']),
        urlToAction(() =>
            Object.fromEntries(
                Object.entries(productRoutes)
                    .filter(([route]) => route.startsWith('/workflows'))
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
        ['/workflows/channels/email/new', 'WorkflowsEmailDomain'],
        ['/workflows/channels/email/42', 'WorkflowsEmailDomain'],
        ['/workflows/channels', 'Workflows'],
        ['/workflows/01a05e5e-38c2-0000-b81a-21fe48581914/workflow', 'Workflow'],
    ])('opens %s in the %s scene', (url, scene) => {
        router.actions.push(url)

        expect(resolvedScene).toBe(scene)
    })
})
