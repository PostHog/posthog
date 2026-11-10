import { KMSClient } from '@aws-sdk/client-kms'

import type { KmsConfig } from '../lib/config'
import { AwsKms, kmsClientConfig } from './aws-kms'
import { LocalKms } from './local-kms'
import type { Kms } from './types'

export function createKms(config: KmsConfig): Kms {
    if (config.provider === 'local') {
        return new LocalKms(config.keys)
    }
    return new AwsKms(new KMSClient(kmsClientConfig(config)), config.keyId)
}
