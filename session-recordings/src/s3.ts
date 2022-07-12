import { S3Client } from '@aws-sdk/client-s3'

// Set the AWS Region.
const REGION = 'us-east-1' //e.g. "us-east-1"
// Create an Amazon S3 service client object.
export const s3Client = new S3Client({
    region: REGION,
    endpoint: 'http://localhost:19000',
    credentials: {
        accessKeyId: 'object_storage_root_user',
        secretAccessKey: 'object_storage_root_password',
    },
    forcePathStyle: true, // Needed to work with MinIO
})
