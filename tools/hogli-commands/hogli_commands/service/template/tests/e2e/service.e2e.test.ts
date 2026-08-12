import { spawn, type ChildProcessWithoutNullStreams } from 'node:child_process'
import { createInterface } from 'node:readline'

interface StartedProcess {
    child: ChildProcessWithoutNullStreams
    port: number
}

function startService(): Promise<StartedProcess> {
    return new Promise((resolve, reject) => {
        const child = spawn(process.execPath, ['--enable-source-maps', 'dist/server.mjs'], {
            cwd: process.cwd(),
            env: { ...process.env, LOG_LEVEL: 'info', NODE_ENV: 'test', PORT: '0' },
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

describe('built service', () => {
    let started: StartedProcess | undefined

    afterAll(() => {
        if (started && started.child.exitCode === null) {
            started.child.kill('SIGKILL')
        }
    })

    it('serves the feature and drains on SIGTERM', async () => {
        started = await startService()
        const baseUrl = `http://127.0.0.1:${started.port}`

        expect((await fetch(`${baseUrl}/_ready`)).status).toBe(200)
        const response = await fetch(`${baseUrl}/api/hello/Ada`)
        expect(response.status).toBe(200)
        expect(await response.json()).toEqual({ greeting: 'Hello, Ada.' })

        const metrics = await (await fetch(`${baseUrl}/_metrics`)).text()
        expect(metrics).toContain('http_server_requests_total')
        expect(metrics).toContain('route="/api/hello/:name"')

        const exit = waitForExit(started.child)
        started.child.kill('SIGTERM')
        expect(await exit).toBe(0)
    })
})
