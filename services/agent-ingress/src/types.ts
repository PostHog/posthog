import { SessionBus, SessionQueueManager } from '@posthog/agent-core'

import { RevisionResolver } from './resolver'

export interface ServerDeps {
    queue: SessionQueueManager
    bus: SessionBus
    resolver: RevisionResolver
    domainSuffix: string
}
