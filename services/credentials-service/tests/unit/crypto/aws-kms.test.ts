import { DecryptCommand, GenerateDataKeyCommand, KMSClient, ReEncryptCommand } from '@aws-sdk/client-kms'
import type { Agent } from 'node:https'
import { describe, expect, it } from 'vitest'

import { AwsKms, kmsClientConfig } from '@/crypto/aws-kms'
import type { EncryptionContext } from '@/crypto/types'

const CONTEXT: EncryptionContext = { integrationId: 'int-1', ownerId: '42', kind: 'slack' }
const KMS_CONTEXT = { integration_id: 'int-1', owner_id: '42', kind: 'slack' }

class RecordingClient {
    readonly commands: unknown[] = []

    constructor(private readonly respond: (command: unknown) => Record<string, unknown> | Error) {}

    async send(command: unknown): Promise<Record<string, unknown>> {
        this.commands.push(command)
        const result = this.respond(command)
        if (result instanceof Error) {
            throw result
        }
        return result
    }
}

function awsError(name: string): Error {
    return Object.assign(new Error('fake failure'), { name })
}

describe('AwsKms', () => {
    it('asks KMS for an AES-256 data key under the configured key and the row context', async () => {
        const client = new RecordingClient(() => ({
            Plaintext: new Uint8Array(32).fill(5),
            CiphertextBlob: new Uint8Array([1, 2, 3]),
            KeyId: 'arn:aws:kms:us-east-1:000000000000:key/fake',
        }))

        const dataKey = await new AwsKms(client, 'alias/integrations').generateDataKey(CONTEXT)

        const command = client.commands[0] as GenerateDataKeyCommand
        expect(command).toBeInstanceOf(GenerateDataKeyCommand)
        expect(command.input).toEqual({
            KeyId: 'alias/integrations',
            KeySpec: 'AES_256',
            EncryptionContext: KMS_CONTEXT,
        })
        expect(dataKey).toEqual({
            plaintextKey: Buffer.alloc(32, 5),
            wrappedKey: Buffer.from([1, 2, 3]),
            keyId: 'arn:aws:kms:us-east-1:000000000000:key/fake',
        })
    })

    it('decrypts with the row context and no key id, so keys from before a rotation still unwrap', async () => {
        const client = new RecordingClient(() => ({ Plaintext: new Uint8Array(32).fill(6) }))

        const key = await new AwsKms(client, 'alias/integrations').decrypt(Buffer.from([9]), CONTEXT)

        const command = client.commands[0] as DecryptCommand
        expect(command).toBeInstanceOf(DecryptCommand)
        expect(command.input).toEqual({ CiphertextBlob: Buffer.from([9]), EncryptionContext: KMS_CONTEXT })
        expect(key).toEqual(Buffer.alloc(32, 6))
    })

    it('rewraps inside KMS with the same context on both sides', async () => {
        const client = new RecordingClient(() => ({
            CiphertextBlob: new Uint8Array([7]),
            KeyId: 'arn:aws:kms:us-east-1:000000000000:key/next',
        }))

        const result = await new AwsKms(client, 'alias/integrations').rewrap(Buffer.from([9]), CONTEXT, 'alias/next')

        const command = client.commands[0] as ReEncryptCommand
        expect(command).toBeInstanceOf(ReEncryptCommand)
        expect(command.input).toEqual({
            CiphertextBlob: Buffer.from([9]),
            SourceEncryptionContext: KMS_CONTEXT,
            DestinationKeyId: 'alias/next',
            DestinationEncryptionContext: KMS_CONTEXT,
        })
        expect(result).toEqual({ wrappedKey: Buffer.from([7]), keyId: 'arn:aws:kms:us-east-1:000000000000:key/next' })
    })

    it('zeroes the SDK plaintext through the returned buffer', async () => {
        const plaintext = new Uint8Array(32).fill(6)
        const client = new RecordingClient(() => ({ Plaintext: plaintext }))

        const key = await new AwsKms(client, 'alias/integrations').decrypt(Buffer.from([9]), CONTEXT)
        key.fill(0)

        expect(plaintext.every((byte) => byte === 0)).toBe(true)
    })

    it.each([
        ['InvalidCiphertextException', 'rejected'],
        ['AccessDeniedException', 'rejected'],
        ['DisabledException', 'rejected'],
        ['KMSInvalidStateException', 'rejected'],
        ['NotFoundException', 'rejected'],
        ['ThrottlingException', 'unavailable'],
        ['TimeoutError', 'unavailable'],
        ['KMSInternalException', 'unavailable'],
    ])('maps %s to %s', async (name, reason) => {
        const client = new RecordingClient(() => awsError(name))

        await expect(new AwsKms(client, 'alias/integrations').decrypt(Buffer.from([9]), CONTEXT)).rejects.toMatchObject(
            { name: 'KmsError', reason, message: `KMS Decrypt failed: ${name}` }
        )
    })

    it('treats a response without a plaintext key as unavailable', async () => {
        const client = new RecordingClient(() => ({ CiphertextBlob: new Uint8Array([1]), KeyId: 'k' }))

        await expect(new AwsKms(client, 'alias/integrations').generateDataKey(CONTEXT)).rejects.toMatchObject({
            reason: 'unavailable',
        })
    })
})

describe('kmsClientConfig', () => {
    function agentOf(config: ReturnType<typeof kmsClientConfig>): Agent & { options: Record<string, unknown> } {
        return (config.requestHandler as { httpsAgent: Agent & { options: Record<string, unknown> } }).httpsAgent
    }

    it('bounds each call to 2s per attempt and 2 retries', () => {
        const config = kmsClientConfig({ provider: 'aws', keyId: 'alias/integrations' })

        expect(config.maxAttempts).toBe(3)
        expect(config.requestHandler).toMatchObject({
            connectionTimeout: 2000,
            requestTimeout: 2000,
            throwOnRequestTimeout: true,
            socketTimeout: 2000,
        })
        expect(agentOf(config).maxSockets).toBe(50)
    })

    // The pods carry HTTPS_PROXY for the egress proxy. An agent without proxyEnv ignores it.
    it('connects directly unless a KMS proxy is configured', () => {
        const direct = agentOf(kmsClientConfig({ provider: 'aws', keyId: 'alias/integrations' }))
        const proxied = agentOf(
            kmsClientConfig({ provider: 'aws', keyId: 'alias/integrations', proxyUrl: 'http://proxy.example.com:3128' })
        )

        expect(direct.options.proxyEnv).toBeUndefined()
        expect(proxied.options.proxyEnv).toEqual({ HTTPS_PROXY: 'http://proxy.example.com:3128' })
    })

    it('passes the region and endpoint through, and builds a client', async () => {
        const config = kmsClientConfig({
            provider: 'aws',
            keyId: 'alias/integrations',
            region: 'eu-central-1',
            endpoint: 'https://kms.example.com',
        })

        expect(config).toMatchObject({ region: 'eu-central-1', endpoint: 'https://kms.example.com' })
        const client = new KMSClient(config)
        expect(await client.config.region()).toBe('eu-central-1')
        client.destroy()
    })
})
