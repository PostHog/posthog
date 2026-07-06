import { describe, it, expect, vi } from 'vitest'

// test-setup.ts globally mocks ./hono/metrics.js (so prom-client does not register
// duplicate metrics across suites), replacing routeLabel with an identity stub.
// Pull the REAL implementation so this suite exercises the actual label logic —
// that global stub is exactly why a routeLabel mismatch could otherwise go unseen.
const { routeLabel } = await vi.importActual<typeof import('@/hono/metrics.js')>('@/hono/metrics.js')

describe('metrics', () => {
    // The http metric `route` label must stay LOW cardinality: parameterised routes
    // collapse to a single stable label, never leaking project/task/run ids. The two
    // primary legs each get their own readable label so stream reads and ingests are
    // distinguishable on dashboards.
    it.each([
        ['/v1/runs/run-xyz/stream', '/v1/runs/stream'],
        ['/v1/runs/run-xyz/ingest', '/v1/runs/ingest'],
        ['/_health', '/_health'],
        ['/_readyz', '/_readyz'],
        ['/_metrics', '/_metrics'],
        ['/health', '/health'],
        ['/', 'other'],
        ['/v1/runs/run-xyz/', 'other'],
        ['/v1/runs/run-xyz/stream/', 'other'],
        ['/api/projects/123/tasks/abc/runs/run-xyz/stream/', 'other'],
    ])('routeLabel(%s) -> %s', (pathname, expected) => {
        expect(routeLabel(pathname)).toBe(expected)
    })

    it('does not leak run ids into the route label', () => {
        expect(routeLabel('/v1/runs/secret-run-id/stream')).not.toContain('secret-run-id')
    })
})
