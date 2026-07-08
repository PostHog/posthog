// Global vitest setup file — loaded via vitest.config.mts setupFiles.
//
// Mocks the metrics module so prom-client never tries to register duplicate
// Counters/Gauges/Histograms across test files that import handler modules.
// Each handler imports from hono/metrics.js at module load time; without this
// mock the second test suite that imports a handler would fail with
// "A metric with that name has already been registered" from prom-client.

import { vi } from 'vitest'

const mockInc = vi.fn()
const mockDec = vi.fn()
const mockSet = vi.fn()
const mockObserve = vi.fn()

// Counters
const mockCounter = { labels: vi.fn().mockReturnValue({ inc: mockInc }), inc: mockInc }
// Gauges
const mockGauge = {
    labels: vi.fn().mockReturnValue({ inc: mockInc, dec: mockDec, set: mockSet }),
    inc: mockInc,
    dec: mockDec,
    set: mockSet,
}
// Histograms
const mockHistogram = {
    labels: vi.fn().mockReturnValue({ observe: mockObserve }),
    observe: mockObserve,
    startTimer: vi.fn().mockReturnValue(vi.fn()),
}

vi.mock('@/hono/metrics.js', () => ({
    register: {
        metrics: vi.fn().mockResolvedValue(''),
        contentType: 'text/plain; version=0.0.4; charset=utf-8',
    },
    routeLabel: vi.fn((p: string) => p),
    taskRunStreamConnectionsOpenedTotal: mockCounter,
    taskRunStreamConnectionsClosedTotal: mockCounter,
    taskRunStreamConnectionDurationSeconds: mockHistogram,
    taskRunStreamLengthOnConnect: mockHistogram,
    taskRunStreamResumeGapTotal: mockCounter,
    taskRunStreamConnectionsRejectedTotal: mockCounter,
    streamIngestEventsTotal: mockCounter,
    ingestClientDisconnectsTotal: mockCounter,
    httpRequestsTotal: mockCounter,
    httpRequestDurationSeconds: mockHistogram,
    inflightRequests: mockGauge,
    shuttingDown: mockGauge,
    openSseStreams: mockGauge,
    observeStreamConnectionOpened: vi.fn(),
    observeStreamConnectionClosed: vi.fn(),
    observeStreamLengthOnConnect: vi.fn(),
    observeStreamResumeGap: vi.fn(),
    observeStreamConnectionRejected: vi.fn(),
    observeStreamIngestEvents: vi.fn(),
    observeIngestClientDisconnect: vi.fn(),
}))
