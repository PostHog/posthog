import { http, HttpResponse, type HttpResponseResolver } from 'msw'
import { setupServer } from 'msw/node'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { afterAll, beforeAll, beforeEach, describe, expect, it } from 'vitest'

import { createApp } from '@/hono/app'
import { TASKS_EXTENSION_ID } from '@/hono/mcp-tasks'

import { contextMillHandler, handlers } from '../workers/fixtures/handlers'
import { createInMemoryRedis } from './helpers/in-memory-redis'

const TOKEN = 'phx_tasks_test_token'
const OTHER_USER_TOKEN = 'phx_tasks_other_user_token'
const RUN_ID = '0190a5d3-0000-7000-8000-000000000001'
const START_TOOL = 'experiment-metrics-recalculation-create'

const usersMe = JSON.parse(
    readFileSync(resolve(__dirname, '../workers/fixtures/api_users__me.json'), 'utf-8')
) as Record<string, unknown>

let statusChecks = 0

function recalculationRun(status: 'pending' | 'in_progress' | 'completed'): Record<string, unknown> {
    return {
        id: RUN_ID,
        experiment_id: 7,
        status,
        total_metrics: 2,
        completed_metrics: status === 'completed' ? 2 : status === 'in_progress' ? 1 : 0,
        failed_metrics: 0,
        metric_errors: {},
        created_at: '2026-10-29T10:00:00Z',
        started_at: null,
        completed_at: null,
        query_to: null,
        metric_retries: {},
        results:
            status === 'completed'
                ? [{ metric_uuid: 'metric-1', status: 'completed', result: { chance_to_win: 0.913 } }]
                : [],
    }
}

const otherUser: HttpResponseResolver = ({ request }) =>
    request.headers.get('authorization') === `Bearer ${OTHER_USER_TOKEN}`
        ? HttpResponse.json({ ...usersMe, distinct_id: 'other-distinct-id', uuid: 'other-user-uuid' })
        : undefined

const mswServer = setupServer(
    http.get('*/api/users/@me', otherUser),
    http.get('*/api/users/@me/', otherUser),
    http.post('*/api/projects/:projectId/experiments/:id/metrics_recalculation/', () =>
        HttpResponse.json({ ...recalculationRun('pending'), is_existing: false })
    ),
    http.get('*/api/projects/:projectId/experiments/:id/metrics_recalculation/:runId/', () => {
        statusChecks += 1
        return HttpResponse.json(recalculationRun(statusChecks === 1 ? 'in_progress' : 'completed'))
    }),
    ...handlers,
    contextMillHandler
)

let app: ReturnType<typeof createApp>['app']

async function rpc(
    method: string,
    params: Record<string, unknown>,
    {
        declareTasks = false,
        token = TOKEN,
        path = '/mcp',
    }: { declareTasks?: boolean; token?: string; path?: string } = {}
): Promise<{ result?: Record<string, any>; error?: { code: number; message: string } }> {
    const response = await app.request(path, {
        method: 'POST',
        headers: {
            Authorization: `Bearer ${token}`,
            'Content-Type': 'application/json',
            Accept: 'application/json, text/event-stream',
            'x-posthog-mcp-mode': 'tools',
            'MCP-Protocol-Version': '2026-07-28',
            'Mcp-Method': method,
            ...(typeof params.name === 'string' ? { 'Mcp-Name': params.name } : {}),
        },
        body: JSON.stringify({
            jsonrpc: '2.0',
            id: 1,
            method,
            params: {
                ...params,
                _meta: {
                    'io.modelcontextprotocol/protocolVersion': '2026-07-28',
                    'io.modelcontextprotocol/clientInfo': { name: 'tasks-test', version: '0.0.1' },
                    'io.modelcontextprotocol/clientCapabilities': declareTasks
                        ? { extensions: { [TASKS_EXTENSION_ID]: {} } }
                        : {},
                },
            },
        }),
    })
    return response.json()
}

describe('MCP Tasks extension', () => {
    beforeAll(async () => {
        process.env.TEST = '1'
        process.env.MCP_TASKS_EXTENSION = 'true'
        mswServer.listen({ onUnhandledRequest: 'bypass' })
        const created = createApp(createInMemoryRedis())
        app = created.app
        await created.warmup()
    })

    afterAll(() => {
        delete process.env.MCP_TASKS_EXTENSION
        mswServer.close()
    })

    beforeEach(() => {
        statusChecks = 0
    })

    it('runs a queued recalculation as a task and returns the status tool result when it finishes', async () => {
        const discover = await rpc('server/discover', {})
        expect(discover.result?.capabilities.extensions).toHaveProperty([TASKS_EXTENSION_ID])

        const started = await rpc('tools/call', { name: START_TOOL, arguments: { id: 7 } }, { declareTasks: true })
        expect(started.result).toMatchObject({ resultType: 'task', status: 'working', pollIntervalMs: 5000 })
        const taskId = started.result?.taskId

        const running = await rpc('tasks/get', { taskId }, { declareTasks: true })
        expect(running.result).toMatchObject({ taskId, status: 'working', statusMessage: '1 of 2 metrics done' })
        expect(running.result).not.toHaveProperty('result')

        const finished = await rpc('tasks/get', { taskId }, { declareTasks: true })
        expect(finished.result).toMatchObject({ taskId, status: 'completed' })
        expect(finished.result?.result.isError).toBeFalsy()
        expect(JSON.stringify(finished.result?.result.content)).toContain('0.913')
    })

    it('answers synchronously when the request does not declare the extension', async () => {
        const response = await rpc('tools/call', { name: START_TOOL, arguments: { id: 7 } })

        expect(response.result).toMatchObject({ resultType: 'complete' })
        expect(response.result).not.toHaveProperty('taskId')
        expect(JSON.stringify(response.result?.content)).toContain(RUN_ID)
    })

    it.each([
        { caller: 'a different user', options: { declareTasks: true, token: OTHER_USER_TOKEN }, code: -32602 },
        {
            caller: 'a connection without the status tool',
            options: { declareTasks: true, path: `/mcp?tools=${START_TOOL}` },
            code: -32602,
        },
        { caller: 'a request that does not declare the extension', options: {}, code: -32021 },
    ])('refuses a task to $caller', async ({ options, code }) => {
        const started = await rpc('tools/call', { name: START_TOOL, arguments: { id: 7 } }, { declareTasks: true })

        const response = await rpc('tasks/get', { taskId: started.result?.taskId }, options)

        expect(response.error).toMatchObject({ code })
        expect(statusChecks).toBe(0)
    })

    it('keeps the task working when a status check fails upstream', async () => {
        const started = await rpc('tools/call', { name: START_TOOL, arguments: { id: 7 } }, { declareTasks: true })
        mswServer.use(
            http.get(
                '*/api/projects/:projectId/experiments/:id/metrics_recalculation/:runId/',
                () => HttpResponse.json({ detail: 'Service unavailable' }, { status: 503 }),
                { once: true }
            )
        )

        const failedCheck = await rpc('tasks/get', { taskId: started.result?.taskId }, { declareTasks: true })
        const nextCheck = await rpc('tasks/get', { taskId: started.result?.taskId }, { declareTasks: true })

        expect(failedCheck.result).toMatchObject({ status: 'working' })
        expect(nextCheck.result).toMatchObject({ status: 'working', statusMessage: '1 of 2 metrics done' })
    })
})
