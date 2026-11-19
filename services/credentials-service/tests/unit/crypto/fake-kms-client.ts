import {
    DecryptCommand,
    GenerateDataKeyCommand,
    InvalidCiphertextException,
    NotFoundException,
    ReEncryptCommand,
} from '@aws-sdk/client-kms'
import { randomBytes } from 'node:crypto'

interface StoredKey {
    plaintext: Buffer
    context: string
    keyArn: string
}

const ARN_PREFIX = 'arn:aws:kms:us-east-1:000000000000:key/'

/** An in-memory stand-in for the KMS API, so AwsKms runs without AWS. */
export class FakeKmsClient {
    readonly calls: string[] = []
    /** Set to make the next `send` throw this error. */
    failNext: Error | null = null
    private readonly blobs = new Map<string, StoredKey>()
    private readonly aliases = new Map<string, string>([
        ['alias/integrations', `${ARN_PREFIX}11111111-1111-1111-1111-111111111111`],
        ['alias/integrations-next', `${ARN_PREFIX}22222222-2222-2222-2222-222222222222`],
    ])

    async send(command: unknown): Promise<Record<string, unknown>> {
        this.calls.push((command as object).constructor.name)
        if (this.failNext) {
            const err = this.failNext
            this.failNext = null
            throw err
        }
        if (command instanceof GenerateDataKeyCommand) {
            const keyArn = this.resolveKey(command.input.KeyId)
            const plaintext = randomBytes(32)
            return {
                Plaintext: new Uint8Array(plaintext),
                CiphertextBlob: this.store(plaintext, command.input.EncryptionContext, keyArn),
                KeyId: keyArn,
            }
        }
        if (command instanceof DecryptCommand) {
            const stored = this.load(command.input.CiphertextBlob, command.input.EncryptionContext)
            return { Plaintext: new Uint8Array(stored.plaintext), KeyId: stored.keyArn }
        }
        if (command instanceof ReEncryptCommand) {
            const stored = this.load(command.input.CiphertextBlob, command.input.SourceEncryptionContext)
            const keyArn = this.resolveKey(command.input.DestinationKeyId)
            return {
                CiphertextBlob: this.store(stored.plaintext, command.input.DestinationEncryptionContext, keyArn),
                KeyId: keyArn,
            }
        }
        throw new Error('unexpected command')
    }

    private resolveKey(keyId: string | undefined): string {
        const arn = keyId ? (this.aliases.get(keyId) ?? keyId) : undefined
        if (!arn || ![...this.aliases.values()].includes(arn)) {
            throw new NotFoundException({ message: 'no such key', $metadata: {} })
        }
        return arn
    }

    private store(plaintext: Buffer, context: Record<string, string> | undefined, keyArn: string): Uint8Array {
        const blob = randomBytes(48)
        this.blobs.set(blob.toString('hex'), {
            plaintext: Buffer.from(plaintext),
            context: JSON.stringify(context ?? {}),
            keyArn,
        })
        return new Uint8Array(blob)
    }

    private load(blob: Uint8Array | undefined, context: Record<string, string> | undefined): StoredKey {
        const stored = blob ? this.blobs.get(Buffer.from(blob).toString('hex')) : undefined
        // Real KMS answers a context mismatch the same way as an unknown blob.
        if (!stored || stored.context !== JSON.stringify(context ?? {})) {
            throw new InvalidCiphertextException({ message: 'invalid ciphertext', $metadata: {} })
        }
        return stored
    }
}
