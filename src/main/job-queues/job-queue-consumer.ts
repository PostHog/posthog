import Piscina from '@posthog/piscina'

import { JobQueueConsumerControl, OnRetryCallback, PluginsServer } from '../../types'
import { startRedlock } from '../../utils/redlock'
import { status } from '../../utils/status'
import { pauseQueueIfWorkerFull } from '../ingestion-queues/queue'

export const LOCKED_RESOURCE = 'plugin-server:locks:retry-queue-consumer'

export async function startJobQueueConsumer(server: PluginsServer, piscina: Piscina): Promise<JobQueueConsumerControl> {
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
