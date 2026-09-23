import assert from 'node:assert/strict'
import { mkdirSync, mkdtempSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { describe, it } from 'node:test'

import { resolveCredentials } from '../../src/cli/credentials.js'

/** The file `posthog-cli login` writes, in the shape `Token` in `cli/src/utils/auth.rs` serializes. */
function homeWithCredentials(contents: string): string {
    const home = mkdtempSync(join(tmpdir(), 'posthog-home-'))
    mkdirSync(join(home, '.posthog'))
    writeFileSync(join(home, '.posthog', 'credentials.json'), contents)
    return home
}

const FILE = JSON.stringify({ host: 'https://eu.posthog.com', token: 'phx_from_file', env_id: '99' })

describe('credentials', () => {
    it('reads the file the Rust CLI writes', () => {
        const credentials = resolveCredentials({}, homeWithCredentials(FILE))

        assert.deepEqual(credentials, {
            apiKey: 'phx_from_file',
            projectId: '99',
            host: 'https://eu.posthog.com',
            source: '~/.posthog/credentials.json',
        })
    })

    it('refuses a credentials file with fields of the wrong type', () => {
        const home = homeWithCredentials(JSON.stringify({ host: 42, token: 'phx_from_file', env_id: '99' }))

        assert.throws(
            () => resolveCredentials({}, home),
            (error: unknown): boolean =>
                (error as { fields: { status: string } }).fields.status === 'invalid_credentials_file'
        )
    })

    it('falls back to the PostHog Cloud US host when the file names none', () => {
        const home = homeWithCredentials(JSON.stringify({ token: 'phx_from_file', env_id: '99' }))

        assert.equal(resolveCredentials({}, home)?.host, 'https://us.posthog.com')
    })

    it('lets the environment win over the file', () => {
        const credentials = resolveCredentials(
            { POSTHOG_CLI_API_KEY: 'phx_from_env', POSTHOG_CLI_PROJECT_ID: '2' },
            homeWithCredentials(FILE)
        )

        assert.deepEqual(credentials, {
            apiKey: 'phx_from_env',
            projectId: '2',
            host: 'https://us.posthog.com',
            source: 'the environment',
        })
    })

    it('lets the flags win over the environment, and names them as the source', () => {
        const credentials = resolveCredentials(
            {
                POSTHOG_CLI_API_KEY: 'phx_from_env',
                POSTHOG_CLI_PROJECT_ID: '2',
                POSTHOG_CLI_HOST: 'https://eu.posthog.com',
            },
            homeWithCredentials(FILE),
            { project: '7', host: 'http://localhost:8010/' }
        )

        assert.deepEqual(credentials, {
            apiKey: 'phx_from_env',
            projectId: '7',
            host: 'http://localhost:8010',
            source: 'the environment, project from --project, host from --host',
        })
    })

    it('pairs a project flag with the key from the file when the environment has none', () => {
        const credentials = resolveCredentials({}, homeWithCredentials(FILE), { project: '7' })

        assert.deepEqual(credentials, {
            apiKey: 'phx_from_file',
            projectId: '7',
            host: 'https://eu.posthog.com',
            source: '~/.posthog/credentials.json, project from --project',
        })
    })

    it('takes the older names for the key and the project, also past an empty newer one', () => {
        const credentials = resolveCredentials(
            { POSTHOG_CLI_API_KEY: '', POSTHOG_CLI_TOKEN: 'phx_from_env', POSTHOG_CLI_ENV_ID: '2' },
            homeWithCredentials('')
        )

        assert.equal(credentials?.apiKey, 'phx_from_env')
        assert.equal(credentials?.projectId, '2')
    })

    it('keeps the key and the project together rather than mixing two sources', () => {
        const credentials = resolveCredentials({ POSTHOG_CLI_API_KEY: 'phx_from_env' }, homeWithCredentials(FILE))

        assert.equal(credentials?.apiKey, 'phx_from_file')
        assert.equal(credentials?.projectId, '99')
    })

    it('points the credentials at another instance through the host variable alone', () => {
        const credentials = resolveCredentials(
            { POSTHOG_CLI_HOST: 'http://localhost:8010/' },
            homeWithCredentials(FILE)
        )

        assert.equal(credentials?.host, 'http://localhost:8010')
        assert.equal(credentials?.apiKey, 'phx_from_file')
    })

    it('refuses a plain-http host that is not loopback, wherever it came from', () => {
        const home = homeWithCredentials(FILE)

        const refusal =
            (status: string) =>
            (error: unknown): boolean =>
                (error as { fields: { status: string } }).fields.status === status

        for (const [env, overrides] of [
            [{ POSTHOG_CLI_HOST: 'http://posthog.example.com' }, {}],
            [{}, { host: 'http://posthog.example.com' }],
        ] as const) {
            assert.throws(() => resolveCredentials(env, home, overrides), refusal('insecure_host'))
        }
        assert.throws(
            () => resolveCredentials({ POSTHOG_CLI_HOST: 'posthog.example.com' }, home),
            refusal('invalid_host')
        )
    })

    it('leaves an insecure host alone when there is no key to send to it', () => {
        const empty = mkdtempSync(join(tmpdir(), 'empty-'))

        assert.equal(resolveCredentials({ POSTHOG_CLI_HOST: 'http://posthog.example.com' }, empty), null)
    })

    it('resolves nothing when neither source is complete', () => {
        assert.equal(
            resolveCredentials({ POSTHOG_CLI_HOST: 'http://localhost:8010' }, mkdtempSync(join(tmpdir(), 'empty-'))),
            null
        )
    })
})
