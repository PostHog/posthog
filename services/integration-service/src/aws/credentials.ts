// AWS credentials, chosen explicitly rather than by the SDK's default chain. That chain
// would let a service whose job is holding third-party credentials authenticate silently as
// an EC2 instance role, or as whatever a developer last ran `aws sso login` against.
//
// There are exactly two ways in: the IRSA web identity token in cluster, and static
// throwaway credentials against a local mock when AWS_ENDPOINT_URL is set. loadConfig()
// exits under NODE_ENV=production if that variable is present, so the second cannot be
// reached on a deployed pod.

import { fromTokenFile } from '@aws-sdk/credential-provider-web-identity'
import type { AwsCredentialIdentityProvider } from '@smithy/types'

import { getEnv } from '../lib/env.js'
import { logger } from '../lib/logging.js'

export function credentialProvider(): AwsCredentialIdentityProvider {
    const endpoint = getEnv('AWS_ENDPOINT_URL')
    if (endpoint) {
        logger.warn('aws:static_credentials', { endpoint })
        return async () => ({
            accessKeyId: process.env['AWS_ACCESS_KEY_ID'] ?? 'test',
            secretAccessKey: process.env['AWS_SECRET_ACCESS_KEY'] ?? 'test',
        })
    }
    // IRSA: reads AWS_WEB_IDENTITY_TOKEN_FILE + AWS_ROLE_ARN, which the EKS pod identity
    // webhook injects. Fails loudly if the pod was not granted a role.
    return fromTokenFile()
}
