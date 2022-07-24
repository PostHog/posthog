import express from 'express'
import { Router } from 'express'
import consumers from 'stream/consumers'
import { ListObjectsCommand, GetObjectCommand } from '@aws-sdk/client-s3'
import { Readable } from 'stream'
import { s3Client } from './s3'
import pino from 'pino'

const routes = Router()

const logger = pino({ name: 'api', level: process.env.LOG_LEVEL || 'info' })

routes.get('/api/team/:teamId/session_recordings/:sessionId', async ({ params: { teamId, sessionId } }, res) => {
    // Fetch events for the specified session recording
    // TODO: habdle time range querying, list pagination

    const prefix = `session_recordings/team_id/${teamId}/session_id/${sessionId}/data/`

    logger.debug({ action: 'fetch_session', teamId, sessionId, prefix })

    const listResponse = await s3Client.send(
        new ListObjectsCommand({
            Bucket: 'posthog',
            Prefix: prefix,
        })
    )

    logger.debug({ chunks: listResponse.Contents?.map((object) => object.Key) })

    const objects = await Promise.all(
        listResponse.Contents?.map((key) =>
            s3Client.send(
                new GetObjectCommand({
                    Bucket: 'posthog',
                    Key: key.Key,
                })
            )
        ) || []
    )

    const blobs = await Promise.all(objects.map((object) => consumers.text(object.Body as Readable)))

    // TODO: we probably don't need to parse JSON here if we're careful and
    // construct the JSON progressively
    const events = blobs.flatMap((blob) => blob.split('\n'))

    logger.debug({ action: 'returning_session', events: '[' + events.join(',') + ']' })

    return res.send(`{"events": [${events.join(',')}]}`)
})

const app = express()
app.use(routes)

const server = app.listen(3000)

// Make sure we log any errors we haven't handled
const errorTypes = ['unhandledRejection', 'uncaughtException']

errorTypes.map((type) => {
    process.on(type, async (e) => {
        logger.debug(`process.on ${type}`)
        logger.error(e)
    })
})

// Make sure we disconnect the consumer before shutdown, especially important
// for the test use case as we'll end up having to wait for and old registered
// consumers to timeout.
const signalTraps = ['SIGTERM', 'SIGINT', 'SIGUSR2']

signalTraps.map((type) => {
    process.once(type, async () => {
        try {
            await server.close()
        } finally {
            process.kill(process.pid, type)
        }
    })
})
