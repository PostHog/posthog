/**
 * Builds the confirmed-action runtime for the CLI.
 *
 * The generated `-prepare`/`-execute` handlers read a process-level runtime
 * that only the Hono server used to install, so every two-step tool the CLI
 * advertised failed at the first call. The CLI has no Redis and no server
 * signing key, so it keeps its own: a key generated once into a local state
 * directory, and a file-backed store that carries the prepared payload from
 * one CLI process to the next.
 *
 * The key lives in that state directory, so a CLI confirmation is valid
 * wherever the directory is — which is what we want; it authorizes the local
 * user's own next command, nothing else.
 */

import { randomBytes } from 'node:crypto'
import * as fs from 'node:fs'
import * as os from 'node:os'
import * as path from 'node:path'

import {
    FileKeyValueStore,
    loadSigningKeyFromEnv,
    NonceLedger,
    PayloadStash,
    SIGNING_KEY_ENV_VAR,
    SIGNING_KEY_MIN_BYTES,
    SignedStateCodec,
} from '@/lib/signed-state'
import { type ConfirmedActionRuntime, setConfirmedActionRuntimeProvider } from '@/tools/confirmed-action-registry'

import { errorCode } from './utils'

export const STATE_DIR_ENV_VAR = 'POSTHOG_CLI_STATE_DIR'
export const HOME_ENV_VAR = 'POSTHOG_HOME'

const KEY_FILE_NAME = 'confirmed-action-key'
const STORE_DIR_NAME = 'confirmed-actions'

/**
 * `POSTHOG_HOME` is the CLI's existing home contract. The Rust wrapper keeps
 * the credentials and the API bundle under it, and falls back to `~/.posthog`
 * (`cli/src/utils/homedir.rs`). It also tells a user whose home directory
 * refuses writes to point that variable at a writable directory, so the
 * confirmation state must follow it instead of staying under the real home
 * directory.
 */
export function resolveCliStateDir(env: NodeJS.ProcessEnv = process.env): string {
    const explicit = env[STATE_DIR_ENV_VAR]
    if (explicit) {
        return explicit
    }
    return path.join(env[HOME_ENV_VAR] || path.join(os.homedir(), '.posthog'), 'cli')
}

/**
 * Register the builder. It runs on the first prepare or execute call, so a
 * command that never reaches a confirmed action touches no files.
 */
export function registerCliConfirmedActionRuntime(env: NodeJS.ProcessEnv = process.env): void {
    setConfirmedActionRuntimeProvider(() => buildCliConfirmedActionRuntime(env))
}

function buildCliConfirmedActionRuntime(env: NodeJS.ProcessEnv): ConfirmedActionRuntime {
    const stateDir = resolveCliStateDir(env)
    try {
        const key = env[SIGNING_KEY_ENV_VAR] ? loadSigningKeyFromEnv(env) : loadOrCreateLocalKey(stateDir)
        const directory = path.join(stateDir, STORE_DIR_NAME)
        fs.mkdirSync(directory, { mode: 0o700, recursive: true })
        const store = new FileKeyValueStore(directory)
        return {
            codec: new SignedStateCodec(key),
            ledger: new NonceLedger(store),
            stash: new PayloadStash(store),
        }
    } catch (error) {
        const detail = error instanceof Error ? error.message : String(error)
        throw new Error(
            `Two-step confirmation is unavailable on this CLI: ${detail}. ` +
                `Its state directory is ${stateDir}, and ${STATE_DIR_ENV_VAR} moves it.`
        )
    }
}

function loadOrCreateLocalKey(stateDir: string): Buffer {
    const file = path.join(stateDir, KEY_FILE_NAME)
    const existing = readLocalKey(file)
    if (existing) {
        return existing
    }

    const generated = randomBytes(SIGNING_KEY_MIN_BYTES).toString('hex')
    fs.mkdirSync(stateDir, { mode: 0o700, recursive: true })
    try {
        // Exclusive create. Two first-run commands must agree on one key,
        // because a hash the first signs fails verification under a key the
        // second wrote over it.
        fs.writeFileSync(file, generated, { flag: 'wx', mode: 0o600 })
    } catch (error) {
        if (errorCode(error) !== 'EEXIST') {
            throw error
        }
        // Whoever creates the file owns the key. Replacing one this command
        // cannot read would race the same way the exclusive create prevents,
        // so an unusable key is a refusal with one action in it.
        const other = readLocalKey(file)
        if (!other) {
            throw new Error(`the key file ${file} is too short to sign with, so delete it and run the command again`)
        }
        return other
    }
    return Buffer.from(generated, 'utf8')
}

function readLocalKey(file: string): Buffer | undefined {
    let raw: string
    try {
        raw = fs.readFileSync(file, 'utf-8').trim()
    } catch (error) {
        if (errorCode(error) === 'ENOENT') {
            return undefined
        }
        throw error
    }
    return Buffer.byteLength(raw, 'utf8') >= SIGNING_KEY_MIN_BYTES ? Buffer.from(raw, 'utf8') : undefined
}
