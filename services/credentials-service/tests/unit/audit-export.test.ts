import { EventEmitter } from 'node:events'
import https from 'node:https'
import type { Pool } from 'pg'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { captureSender, toCaptureEvent } from '@/audit/exporter'
import { measureAuditExportLag } from '@/audit/lag'
import { auditExportLagSeconds } from '@/audit/metrics'
import type { AuditExportConfig } from '@/lib/config'
import { logger } from '@/lib/logging'

const CONFIG: AuditExportConfig = {
    host: 'https://capture.example.com',
    apiKey: 'phc_fake',
    batchSize: 10,
    intervalSeconds: 10,
    timeoutMs: 1000,
}

const ROW = {
    id: '0190a1c2-0000-7000-8000-000000000001',
    occurred_at: new Date('2026-01-01T00:00:00Z'),
    occurred_at_us: '1767225600000000',
    deployment: 'cdp-api',
    caller: 'tests',
    user_id: '7',
    owner_type: 'team',
    owner_id: '101',
    integration_id: null,
    kind: 'hubspot',
    operation: 'resolve',
    fields: ['access_token'],
    outcome: 'ok',
    request_id: null,
}

describe('measureAuditExportLag', () => {
    afterEach(() => {
        auditExportLagSeconds.set(0)
        vi.restoreAllMocks()
    })

    it('sets the lag gauge from the query result', async () => {
        const query = vi.fn().mockResolvedValue({ rows: [{ lag: '120' }] })
        await measureAuditExportLag({ query } as unknown as Pool)

        expect(query.mock.calls[0]?.[0]).toContain('min(occurred_at)')
        expect(query.mock.calls[0]?.[0]).toContain('exported_at IS NULL')
        expect((await auditExportLagSeconds.get()).values[0]?.value).toBe(120)
    })

    it('keeps the last gauge value when the query fails', async () => {
        auditExportLagSeconds.set(42)
        const query = vi.fn().mockRejectedValue(new Error('database unavailable'))
        const warn = vi.spyOn(logger, 'warn').mockImplementation(() => undefined)

        await expect(measureAuditExportLag({ query } as unknown as Pool)).resolves.toBeUndefined()
        expect((await auditExportLagSeconds.get()).values[0]?.value).toBe(42)
        expect(warn).toHaveBeenCalledWith('audit:lag_query_failed', { error: 'database unavailable' })
    })
})

describe('toCaptureEvent', () => {
    it.each(['dev', 'prod-us', 'prod-eu'])('tags the event with environment %s', (environment) => {
        expect(toCaptureEvent(ROW, environment).properties.environment).toBe(environment)
    })
})

describe('captureSender with a proxy', () => {
    afterEach(() => {
        vi.restoreAllMocks()
    })

    function mockRequest(status: number): { agents: unknown[]; written: string[] } {
        const agents: unknown[] = []
        const written: string[] = []
        vi.spyOn(https, 'request').mockImplementation(((_url: unknown, options: any, cb: any) => {
            agents.push(options.agent)
            const req = new EventEmitter() as EventEmitter & { end: (body: string) => void }
            req.end = (body) => {
                written.push(body)
                const res = Object.assign(new EventEmitter(), { statusCode: status, resume: () => undefined })
                cb(res)
            }
            return req
        }) as any)
        return { agents, written }
    }

    it('sends through an agent that carries the proxy', async () => {
        const { agents, written } = mockRequest(200)
        const send = captureSender({ ...CONFIG, proxyUrl: 'http://proxy.example.com:3128' })
        await send([toCaptureEvent(ROW, 'dev')])
        const agent = agents[0] as https.Agent & { options: Record<string, unknown> }
        expect(agent.options.proxyEnv).toEqual({ HTTPS_PROXY: 'http://proxy.example.com:3128' })
        expect(JSON.parse(written[0]!).api_key).toBe('phc_fake')
    })

    it('treats a non-2xx answer as a failed send without the body in the error', async () => {
        mockRequest(503)
        const send = captureSender({ ...CONFIG, proxyUrl: 'http://proxy.example.com:3128' })
        await expect(send([])).rejects.toThrow('capture answered 503')
    })

    it('rejects within the timeout when the proxy never answers', async () => {
        vi.useFakeTimers()
        try {
            vi.spyOn(https, 'request').mockImplementation((() => {
                const req = new EventEmitter() as EventEmitter & { end: () => void; destroy: (err: Error) => void }
                req.end = () => undefined
                req.destroy = (err) => void req.emit('error', err)
                return req
            }) as any)
            const send = captureSender({ ...CONFIG, proxyUrl: 'http://proxy.example.com:3128' })
            const result = expect(send([])).rejects.toThrow('timed out')
            await vi.advanceTimersByTimeAsync(CONFIG.timeoutMs)
            await result
        } finally {
            vi.useRealTimers()
        }
    })

    it('does not throw when the response errors after the headers', async () => {
        vi.spyOn(https, 'request').mockImplementation(((_url: unknown, _options: unknown, cb: any) => {
            const req = new EventEmitter() as EventEmitter & { end: () => void }
            req.end = () => {
                const res = Object.assign(new EventEmitter(), { statusCode: 200, resume: () => undefined })
                cb(res)
                res.emit('error', new Error('ECONNRESET'))
            }
            return req
        }) as any)
        const send = captureSender({ ...CONFIG, proxyUrl: 'http://proxy.example.com:3128' })
        await expect(send([])).resolves.toBeUndefined()
    })

    it('does not use the https module without a proxy', async () => {
        const request = vi.spyOn(https, 'request')
        const fetchFn = vi.fn(async () => new Response(null, { status: 200 })) as unknown as typeof fetch
        await captureSender(CONFIG, fetchFn)([])
        expect(fetchFn).toHaveBeenCalledOnce()
        expect(request).not.toHaveBeenCalled()
    })
})
