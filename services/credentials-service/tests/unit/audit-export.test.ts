import { EventEmitter } from 'node:events'
import https from 'node:https'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { captureSender, toCaptureEvent } from '@/audit/exporter'
import type { AuditExportConfig } from '@/lib/config'

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

    it('does not use the https module without a proxy', async () => {
        const request = vi.spyOn(https, 'request')
        const fetchFn = vi.fn(async () => new Response(null, { status: 200 })) as unknown as typeof fetch
        await captureSender(CONFIG, fetchFn)([])
        expect(fetchFn).toHaveBeenCalledOnce()
        expect(request).not.toHaveBeenCalled()
    })
})
