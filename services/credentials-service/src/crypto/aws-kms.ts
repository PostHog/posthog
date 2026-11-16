import {
    DecryptCommand,
    GenerateDataKeyCommand,
    type KMSClient,
    type KMSClientConfig,
    ReEncryptCommand,
} from '@aws-sdk/client-kms'
import https from 'node:https'

import type { AwsKmsConfig } from '../lib/config'
import { kmsEncryptionContext } from './canonical'
import { type DataKey, type EncryptionContext, type Kms, KmsError, type WrappedDataKey } from './types'

/** Per attempt, for the connection, the response headers and each gap while reading the body. */
const KMS_TIMEOUT_MS = 2_000
/** Smithy's own default, which a custom agent would otherwise drop for Infinity. */
const KMS_MAX_SOCKETS = 50
/** One attempt and two retries. */
const KMS_MAX_ATTEMPTS = 3

// KMS answered, and the answer is no. Every other failure counts as KMS being unavailable.
const REJECTED_ERRORS = new Set([
    'AccessDeniedException',
    'DisabledException',
    'IncorrectKeyException',
    'InvalidCiphertextException',
    'InvalidGrantTokenException',
    'InvalidKeyUsageException',
    'KMSInvalidStateException',
    'NotFoundException',
])

/** `node:https` AgentOptions, plus `proxyEnv` (Node 24.5+), which the Node 22 types do not have yet. */
interface ProxyAwareAgentOptions extends https.AgentOptions {
    proxyEnv?: { HTTPS_PROXY: string }
}

export function kmsClientConfig(config: AwsKmsConfig): KMSClientConfig {
    // The pods carry HTTP_PROXY/HTTPS_PROXY for the egress proxy. An agent built without
    // `proxyEnv` never reads them, even under NODE_USE_ENV_PROXY, so KMS traffic goes direct
    // unless a proxy is set for KMS on purpose.
    const agentOptions: ProxyAwareAgentOptions = { keepAlive: true, maxSockets: KMS_MAX_SOCKETS }
    if (config.proxyUrl) {
        agentOptions.proxyEnv = { HTTPS_PROXY: config.proxyUrl }
    }
    const clientConfig: KMSClientConfig = {
        maxAttempts: KMS_MAX_ATTEMPTS,
        requestHandler: {
            httpsAgent: new https.Agent(agentOptions),
            connectionTimeout: KMS_TIMEOUT_MS,
            requestTimeout: KMS_TIMEOUT_MS,
            throwOnRequestTimeout: true,
            // requestTimeout stops at the response headers. This one also covers a stalled body.
            socketTimeout: KMS_TIMEOUT_MS,
        },
    }
    if (config.region) {
        clientConfig.region = config.region
    }
    if (config.endpoint) {
        clientConfig.endpoint = config.endpoint
    }
    return clientConfig
}

function asKmsError(err: unknown, op: string): KmsError {
    const name = err instanceof Error ? err.name : 'UnknownError'
    // The SDK error name carries no key material, so it is safe in the message.
    return new KmsError(REJECTED_ERRORS.has(name) ? 'rejected' : 'unavailable', `KMS ${op} failed: ${name}`)
}

function required<T>(value: T | undefined, field: string, op: string): T {
    if (value === undefined) {
        throw new KmsError('unavailable', `KMS ${op} returned no ${field}`)
    }
    return value
}

// The SDK returns a Uint8Array. A Buffer view over the same memory lets the caller zero it.
function bufferView(bytes: Uint8Array): Buffer {
    return Buffer.from(bytes.buffer, bytes.byteOffset, bytes.byteLength)
}

export class AwsKms implements Kms {
    readonly provider = 'aws'

    constructor(
        private readonly client: Pick<KMSClient, 'send'>,
        /** The key that wraps new data keys: an alias, key id or key ARN. */
        private readonly keyId: string
    ) {}

    async generateDataKey(context: EncryptionContext): Promise<DataKey> {
        const command = new GenerateDataKeyCommand({
            KeyId: this.keyId,
            KeySpec: 'AES_256',
            EncryptionContext: kmsEncryptionContext(context),
        })
        let output
        try {
            output = await this.client.send(command)
        } catch (err) {
            throw asKmsError(err, 'GenerateDataKey')
        }
        return {
            plaintextKey: bufferView(required(output.Plaintext, 'Plaintext', 'GenerateDataKey')),
            wrappedKey: Buffer.from(required(output.CiphertextBlob, 'CiphertextBlob', 'GenerateDataKey')),
            keyId: required(output.KeyId, 'KeyId', 'GenerateDataKey'),
        }
    }

    async decrypt(wrappedKey: Buffer, context: EncryptionContext): Promise<Buffer> {
        // No KeyId: the wrapped key names its own key, and keys from before a rotation must
        // still unwrap. IAM limits which keys this role can use.
        const command = new DecryptCommand({
            CiphertextBlob: wrappedKey,
            EncryptionContext: kmsEncryptionContext(context),
        })
        let output
        try {
            output = await this.client.send(command)
        } catch (err) {
            throw asKmsError(err, 'Decrypt')
        }
        return bufferView(required(output.Plaintext, 'Plaintext', 'Decrypt'))
    }

    async rewrap(wrappedKey: Buffer, context: EncryptionContext, targetKeyId: string): Promise<WrappedDataKey> {
        // ReEncrypt runs inside KMS, so the plaintext data key never reaches this process.
        const encryptionContext = kmsEncryptionContext(context)
        const command = new ReEncryptCommand({
            CiphertextBlob: wrappedKey,
            SourceEncryptionContext: encryptionContext,
            DestinationKeyId: targetKeyId,
            DestinationEncryptionContext: encryptionContext,
        })
        let output
        try {
            output = await this.client.send(command)
        } catch (err) {
            throw asKmsError(err, 'ReEncrypt')
        }
        return {
            wrappedKey: Buffer.from(required(output.CiphertextBlob, 'CiphertextBlob', 'ReEncrypt')),
            keyId: required(output.KeyId, 'KeyId', 'ReEncrypt'),
        }
    }
}
