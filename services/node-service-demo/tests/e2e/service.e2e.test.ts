import { spawn, type ChildProcessWithoutNullStreams } from 'node:child_process'
import { randomUUID } from 'node:crypto'
import { createInterface } from 'node:readline'
import { Pool } from 'pg'

import { runPostgresMigrations } from '@posthog/node-migrations'

import { getTestDatabaseUrl } from '../helpers/database.js'

interface StartedProcess {
    child: ChildProcessWithoutNullStreams
    port: number
}

function startService(): Promise<StartedProcess> {
    return new Promise((resolve, reject) => {
        const child = spawn(process.execPath, ['--enable-source-maps', 'dist/server.mjs'], {
            cwd: process.cwd(),
            env: {
                ...process.env,
                DATABASE_URL: getTestDatabaseUrl(),
                LOG_LEVEL: 'info',
                NODE_ENV: 'test',
                PORT: '0',
            },
            stdio: 'pipe',
        })
        let stderr = ''
        child.stderr.on('data', (chunk: Buffer) => {
            stderr += chunk.toString()
        })

        const startupTimeout = setTimeout(() => {
            child.kill('SIGKILL')
            reject(new Error(`Service did not become ready. stderr: ${stderr}`))
        }, 10000)

        const output = createInterface({ input: child.stdout })
        output.on('line', (line) => {
            try {
                const log = JSON.parse(line) as { event?: string; port?: number }
                if (log.event === 'service.started' && typeof log.port === 'number') {
                    clearTimeout(startupTimeout)
                    output.close()
                    resolve({ child, port: log.port })
                }
            } catch {
                return
            }
        })

        child.once('exit', (code, signal) => {
            clearTimeout(startupTimeout)
            reject(new Error(`Service exited before startup with code ${code} and signal ${signal}. stderr: ${stderr}`))
        })
    })
}

function waitForExit(child: ChildProcessWithoutNullStreams): Promise<number | null> {
    return new Promise((resolve, reject) => {
        const timeout = setTimeout(() => {
            child.kill('SIGKILL')
            reject(new Error('Service did not stop within 10 seconds'))
        }, 10000)
        child.once('exit', (code) => {
            clearTimeout(timeout)
            resolve(code)
        })
    })
}

describe('built demo service', () => {
    const databaseUrl = getTestDatabaseUrl()
    const counterName = `e2e-${randomUUID()}`
    const pool = new Pool({ connectionString: databaseUrl })
    let started: StartedProcess | undefined

    beforeAll(async () => {
        await runPostgresMigrations({ databaseUrl, serviceName: 'node-service-demo' })
    })

    afterAll(async () => {
        if (started && started.child.exitCode === null) {
            started.child.kill('SIGKILL')
        }
        await pool.query('DELETE FROM node_service_demo_counters WHERE name = $1', [counterName])
        await pool.end()
    })

    it('serves a migrated database flow and drains on SIGTERM', async () => {
        started = await startService()
        const baseUrl = `http://127.0.0.1:${started.port}`

        const readiness = await fetch(`${baseUrl}/_ready`)
        expect(readiness.status).toBe(200)

        const increment = await fetch(`${baseUrl}/api/counters/${counterName}/increment`, { method: 'POST' })
        expect(increment.status).toBe(200)
        expect(await increment.json()).toEqual({ name: counterName, value: 1 })

        const persisted = await pool.query<{ value: number }>(
            'SELECT value FROM node_service_demo_counters WHERE name = $1',
            [counterName]
        )
        expect(persisted.rows[0]?.value).toBe(1)

        const metrics = await (await fetch(`${baseUrl}/_metrics`)).text()
        expect(metrics).toContain('http_server_requests_total')
        expect(metrics).toContain('route="/api/counters/:name/increment"')

        const exit = waitForExit(started.child)
        started.child.kill('SIGTERM')
        expect(await exit).toBe(0)
    })
})
