import { Router } from 'express'
import { Consumer, ConsumerConfig } from 'kafkajs'

export const getHealthcheckRoutes = ({
    consumer,
    consumerConfig: { sessionTimeout },
}: {
    consumer: Consumer
    consumerConfig: ConsumerConfig
}) => {
    const { HEARTBEAT } = consumer.events
    let lastHeartbeat: number | undefined
    consumer.on(HEARTBEAT, ({ timestamp }) => (lastHeartbeat = timestamp))

    const routes = Router()

    routes.get('/_livez', async (_, res) => {
        // For liveness we just check that the Node event loop is still running,
        // nothing else. It's possible that the pod is in an unrecoverable
        // state regarding consuming, in which case this liveness check wouldn't
        // help.
        return res.status(200).json({ http: true })
    })

    routes.get('/_readyz', async (_, res) => {
        // Consumer has heartbeat within the session timeout,
        // so it is healthy
        if (lastHeartbeat && Date.now() - lastHeartbeat < sessionTimeout) {
            return res.status(200).json({ consumer: true })
        }

        // Consumer has no heartbeat, but maybe it's because the group is currently rebalancing
        try {
            const { state } = await consumer.describeGroup()

            const ready = ['CompletingRebalance', 'PreparingRebalance'].includes(state)
            return res.status(200).json({ consumer: ready })
        } catch (err) {
            return res.status(503).json({ consumer: false })
        }
    })

    return routes
}
