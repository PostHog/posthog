import type { CanvasGenerationTask } from 'products/canvas/frontend/canvasTasksApi'
import type { CanvasViewResponseApi } from 'products/canvas/frontend/generated/api.schemas'

import { customChartDataFromResponse, sampleCustomChartData } from './customChartData'
import { CustomChartStatus, customChartStatus } from './customChartLogic'

const readyBuild = { id: 'build-1', build_status: 'ready', artifact_url: 'https://artifacts.example.com/b/index.html' }

function view(overrides: Record<string, unknown> = {}): CanvasViewResponseApi {
    return {
        canvas: { id: 'canvas-1', generation_task_id: 'task-1' },
        published_build: null,
        has_active_build: false,
        current_version_id: null,
        ...overrides,
    } as unknown as CanvasViewResponseApi
}

function task(status: string | null): CanvasGenerationTask {
    return { id: 'task-1', title: 'Chart', latest_run: status ? { id: 'run-1', status } : null } as CanvasGenerationTask
}

describe('custom chart', () => {
    test.each<[string, CanvasViewResponseApi | null, boolean, CanvasGenerationTask | null, CustomChartStatus]>([
        ['an unreadable canvas falls back', null, true, null, 'unavailable'],
        ['nothing loaded yet', null, false, null, 'loading'],
        [
            'a ready build draws while the agent still works',
            view({ published_build: readyBuild }),
            false,
            task('in_progress'),
            'ready',
        ],
        ['an active build is building', view({ has_active_build: true }), false, task('completed'), 'building'],
        ['a running agent is building', view(), false, task('in_progress'), 'building'],
        ['an agent that ended without a build failed', view(), false, task('completed'), 'failed'],
        ['a failed run failed', view(), false, task('failed'), 'failed'],
        [
            'a canvas with no agent task failed',
            view({ canvas: { id: 'canvas-1', generation_task_id: null } }),
            false,
            null,
            'failed',
        ],
    ])('status: %s', (_, canvasView, unavailable, generationTask, expected) => {
        expect(customChartStatus(canvasView, unavailable, generationTask)).toEqual(expected)
    })

    test.each([
        [
            'trends results',
            { kind: 'TrendsQuery' },
            { result: [{ label: 'Pageviews', data: [1, 2] }] },
            { query: { kind: 'TrendsQuery' }, results: [{ label: 'Pageviews', data: [1, 2] }] },
        ],
        [
            'SQL rows with columns',
            { kind: 'HogQLQuery' },
            { results: [[1, 'a']], columns: ['count', 'name'], types: ['UInt64', 'String'] },
            {
                query: { kind: 'HogQLQuery' },
                results: [[1, 'a']],
                columns: ['count', 'name'],
                types: ['UInt64', 'String'],
            },
        ],
        ['a response with no results', { kind: 'TrendsQuery' }, { error: 'boom' }, null],
    ])('data from %s', (_, query, response, expected) => {
        expect(customChartDataFromResponse(query, response)).toEqual(expected)
    })

    it('keeps the sample small enough for the agent prompt', () => {
        const series = Array.from({ length: 50 }, (_, index) => ({
            label: `Series ${index} ${'x'.repeat(200)}`,
            data: Array.from({ length: 365 }, (_, day) => day),
            days: Array.from({ length: 365 }, (_, day) => `2026-01-${day}`),
        }))
        const sample = sampleCustomChartData({ query: { kind: 'TrendsQuery' }, results: series })

        expect(JSON.stringify(sample).length).toBeLessThanOrEqual(12_000)
        expect((sample.results as (typeof series)[number][])[0]).toMatchObject({
            label: series[0].label,
            data: series[0].data.slice(0, 30),
        })
    })
})
