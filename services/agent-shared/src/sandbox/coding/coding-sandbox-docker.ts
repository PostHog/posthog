/**
 * Docker-backed tier-2 coding sandbox (local dev). Provisions one container
 * per session running the real `agent-server` harness from the published
 * PostHog Code image, JWT-authed on its `/command` + `/events` endpoints.
 * The Modal pool (prod) plugs in behind the same `CodingSandboxPool`
 * interface. Image-agnostic — `image` is the seam; the published image is the
 * default, the fixture image is injected by the fast tests.
 *
 * Transport only: it knows nothing about turns, ACP event semantics, or
 * approvals. The supervisor (`runCodingSession`) drives those on top.
 */

import { spawn } from 'node:child_process'
import * as http from 'node:http'
import { URL } from 'node:url'

import {
    CodingAcquireOpts,
    CodingSandbox,
    CodingSandboxPool,
    EventSubscription,
    HarnessCommand,
    HarnessFrame,
    JsonRpcResponse,
} from './contract'

/** The real PostHog Code harness image. Pulled from GHCR; tagged by commit/`master`. */
export const PUBLISHED_HARNESS_IMAGE = 'ghcr.io/posthog/posthog-sandbox-base:master'
const HARNESS_PORT = 3001

/**
 * A `localhost` URL is unreachable from inside the container (it resolves to
 * the container, not the host). Rewrite to `host.docker.internal` (mapped via
 * `--add-host`) so the harness can reach host-run services (the local
 * ai-gateway, the local PostHog API) in dev. No-op for non-loopback hosts.
 */
function dockerizeHostUrl(url: string | undefined): string | undefined {
    if (!url) {
        return url
    }
    return url.replace(/\/\/(localhost|127\.0\.0\.1)(:|\/|$)/, '//host.docker.internal$2')
}

interface DockerState {
    sessionId: string
    containerId: string
    base: string // http://127.0.0.1:<port>
    token: string
}

function runDocker(args: string[]): Promise<{ stdout: string; stderr: string; code: number }> {
    return new Promise((resolve, reject) => {
        const p = spawn('docker', args)
        let stdout = ''
        let stderr = ''
        p.stdout.on('data', (d) => (stdout += d.toString()))
        p.stderr.on('data', (d) => (stderr += d.toString()))
        p.on('exit', (code) => resolve({ stdout, stderr, code: code ?? -1 }))
        p.on('error', reject)
    })
}

function httpJson(
    method: string,
    url: string,
    opts: { headers?: Record<string, string>; body?: string; timeoutMs?: number } = {}
): Promise<{ status: number; body: string }> {
    return new Promise((resolve, reject) => {
        const u = new URL(url)
        const req = http.request(
            {
                hostname: u.hostname,
                port: u.port,
                path: u.pathname,
                method,
                headers: opts.headers,
                timeout: opts.timeoutMs ?? 30_000,
            },
            (res) => {
                let data = ''
                res.on('data', (c) => (data += c))
                res.on('end', () => resolve({ status: res.statusCode ?? 0, body: data }))
            }
        )
        req.on('timeout', () => req.destroy(new Error('http timeout')))
        req.on('error', reject)
        if (opts.body) {
            req.write(opts.body)
        }
        req.end()
    })
}

class DockerCodingSandbox implements CodingSandbox {
    private alive = true
    constructor(private readonly state: DockerState) {}

    get sessionId(): string {
        return this.state.sessionId
    }
    get providerSandboxId(): string {
        return this.state.containerId
    }

    async command(cmd: HarnessCommand): Promise<JsonRpcResponse> {
        if (!this.alive) {
            return { jsonrpc: '2.0', id: 'dead', error: { code: -1, message: 'sandbox released' } }
        }
        const id = `cmd_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`
        const res = await httpJson('POST', `${this.state.base}/command`, {
            headers: { authorization: `Bearer ${this.state.token}`, 'content-type': 'application/json' },
            body: JSON.stringify({ jsonrpc: '2.0', id, method: cmd.method, params: cmd.params ?? {} }),
        })
        try {
            return JSON.parse(res.body) as JsonRpcResponse
        } catch {
            return { jsonrpc: '2.0', id, error: { code: res.status, message: res.body.slice(0, 200) } }
        }
    }

    openEvents(onFrame: (frame: HarnessFrame) => void): EventSubscription {
        const u = new URL(`${this.state.base}/events`)
        const req = http.request(
            {
                hostname: u.hostname,
                port: u.port,
                path: u.pathname,
                method: 'GET',
                headers: { authorization: `Bearer ${this.state.token}`, accept: 'text/event-stream' },
            },
            (res) => {
                res.setEncoding('utf-8')
                let buf = ''
                res.on('data', (chunk) => {
                    buf += chunk
                    let idx
                    while ((idx = buf.indexOf('\n\n')) !== -1) {
                        const frame = buf.slice(0, idx)
                        buf = buf.slice(idx + 2)
                        const dataLine = frame.split('\n').find((l) => l.startsWith('data: '))
                        if (!dataLine) {
                            continue
                        }
                        try {
                            onFrame(JSON.parse(dataLine.slice(6)) as HarnessFrame)
                        } catch {
                            /* keepalive / non-json */
                        }
                    }
                })
            }
        )
        req.on('error', () => undefined)
        req.end()
        return { close: () => req.destroy() }
    }

    async isAlive(): Promise<boolean> {
        if (!this.alive) {
            return false
        }
        const { stdout, code } = await runDocker(['inspect', '-f', '{{.State.Running}}', this.state.containerId])
        return code === 0 && stdout.trim() === 'true'
    }

    async destroy(): Promise<void> {
        this.alive = false
        await runDocker(['rm', '-f', this.state.containerId]).catch(() => undefined)
    }
}

export class DockerCodingSandboxPool implements CodingSandboxPool {
    readonly kind = 'docker-coding' as const
    private readonly bySession = new Map<string, DockerCodingSandbox>()
    private readonly image: string

    constructor(opts?: { image?: string }) {
        this.image = opts?.image ?? PUBLISHED_HARNESS_IMAGE
    }

    async acquireForSession(opts: CodingAcquireOpts): Promise<CodingSandbox> {
        const existing = this.bySession.get(opts.sessionId)
        if (existing && (await existing.isAlive())) {
            return existing
        }

        const { launch, auth, harnessIds } = opts
        const args = [
            'run',
            '-d',
            '--rm',
            '-p',
            `127.0.0.1::${HARNESS_PORT}`,
            '--add-host=host.docker.internal:host-gateway',
            '-w',
            '/scripts',
        ]

        if (launch.limits.memoryMb) {
            args.push('--memory', `${launch.limits.memoryMb}m`)
        }
        if (launch.limits.cpuCores) {
            args.push('--cpus', String(launch.limits.cpuCores))
        }
        if (opts.workspaceMount) {
            args.push(
                '-v',
                `${opts.workspaceMount.hostPath}:/tmp/workspace${opts.workspaceMount.readonly ? ':ro' : ''}`
            )
        }

        const env: Record<string, string> = {
            JWT_PUBLIC_KEY: auth.publicKeyPem,
            POSTHOG_API_URL: dockerizeHostUrl(launch.apiUrl) ?? 'http://host.docker.internal:8010',
            POSTHOG_PERSONAL_API_KEY: launch.apiKey ?? 'phx_local',
            POSTHOG_PROJECT_ID: String(launch.projectId ?? 1),
            POSTHOG_CODE_RUNTIME_ADAPTER: 'claude',
            POSTHOG_CODE_MODEL: launch.model,
        }
        const gatewayUrl = dockerizeHostUrl(launch.modelBaseUrl)
        if (gatewayUrl) {
            env.LLM_GATEWAY_URL = gatewayUrl
        }
        if (launch.reasoningEffort) {
            env.POSTHOG_CODE_REASONING_EFFORT = launch.reasoningEffort
        }
        for (const [k, v] of Object.entries(env)) {
            args.push('-e', `${k}=${v}`)
        }

        args.push(
            this.image,
            '/scripts/node_modules/.bin/agent-server',
            '--port',
            String(HARNESS_PORT),
            '--taskId',
            harnessIds.taskId,
            '--runId',
            harnessIds.runId,
            '--mode',
            'background'
        )
        if (launch.mcpServers.length) {
            args.push('--mcpServers', JSON.stringify(launch.mcpServers))
        }
        if (launch.systemPrompt) {
            args.push('--claudeCodeConfig', JSON.stringify({ systemPrompt: launch.systemPrompt }))
        }

        const { stdout, code, stderr } = await runDocker(args)
        if (code !== 0) {
            throw new Error(`docker run failed: ${stderr.trim()}`)
        }
        const containerId = stdout.trim()

        const portRes = await runDocker(['port', containerId, String(HARNESS_PORT)])
        const hostPort = portRes.stdout.trim().split('\n')[0]?.split(':').pop()
        if (!hostPort) {
            await runDocker(['rm', '-f', containerId]).catch(() => undefined)
            throw new Error(`could not resolve mapped port: ${portRes.stdout}`)
        }
        const base = `http://127.0.0.1:${hostPort}`

        await this.waitForHealth(`${base}/health`, containerId)

        const sandbox = new DockerCodingSandbox({ sessionId: opts.sessionId, containerId, base, token: auth.token })
        this.bySession.set(opts.sessionId, sandbox)
        return sandbox
    }

    private async waitForHealth(healthUrl: string, containerId: string): Promise<void> {
        const deadline = Date.now() + 30_000
        while (Date.now() < deadline) {
            try {
                const res = await httpJson('GET', healthUrl, { timeoutMs: 2_000 })
                if (res.status === 200) {
                    return
                }
            } catch {
                /* not up yet */
            }
            await new Promise((r) => setTimeout(r, 150))
        }
        await runDocker(['rm', '-f', containerId]).catch(() => undefined)
        throw new Error('coding sandbox harness failed health check')
    }

    async release(sessionId: string): Promise<void> {
        const s = this.bySession.get(sessionId)
        if (s) {
            await s.destroy()
            this.bySession.delete(sessionId)
        }
    }
}
