import express from 'express'
import { Router } from 'express'
import consumers from 'stream/consumers'
import { ListObjectsCommand, GetObjectCommand } from '@aws-sdk/client-s3'
import { Readable } from 'stream'
import { s3Client } from './s3'

const routes = Router()

routes.get('/api/team/:teamId/session_recordings/:sessionId', async ({ params: { teamId, sessionId } }, res) => {
    // Fetch events for the specified session recording
    // TODO: habdle time range querying, list pagination

    console.debug({ action: 'fetch_session', teamId, sessionId })

    const listResponse = await s3Client.send(
        new ListObjectsCommand({
            Bucket: 'posthog',
            Prefix: `team_id/${teamId}/session_id/${sessionId}/chunks/`,
        })
    )

    console.debug({ event: listResponse.Contents })

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
    const events = blobs.flatMap((blob) => blob.split('\n').map((line) => JSON.parse(line)))

    console.debug({ action: 'returning_session', events })

    return res.json({ events })
})

const server = express()
server.use(routes)

server.listen(3000)
