import Piscina from '@posthog/piscina'

import { status } from '../../shared/status'
import { OnRetryCallback, PluginsServer, RetryQueueConsumerControl } from '../../types'
import { pauseQueueIfWorkerFull } from '../queue'
import { startRedlock } from './redlock'

export const LOCKED_RESOURCE = 'plugin-server:locks:retry-queue-consumer'

export async function startRetryQueueConsumer(
    server: PluginsServer,
    piscina: Piscina
): Promise<RetryQueueConsumerControl> {
    status.info('🔄', 'Starting retry queue consumer, trying to get lock...')

    const onRetry: OnRetryCallback = async (retries) => {
        pauseQueueIfWorkerFull(server.retryQueueManager.pauseConsumer, server, piscina)
        for (const retry of retries) {
            await piscina.runTask({ task: 'retry', args: { retry } })
        }
    }

    const unlock = await startRedlock({
        server,
        resource: LOCKED_RESOURCE,
        onLock: async () => {
            status.info('🔄', 'Retry queue consumer lock aquired')
            await server.retryQueueManager.startConsumer(onRetry)
        },
        onUnlock: async () => {
            status.info('🔄', 'Stopping retry queue consumer')
            await server.retryQueueManager.stopConsumer()
        },
        ttl: server.SCHEDULE_LOCK_TTL,
    })

    return { stop: () => unlock(), resume: () => server.retryQueueManager.resumeConsumer() }
}
