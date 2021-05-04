import Piscina from '@posthog/piscina'

import { JobQueueConsumerControl, OnJobCallback, PluginsServer } from '../../types'
import { startRedlock } from '../../utils/redlock'
import { status } from '../../utils/status'
import { pauseQueueIfWorkerFull } from '../ingestion-queues/queue'

export const LOCKED_RESOURCE = 'plugin-server:locks:job-queue-consumer'

export async function startJobQueueConsumer(server: PluginsServer, piscina: Piscina): Promise<JobQueueConsumerControl> {
    status.info('🔄', 'Starting job queue consumer, trying to get lock...')

    const onJob: OnJobCallback = async (jobs) => {
        pauseQueueIfWorkerFull(server.jobQueueManager.pauseConsumer, server, piscina)
        for (const job of jobs) {
            await piscina.runTask({ task: 'runJob', args: { job } })
        }
    }

    const unlock = await startRedlock({
        server,
        resource: LOCKED_RESOURCE,
        onLock: async () => {
            status.info('🔄', 'Job queue consumer lock aquired')
            await server.jobQueueManager.startConsumer(onJob)
        },
        onUnlock: async () => {
            status.info('🔄', 'Stopping job queue consumer')
            await server.jobQueueManager.stopConsumer()
        },
        ttl: server.SCHEDULE_LOCK_TTL,
    })

    return { stop: () => unlock(), resume: () => server.jobQueueManager.resumeConsumer() }
}
