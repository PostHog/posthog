import express from 'express'
import pino from 'pino'
import { apiRecordingsRoutes } from './api/recordings'
import { healthCheckRoutes } from './healthcheck'
import { startConsumer } from './ingester'
import { consumer } from './utils/kafka'

import { metricRoutes } from './utils/metrics'

const logger = pino({ name: 'main', level: process.env.LOG_LEVEL || 'info' })

const app = express()
app.use(healthCheckRoutes)
app.use(metricRoutes)
app.use(apiRecordingsRoutes)

const server = app.listen(process.env.PORT || 3000)

startConsumer()

// Make sure we log any errors we haven't handled
const errorTypes = ['unhandledRejection', 'uncaughtException']

errorTypes.map((type) => {
    process.on(type, async (e) => {
        try {
            logger.debug(`process.on ${type}`)
            logger.error(e)
            await Promise.all([consumer.disconnect(), server.close()])
            process.exit(0)
        } catch (_) {
            process.exit(1)
        }
    })
})

// Make sure we disconnect the consumer before shutdown, especially important
// for the test use case as we'll end up having to wait for and old registered
// consumers to timeout.
const signalTraps = ['SIGTERM', 'SIGINT', 'SIGUSR2']

signalTraps.map((type) => {
    process.once(type, async () => {
        try {
            await Promise.all([consumer.disconnect(), server.close()])
        } finally {
            process.kill(process.pid, type)
        }
    })
})
