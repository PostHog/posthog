import express from 'express'
import { Router } from 'express'
import consumers from 'stream/consumers'
import { S3Client } from '@aws-sdk/client-s3'
import { ListObjectsCommand, GetObjectCommand } from '@aws-sdk/client-s3'
import { Readable } from 'stream'

// Set the AWS Region.
const REGION = 'us-east-1' //e.g. "us-east-1"
// Create an Amazon S3 service client object.
const s3Client = new S3Client({
    region: REGION,
    endpoint: 'http://localhost:19000',
    credentials: {
        accessKeyId: 'object_storage_root_user',
        secretAccessKey: 'object_storage_root_password',
    },
    forcePathStyle: true, // Needed to work with MinIO
})

const routes = Router()

routes.get('/api/team/:teamId/session_recordings/:sessionId', async ({ params: { teamId, sessionId } }, res) => {
    // Fetch events for the specified session recording
    // TODO: habdle time range querying
    const listResponse = await s3Client.send(
        new ListObjectsCommand({
            Bucket: 'posthog',
            Prefix: `team_id/${teamId}/session_id/${sessionId}/chunks/`,
        })
    )

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

    return res.json({ events })
})

const server = express()
server.use(routes)

server.listen(3000)
