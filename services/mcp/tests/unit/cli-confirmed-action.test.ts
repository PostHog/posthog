import * as fs from 'node:fs/promises'
import * as os from 'node:os'
import * as path from 'node:path'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import {
    HOME_ENV_VAR,
    registerCliConfirmedActionRuntime,
    resolveCliStateDir,
    STATE_DIR_ENV_VAR,
} from '@/cli/confirmed-action'
import { SIGNING_KEY_ENV_VAR } from '@/lib/signed-state'
import { getConfirmedActionRuntime, setConfirmedActionRuntime } from '@/tools/confirmed-action-registry'
import {
    CONFIRMATION_HASH_ARG,
    CONFIRMATION_WORD,
    CONFIRMATION_WORD_ARG,
    executeConfirmedAction,
    prepareConfirmedAction,
} from '@/tools/confirmed-action-runtime'
import type { Context } from '@/tools/types'

function makeContext(): Context {
    const stub = null as unknown as never
    return {
        api: stub,
        cache: stub,
        env: stub,
        stateManager: stub,
        sessionManager: stub,
        getDistinctId: () => Promise.resolve('cli-user'),
        trackEvent: () => Promise.resolve(),
    } as Context
}

/** Each CLI command is its own process, so every call registers afresh. */
function nextCliInvocation(stateDir: string): void {
    setConfirmedActionRuntime(undefined)
    registerCliConfirmedActionRuntime({ [STATE_DIR_ENV_VAR]: stateDir } as NodeJS.ProcessEnv)
}

async function prepare(stateDir: string): Promise<string> {
    nextCliInvocation(stateDir)
    const runtime = getConfirmedActionRuntime()
    const result = await prepareConfirmedAction(makeContext(), {
        args: { id: 'metric-1' },
        purpose: 'data-catalog-metric-delete',
        actionLabel: 'delete metric',
        messageTemplate: "About to delete metric '{id}'.",
        codec: runtime.codec,
        stash: runtime.stash,
    })
    return result.confirmation_hash
}

async function execute(stateDir: string, hash: string): Promise<{ ok: boolean }> {
    nextCliInvocation(stateDir)
    const runtime = getConfirmedActionRuntime()
    return executeConfirmedAction<{ id: string }>(makeContext(), {
        incomingArgs: { [CONFIRMATION_HASH_ARG]: hash, [CONFIRMATION_WORD_ARG]: CONFIRMATION_WORD },
        purpose: 'data-catalog-metric-delete',
        codec: runtime.codec,
        ledger: runtime.ledger,
        stash: runtime.stash,
    })
}

describe('CLI confirmed-action runtime', () => {
    let stateDir: string

    beforeEach(async () => {
        stateDir = await fs.mkdtemp(path.join(os.tmpdir(), 'posthog-cli-confirm-'))
    })

    afterEach(async () => {
        setConfirmedActionRuntime(undefined)
        await fs.rm(stateDir, { force: true, recursive: true })
    })

    it('carries a confirmation from the prepare command to the execute command', async () => {
        const hash = await prepare(stateDir)

        const outcome = await execute(stateDir, hash)

        expect(outcome).toEqual({ ok: true, verifiedArgs: { id: 'metric-1' } })
    })

    it('refuses a confirmation that a previous command already spent', async () => {
        const hash = await prepare(stateDir)
        await execute(stateDir, hash)

        const outcome = await execute(stateDir, hash)

        expect(outcome.ok).toBe(false)
    })

    it('refuses a stored key that is too short to sign with', async () => {
        await fs.writeFile(path.join(stateDir, 'confirmed-action-key'), 'short')
        nextCliInvocation(stateDir)

        expect(() => getConfirmedActionRuntime()).toThrowError(
            expect.objectContaining({ message: expect.stringContaining('delete it and run the command again') })
        )
    })

    it('touches no files until a confirmed action needs the runtime', async () => {
        nextCliInvocation(stateDir)

        expect(await fs.readdir(stateDir)).toEqual([])
    })

    it('reports an unusable state directory in terms the CLI user controls', async () => {
        const blocked = path.join(stateDir, 'not-a-directory')
        await fs.writeFile(blocked, 'x')
        nextCliInvocation(blocked)

        expect(() => getConfirmedActionRuntime()).toThrowError(
            expect.objectContaining({ message: expect.stringContaining(STATE_DIR_ENV_VAR) })
        )
        expect(() => getConfirmedActionRuntime()).not.toThrowError(
            expect.objectContaining({ message: expect.stringContaining('MCP_SIGNED_STATE_KEY') })
        )
    })

    it('reports a signing key that is too short without the state-directory remedy', () => {
        setConfirmedActionRuntime(undefined)
        registerCliConfirmedActionRuntime({
            [STATE_DIR_ENV_VAR]: stateDir,
            [SIGNING_KEY_ENV_VAR]: 'too-short-to-sign-with',
        } as NodeJS.ProcessEnv)

        expect(() => getConfirmedActionRuntime()).toThrowError(
            expect.objectContaining({ message: expect.stringContaining(SIGNING_KEY_ENV_VAR) })
        )
        expect(() => getConfirmedActionRuntime()).not.toThrowError(
            expect.objectContaining({ message: expect.stringContaining(STATE_DIR_ENV_VAR) })
        )
    })

    it('keeps its files under a redirected POSTHOG_HOME', async () => {
        const home = path.join(stateDir, 'posthog-home')
        setConfirmedActionRuntime(undefined)
        registerCliConfirmedActionRuntime({ [HOME_ENV_VAR]: home } as NodeJS.ProcessEnv)

        getConfirmedActionRuntime()

        expect(await fs.readdir(path.join(home, 'cli'))).toEqual(
            expect.arrayContaining(['confirmed-action-key', 'confirmed-actions'])
        )
    })

    it('prefers the explicit state directory over POSTHOG_HOME', () => {
        const resolved = resolveCliStateDir({
            [STATE_DIR_ENV_VAR]: stateDir,
            [HOME_ENV_VAR]: path.join(stateDir, 'posthog-home'),
        } as NodeJS.ProcessEnv)

        expect(resolved).toBe(stateDir)
    })
})
