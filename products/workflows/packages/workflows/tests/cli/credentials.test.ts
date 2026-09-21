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

    it('takes the older names for the key and the project', () => {
        const credentials = resolveCredentials(
            { POSTHOG_CLI_TOKEN: 'phx_from_env', POSTHOG_CLI_ENV_ID: '2' },
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

    it('resolves nothing when neither source is complete', () => {
        assert.equal(
            resolveCredentials({ POSTHOG_CLI_HOST: 'http://localhost:8010' }, mkdtempSync(join(tmpdir(), 'empty-'))),
            null
        )
    })
})
