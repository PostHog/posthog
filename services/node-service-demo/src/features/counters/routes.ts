import type { NodeService } from '@posthog/node-service'

import { isValidCounterName } from './counter-name.js'
import type { CounterStore } from './counter-store.js'

export function registerCounterRoutes(app: NodeService['app'], store: CounterStore): void {
    app.post('/api/counters/:name/increment', async (context) => {
        const name = context.req.param('name')
        if (!isValidCounterName(name)) {
            return context.json({ error: 'Counter names must start with a lowercase letter.' }, 400)
        }

        return context.json(await store.increment(name))
    })

    app.get('/api/counters/:name', async (context) => {
        const name = context.req.param('name')
        if (!isValidCounterName(name)) {
            return context.json({ error: 'Counter names must start with a lowercase letter.' }, 400)
        }

        const counter = await store.get(name)
        if (!counter) {
            return context.json({ error: 'Counter not found.' }, 404)
        }
        return context.json(counter)
    })
}
