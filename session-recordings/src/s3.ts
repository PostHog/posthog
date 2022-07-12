import { S3Client } from '@aws-sdk/client-s3'

const ACCESS_KEY_ID = process.env.NODE_ENV === 'dev' ? 'root' : process.env.OBJECT_STORAGE_ACCESS_KEY_ID
const SECRET_ACCESS_KEY = process.env.NODE_ENV === 'dev' ? 'password' : process.env.OBJECT_STORAGE_SECRET_ACCESS_KEY

const credentials = ACCESS_KEY_ID
    ? {
          accessKeyId: ACCESS_KEY_ID,
          secretAccessKey: SECRET_ACCESS_KEY,
      }
    : undefined

// Set the AWS Region.
const REGION = 'us-east-1' //e.g. "us-east-1"
// Create an Amazon S3 service client object.
export const s3Client = new S3Client({
    region: REGION,
    endpoint: 'http://localhost:19000',
    credentials: credentials,
    forcePathStyle: true, // Needed to work with MinIO
})
