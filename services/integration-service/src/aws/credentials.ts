// AWS credentials for this service, chosen explicitly rather than by the SDK's default
// chain.
//
// The default chain (`@aws-sdk/credential-provider-node`) tries, in order: environment,
// SSO cache, shared INI profiles, a `credential_process` subprocess, web identity, and
// finally the EC2 instance metadata service. For a service whose entire job is holding
// third-party credentials, most of those are paths it should never be able to take —
// silently authenticating as an EC2 instance role, or as whatever a developer last
// logged into with `aws sso login`, is a failure mode worth removing rather than
// documenting.
//
// So there are exactly two ways in:
//   - in the cluster: the IRSA web identity token, which is how the pod is meant to
//     assume its role;
//   - against a local mock (moto): static throwaway credentials, only when
//     AWS_ENDPOINT_URL points somewhere that is not AWS.
//
// Narrowing this also drops the SSO/INI/IMDS providers out of the bundle, which is what
// keeps deps-allowlist.txt short.

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
