import type { NodeService } from '@posthog/node-service'

import { greetingFor } from './greeting.js'

export function registerHelloRoutes(app: NodeService['app']): void {
    app.get('/api/hello/:name', (context) => {
        const greeting = greetingFor(context.req.param('name'))
        if (!greeting) {
            return context.json({ error: 'Provide a name between 1 and 64 characters.' }, 400)
        }
        return context.json({ greeting })
    })
}
