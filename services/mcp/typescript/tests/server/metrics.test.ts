import { beforeEach, describe, expect, it } from 'vitest'

import { Metrics } from '@/server/metrics'

describe('Metrics', () => {
    let metrics: Metrics

    beforeEach(() => {
        metrics = new Metrics()
    })

    describe('constructor', () => {
        it('creates a registry', () => {
            expect(metrics.registry).toBeDefined()
        })

        it('registers default metrics', async () => {
            const output = await metrics.registry.metrics()
            expect(output).toContain('process_')
        })
    })

    describe('incRequest', () => {
        it('increments request counter with labels', async () => {
            metrics.incRequest('POST', '200')
            metrics.incRequest('POST', '200')
            metrics.incRequest('GET', '404')

            const output = await metrics.registry.metrics()
            expect(output).toContain('mcp_requests_total')
            expect(output).toContain('method="POST"')
            expect(output).toContain('status="200"')
            expect(output).toContain('status="404"')
        })
    })

    describe('observeDuration', () => {
        it('observes request duration', async () => {
            metrics.observeDuration('POST', 0.5)
            metrics.observeDuration('POST', 1.5)

            const output = await metrics.registry.metrics()
            expect(output).toContain('mcp_request_duration_seconds')
            expect(output).toContain('method="POST"')
        })
    })

    describe('incToolCall', () => {
        it('increments tool call counter with success status', async () => {
            metrics.incToolCall('dashboard-get', 'success')

            const output = await metrics.registry.metrics()
            expect(output).toContain('mcp_tool_calls_total')
            expect(output).toContain('tool="dashboard-get"')
            expect(output).toContain('status="success"')
        })

        it('increments tool call counter with error status', async () => {
            metrics.incToolCall('dashboard-get', 'error')

            const output = await metrics.registry.metrics()
            expect(output).toContain('status="error"')
        })
    })

    describe('registry.metrics', () => {
        it('returns prometheus format output', async () => {
            const output = await metrics.registry.metrics()
            expect(output).toContain('# HELP')
            expect(output).toContain('# TYPE')
        })

        it('returns correct content type', () => {
            expect(metrics.registry.contentType).toContain('text/plain')
        })
    })
})
