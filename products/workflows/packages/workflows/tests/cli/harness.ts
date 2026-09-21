// What the CLI tests run against: a throwaway directory that looks like a customer repository,
// the CLI started as its own process, and a node:http stand-in for PostHog that records what
// reached the wire.

import { spawn } from 'node:child_process'
import { mkdirSync, mkdtempSync, symlinkSync, writeFileSync } from 'node:fs'
import { createServer, type Server } from 'node:http'
import type { AddressInfo } from 'node:net'
import { tmpdir } from 'node:os'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
export const packageRoot = resolve(here, '..', '..', '..')
// The built artifact, not the test build, so the tests run the file the bin entry points at.
const cliEntry = join(packageRoot, 'dist', 'cli', 'main.js')

export interface Workspace {
    readonly dir: string
    /** Stands in for the user's home directory, so no test can read the developer's own credentials. */
    readonly home: string
}

/**
 * A directory holding the given files, with `@posthog/workflows` linked into `node_modules`
 * the way a package manager leaves it, so a fixture imports the package by name.
 */
export function makeWorkspace(files: Readonly<Record<string, string>> = {}): Workspace {
    const dir = mkdtempSync(join(tmpdir(), 'posthog-workflows-'))
    const home = join(dir, 'home')
    mkdirSync(home)
    mkdirSync(join(dir, 'node_modules', '@posthog'), { recursive: true })
    symlinkSync(packageRoot, join(dir, 'node_modules', '@posthog', 'workflows'), 'dir')
    for (const [name, contents] of Object.entries(files)) {
        const target = join(dir, name)
        mkdirSync(dirname(target), { recursive: true })
        writeFileSync(target, contents)
    }
    return { dir, home }
}

export interface RunResult {
    readonly stdout: string
    readonly stderr: string
    readonly code: number
}

/**
 * Runs the CLI with an environment holding only what the test puts in it.
 *
 * The child runs asynchronously on purpose: a synchronous spawn blocks this process's event loop,
 * and the stand-in server runs on that loop, so the CLI would wait for an answer that cannot come.
 */
export async function runCli(
    args: readonly string[],
    options: { workspace: Workspace; env?: Readonly<Record<string, string>> }
): Promise<RunResult> {
    const child = spawn(process.execPath, [cliEntry, ...args], {
        cwd: options.workspace.dir,
        env: {
            PATH: process.env.PATH ?? '',
            HOME: options.workspace.home,
            ...options.env,
        },
    })
    let stdout = ''
    let stderr = ''
    child.stdout.setEncoding('utf8')
    child.stderr.setEncoding('utf8')
    child.stdout.on('data', (chunk: string) => (stdout += chunk))
    child.stderr.on('data', (chunk: string) => (stderr += chunk))
    const code = await new Promise<number>((done) => child.on('close', (status) => done(status ?? -1)))
    return { stdout, stderr, code }
}

export interface RecordedRequest {
    readonly method: string
    readonly url: string
    readonly headers: Readonly<Record<string, string | string[] | undefined>>
    readonly body: Record<string, unknown> | null
}

export interface StoredRow extends Record<string, unknown> {
    id: string
    version: number
}

export interface StandIn {
    readonly url: string
    readonly requests: readonly RecordedRequest[]
    readonly rows: readonly StoredRow[]
    /** Puts a workflow in the project before the CLI runs, as PostHog would already hold it. */
    seed(row: Record<string, unknown>): StoredRow
    close(): Promise<void>
}

export interface StandInOptions {
    /** Field names the server drops from a write, as PostHog does before the backend tickets land. */
    readonly drops?: readonly string[]
    /** Keys the server adds to what it stores, the way it compiles bytecode into a filter. */
    readonly inject?: (row: StoredRow) => void
    /** A PostHog that does not know `?key=` yet, and answers with every workflow in the project. */
    readonly ignoreKeyFilter?: boolean
}

/** A PostHog stand-in that serves the three calls `push` makes. */
export async function startStandIn(options: StandInOptions = {}): Promise<StandIn> {
    const requests: RecordedRequest[] = []
    const rows: StoredRow[] = []
    const drops = new Set(options.drops ?? [])

    const store = (body: Record<string, unknown>, row: StoredRow): StoredRow => {
        for (const [key, value] of Object.entries(body)) {
            if (!drops.has(key)) {
                row[key] = value
            }
        }
        options.inject?.(row)
        return row
    }

    const server: Server = createServer((request, response) => {
        const chunks: Buffer[] = []
        request.on('data', (chunk: Buffer) => chunks.push(chunk))
        request.on('end', () => {
            const raw = Buffer.concat(chunks).toString('utf8')
            const body = raw === '' ? null : (JSON.parse(raw) as Record<string, unknown>)
            const url = request.url ?? ''
            // A copy, because what the server stores is edited afterwards and the record must not move with it.
            requests.push({
                method: request.method ?? '',
                url,
                headers: request.headers,
                body: body === null ? null : (structuredClone(body) as Record<string, unknown>),
            })

            const send = (status: number, payload: unknown): void => {
                response.writeHead(status, { 'Content-Type': 'application/json' })
                response.end(JSON.stringify(payload))
            }

            if (request.method === 'GET') {
                const key = new URL(url, 'http://stand-in').searchParams.get('key')
                send(200, {
                    results: options.ignoreKeyFilter === true ? rows : rows.filter((row) => row.key === key),
                })
                return
            }
            if (request.method === 'POST' && body !== null) {
                const row = store(body, { id: `id-${rows.length + 1}`, version: 1 })
                rows.push(row)
                send(201, row)
                return
            }
            if (request.method === 'PATCH' && body !== null) {
                const id = url.split('/').filter(Boolean).at(-1)
                const row = rows.find((candidate) => candidate.id === id)
                if (row === undefined) {
                    send(404, { detail: 'Not found.' })
                    return
                }
                row.version += 1
                send(200, store(body, row))
                return
            }
            send(405, { detail: 'Method not allowed.' })
        })
    })

    await new Promise<void>((done) => server.listen(0, '127.0.0.1', done))
    const port = (server.address() as AddressInfo).port
    return {
        url: `http://127.0.0.1:${port}`,
        requests,
        rows,
        seed(row: Record<string, unknown>): StoredRow {
            const stored: StoredRow = { id: `id-${rows.length + 1}`, version: 1, ...row }
            rows.push(stored)
            return stored
        },
        close: () =>
            new Promise<void>((done) => {
                // A keep-alive socket from the CLI's fetch would hold the close open.
                server.closeAllConnections()
                server.close(() => done())
            }),
    }
}

/** A workflow file in the shape a customer writes, with whatever the case needs changed. */
export function workflowFile(
    options: { key?: string; name?: string; status?: string; wait?: string; secret?: boolean } = {}
): string {
    const secretImport = options.secret === true ? ', secret, webhook' : ''
    const secretStep = options.secret === true ? 'notify, ' : ''
    const webhook =
        options.secret === true
            ? `
const notify = webhook({
    name: 'Tell the CRM',
    url: 'https://example.com/hooks/onboarding',
    signingSecret: secret('CRM_WEBHOOK_SECRET'),
})
`
            : ''
    return `import { delay, onEvent, path, workflow${secretImport} } from '@posthog/workflows'
${webhook}
export const onboarding = workflow({
    key: '${options.key ?? 'onboarding-nudge'}',
    name: '${options.name ?? 'Onboarding nudge'}',
    status: '${options.status ?? 'draft'}',
    on: onEvent({ event: 'user signed up' }),
    steps: path(${secretStep}delay('${options.wait ?? '1d'}', { name: 'Wait a day' })),
    exit: { reason: 'Onboarding nudge finished' },
})
`
}
