// Credentials. The CLI reimplements no login: it reads the file `posthog-cli login` writes, and
// lets the environment override it, so a developer logs in once and CI sets variables.

import { readFileSync } from 'node:fs'
import { join } from 'node:path'

import { WorkflowError } from '../errors.js'

const DEFAULT_HOST = 'https://us.posthog.com'

export interface Credentials {
    readonly apiKey: string
    readonly projectId: string
    readonly host: string
    /** Named in the output, so a surprising project is traceable to where it came from. */
    readonly source: string
}

/**
 * The shape the Rust CLI writes, from `Token` in `cli/src/utils/auth.rs`. Reading it is the whole
 * reason `posthog-cli login` serves both tools, so a change to those three field names is a change
 * this file has to follow. Nothing checks that automatically: a test that read the Rust source
 * from here would couple two trees through a string match that a rename or a reformat breaks.
 */
interface CredentialsFile {
    readonly host?: string | null
    readonly token?: string
    readonly env_id?: string
}

/** `POSTHOG_HOME` first, then `~/.posthog`, following `cli/src/utils/homedir.rs`. */
function credentialsPath(env: Readonly<Record<string, string | undefined>>, homeDir: string): string {
    const home = env.POSTHOG_HOME
    return home === undefined || home === ''
        ? join(homeDir, '.posthog', 'credentials.json')
        : join(home, 'credentials.json')
}

function readFile(path: string): CredentialsFile | null {
    try {
        return JSON.parse(readFileSync(path, 'utf8')) as CredentialsFile
    } catch {
        return null
    }
}

function shown(path: string, homeDir: string): string {
    return path.startsWith(homeDir) ? `~${path.slice(homeDir.length)}` : path
}

/**
 * The key and the project resolve together from one source, following the Rust CLI. Mixing them
 * would let a token from the environment write to the project id left in the file, which is how a
 * staging deploy reaches production.
 *
 * `POSTHOG_CLI_HOST` is the one value that overrides on its own. The Rust CLI takes the host from
 * the same source as the pair; this CLI does not, because pointing one set of credentials at
 * another instance is what the variable is for, and a push names the host it wrote to.
 *
 * Null rather than a throw when nothing is configured, which is what lets `check` degrade.
 */
export function resolveCredentials(
    env: Readonly<Record<string, string | undefined>>,
    homeDir: string
): Credentials | null {
    const host = env.POSTHOG_CLI_HOST?.replace(/\/+$/, '')
    const apiKey = env.POSTHOG_CLI_API_KEY ?? env.POSTHOG_CLI_TOKEN
    const projectId = env.POSTHOG_CLI_PROJECT_ID ?? env.POSTHOG_CLI_ENV_ID

    if (apiKey !== undefined && apiKey !== '' && projectId !== undefined && projectId !== '') {
        return { apiKey, projectId, host: host ?? DEFAULT_HOST, source: 'the environment' }
    }

    const path = credentialsPath(env, homeDir)
    const file = readFile(path)
    if (file?.token !== undefined && file.token !== '' && file.env_id !== undefined && file.env_id !== '') {
        return {
            apiKey: file.token,
            projectId: file.env_id,
            host: host ?? file.host?.replace(/\/+$/, '') ?? DEFAULT_HOST,
            source: shown(path, homeDir),
        }
    }
    return null
}

export function requireCredentials(env: Readonly<Record<string, string | undefined>>, homeDir: string): Credentials {
    const credentials = resolveCredentials(env, homeDir)
    if (credentials !== null) {
        return credentials
    }
    throw new WorkflowError({
        status: 'missing_credentials',
        message: 'No PostHog credentials.',
        why: `push writes to a project, so it needs a personal API key with hog_flow:write and the project to write into. Neither the environment nor ${shown(credentialsPath(env, homeDir), homeDir)} carried both.`,
        fix: 'In CI set POSTHOG_CLI_API_KEY, POSTHOG_CLI_PROJECT_ID and POSTHOG_CLI_HOST. On your own machine run posthog-cli login once.',
    })
}
