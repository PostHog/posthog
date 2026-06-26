// Tests for jwt.ts: RS256 key pair generated inline, tokens signed and verified.
//
// Coverage mirrors the Python validate_* tests in
// products/tasks/backend/stream/tests/ adapted for the Node JWT helpers.

import { SignJWT, exportSPKI, generateKeyPair } from 'jose'
import { describe, it, expect, beforeAll } from 'vitest'

import { SANDBOX_EVENT_INGEST_AUDIENCE, STREAM_READ_AUDIENCE } from '@/lib/constants.js'
import { loadPublicKeys, validateSandboxEventIngestToken, validateStreamReadToken } from '@/lib/jwt.js'

// ---------------------------------------------------------------------------
// Shared key-pair fixture
// ---------------------------------------------------------------------------

interface KeyPairFixture {
    privateKey: CryptoKey
    alternatePrivateKey: CryptoKey
    // Default trusted set the validators receive: the primary key only.
    publicKeys: CryptoKey[]
    primaryPublicKey: CryptoKey
    alternatePublicKey: CryptoKey
}

let keys: KeyPairFixture

beforeAll(async () => {
    const primary = await generateKeyPair('RS256', { extractable: true })
    const alternate = await generateKeyPair('RS256', { extractable: true })

    const [primaryPublicKey, alternatePublicKey] = await loadPublicKeys([
        await exportSPKI(primary.publicKey),
        await exportSPKI(alternate.publicKey),
    ])
    if (!primaryPublicKey || !alternatePublicKey) {
        throw new Error('failed to load test public keys')
    }

    keys = {
        privateKey: primary.privateKey,
        alternatePrivateKey: alternate.privateKey,
        publicKeys: [primaryPublicKey],
        primaryPublicKey,
        alternatePublicKey,
    }
})

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

interface TokenOptions {
    audience?: string
    runId?: string
    taskId?: string
    teamId?: unknown
    expiresIn?: string
    omitExp?: boolean
    signingKey?: CryptoKey
}

async function signToken(opts: TokenOptions = {}): Promise<string> {
    const {
        audience = STREAM_READ_AUDIENCE,
        runId = 'run-abc-123',
        taskId = 'task-abc-123',
        teamId = 42,
        expiresIn = '1h',
        omitExp = false,
        signingKey,
    } = opts

    const builder = new SignJWT({ run_id: runId, task_id: taskId, team_id: teamId }).setProtectedHeader({
        alg: 'RS256',
    })

    if (audience) {
        builder.setAudience(audience)
    }
    if (!omitExp) {
        builder.setExpirationTime(expiresIn)
    }

    return builder.sign(signingKey ?? keys.privateKey)
}

// ---------------------------------------------------------------------------
// stream_read tokens
// ---------------------------------------------------------------------------

describe('jwt', () => {
    describe('validateStreamReadToken', () => {
        it('verifies a valid stream_read token', async () => {
            const token = await signToken({ audience: STREAM_READ_AUDIENCE })
            const payload = await validateStreamReadToken(token, keys.publicKeys)

            expect(payload.runId).toBe('run-abc-123')
            expect(payload.taskId).toBe('task-abc-123')
            expect(payload.teamId).toBe(42)
        })

        it('rejects a token with the wrong audience (sandbox_event_ingest)', async () => {
            const token = await signToken({ audience: SANDBOX_EVENT_INGEST_AUDIENCE })

            await expect(validateStreamReadToken(token, keys.publicKeys)).rejects.toThrow(Error)
        })

        it('rejects an expired token', async () => {
            const token = await signToken({ audience: STREAM_READ_AUDIENCE, expiresIn: '-1s' })

            await expect(validateStreamReadToken(token, keys.publicKeys)).rejects.toThrow(Error)
        })

        it('rejects a token signed with a different private key (bad signature)', async () => {
            const token = await signToken({
                audience: STREAM_READ_AUDIENCE,
                signingKey: keys.alternatePrivateKey,
            })

            await expect(validateStreamReadToken(token, keys.publicKeys)).rejects.toThrow(Error)
        })

        it('rejects a plainly malformed token string', async () => {
            await expect(validateStreamReadToken('not.a.jwt', keys.publicKeys)).rejects.toThrow(Error)
        })

        it('rejects when run_id claim is not a string', async () => {
            const token = await signToken({ audience: STREAM_READ_AUDIENCE, runId: 999 as unknown as string })

            await expect(validateStreamReadToken(token, keys.publicKeys)).rejects.toThrow('run_id must be a string')
        })

        it('rejects when task_id claim is not a string', async () => {
            const token = await signToken({ audience: STREAM_READ_AUDIENCE, taskId: true as unknown as string })

            await expect(validateStreamReadToken(token, keys.publicKeys)).rejects.toThrow('task_id must be a string')
        })

        it('rejects when team_id claim is a float', async () => {
            const token = await signToken({ audience: STREAM_READ_AUDIENCE, teamId: 1.5 })

            await expect(validateStreamReadToken(token, keys.publicKeys)).rejects.toThrow('team_id must be an integer')
        })

        it('rejects when team_id claim is a string', async () => {
            const token = await signToken({ audience: STREAM_READ_AUDIENCE, teamId: '42' })

            await expect(validateStreamReadToken(token, keys.publicKeys)).rejects.toThrow('team_id must be an integer')
        })

        it('rejects when team_id claim is null', async () => {
            const token = await signToken({ audience: STREAM_READ_AUDIENCE, teamId: null })

            await expect(validateStreamReadToken(token, keys.publicKeys)).rejects.toThrow('team_id must be an integer')
        })

        it('rejects when team_id claim is a boolean', async () => {
            // Number.isInteger(true) is false because typeof true === 'boolean'
            const token = await signToken({ audience: STREAM_READ_AUDIENCE, teamId: true })

            await expect(validateStreamReadToken(token, keys.publicKeys)).rejects.toThrow('team_id must be an integer')
        })
    })

    // ---------------------------------------------------------------------------
    // sandbox_event_ingest tokens
    // ---------------------------------------------------------------------------

    describe('validateSandboxEventIngestToken', () => {
        it('verifies a valid sandbox_event_ingest token', async () => {
            const token = await signToken({ audience: SANDBOX_EVENT_INGEST_AUDIENCE })
            const payload = await validateSandboxEventIngestToken(token, keys.publicKeys)

            expect(payload.runId).toBe('run-abc-123')
            expect(payload.taskId).toBe('task-abc-123')
            expect(payload.teamId).toBe(42)
        })

        it('rejects a token with the wrong audience (stream_read)', async () => {
            const token = await signToken({ audience: STREAM_READ_AUDIENCE })

            await expect(validateSandboxEventIngestToken(token, keys.publicKeys)).rejects.toThrow(Error)
        })

        it('rejects an expired token', async () => {
            const token = await signToken({ audience: SANDBOX_EVENT_INGEST_AUDIENCE, expiresIn: '-1s' })

            await expect(validateSandboxEventIngestToken(token, keys.publicKeys)).rejects.toThrow(Error)
        })

        it('rejects a token signed with a different private key (bad signature)', async () => {
            const token = await signToken({
                audience: SANDBOX_EVENT_INGEST_AUDIENCE,
                signingKey: keys.alternatePrivateKey,
            })

            await expect(validateSandboxEventIngestToken(token, keys.publicKeys)).rejects.toThrow(Error)
        })

        it('rejects a plainly malformed token string', async () => {
            await expect(validateSandboxEventIngestToken('header.payload', keys.publicKeys)).rejects.toThrow(Error)
        })

        it('rejects when run_id claim is not a string', async () => {
            const token = await signToken({
                audience: SANDBOX_EVENT_INGEST_AUDIENCE,
                runId: 0 as unknown as string,
            })

            await expect(validateSandboxEventIngestToken(token, keys.publicKeys)).rejects.toThrow(
                'run_id must be a string'
            )
        })

        it('rejects when task_id claim is not a string', async () => {
            const token = await signToken({
                audience: SANDBOX_EVENT_INGEST_AUDIENCE,
                taskId: null as unknown as string,
            })

            await expect(validateSandboxEventIngestToken(token, keys.publicKeys)).rejects.toThrow(
                'task_id must be a string'
            )
        })

        it('rejects when team_id claim is a float', async () => {
            const token = await signToken({ audience: SANDBOX_EVENT_INGEST_AUDIENCE, teamId: 42.7 })

            await expect(validateSandboxEventIngestToken(token, keys.publicKeys)).rejects.toThrow(
                'team_id must be an integer'
            )
        })

        it('rejects when team_id claim is missing', async () => {
            // Build a token without team_id using a raw builder
            const token = await new SignJWT({ run_id: 'r', task_id: 't' })
                .setProtectedHeader({ alg: 'RS256' })
                .setAudience(SANDBOX_EVENT_INGEST_AUDIENCE)
                .setExpirationTime('1h')
                .sign(keys.privateKey)

            await expect(validateSandboxEventIngestToken(token, keys.publicKeys)).rejects.toThrow(
                'team_id must be an integer'
            )
        })
    })

    // ---------------------------------------------------------------------------
    // Key rotation: a token signed under the secondary key still verifies
    // ---------------------------------------------------------------------------

    describe('key rotation', () => {
        it('accepts a token signed with the secondary key when both keys are trusted', async () => {
            const token = await signToken({
                audience: STREAM_READ_AUDIENCE,
                signingKey: keys.alternatePrivateKey,
            })

            // Verifying against the primary alone fails (the bad-signature case above)...
            await expect(validateStreamReadToken(token, [keys.primaryPublicKey])).rejects.toThrow(Error)
            // ...but verifying against [primary, secondary] succeeds — zero-downtime rotation.
            const payload = await validateStreamReadToken(token, [keys.primaryPublicKey, keys.alternatePublicKey])
            expect(payload.runId).toBe('run-abc-123')
        })

        it('still rejects an expired token even when multiple keys are trusted', async () => {
            const token = await signToken({
                audience: STREAM_READ_AUDIENCE,
                signingKey: keys.alternatePrivateKey,
                expiresIn: '-1s',
            })

            await expect(
                validateStreamReadToken(token, [keys.primaryPublicKey, keys.alternatePublicKey])
            ).rejects.toThrow(Error)
        })
    })

    // ---------------------------------------------------------------------------
    // loadPublicKeys / normalization
    // ---------------------------------------------------------------------------

    describe('loadPublicKeys', () => {
        it('loads valid SPKI PEMs and returns CryptoKeys', async () => {
            const { publicKey: rawPub } = await generateKeyPair('RS256', { extractable: true })
            const spki = await exportSPKI(rawPub)
            const [key] = await loadPublicKeys([spki])

            expect(key).toBeTruthy()
            expect(key?.type).toBe('public')
        })

        it('keys loaded from PEM verify tokens signed by the matching private key', async () => {
            const { privateKey: pk, publicKey: rawPub } = await generateKeyPair('RS256', { extractable: true })
            const spki = await exportSPKI(rawPub)
            const loadedKeys = await loadPublicKeys([spki])

            const token = await new SignJWT({ run_id: 'r', task_id: 't', team_id: 1 })
                .setProtectedHeader({ alg: 'RS256' })
                .setAudience(STREAM_READ_AUDIENCE)
                .setExpirationTime('1h')
                .sign(pk)

            const payload = await validateStreamReadToken(token, loadedKeys)
            expect(payload.runId).toBe('r')
        })

        it('rejects a PEM with literal backslash-n sequences (not normalized)', async () => {
            // A PEM with \\n instead of real newlines is invalid unless normalized first.
            // loadPublicKeys expects pre-normalized PEMs (normalizePemKey is called in config.ts
            // before the keys reach loadPublicKeys).
            const { publicKey: rawPub } = await generateKeyPair('RS256', { extractable: true })
            const spki = await exportSPKI(rawPub)
            const broken = spki.replace(/\n/g, '\\n')

            await expect(loadPublicKeys([broken])).rejects.toThrow(Error)
        })
    })
})
