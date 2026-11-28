import type { JourneyApi, JourneyRunStepApi } from './generated/api.schemas'
import { journeyRunStartUrl, runSummary } from './journeyRuns'

function step(index: number, changes: Partial<JourneyRunStepApi> = {}): JourneyRunStepApi {
    return {
        index,
        step: { type: 'element_click', selector: 'a' },
        status: 'passed',
        failure_reason: null,
        message: '',
        screenshot_url: null,
        baseline_screenshot_url: null,
        diff_screenshot_url: null,
        diff_percentage: null,
        visual_change: 'unchanged',
        duration_ms: 100,
        ...changes,
    }
}

const CLICK = { type: 'element_click', selector: 'button' } as const

describe('journeyRuns', () => {
    test.each<[string, Pick<JourneyApi, 'start_url' | 'steps'>, string | null]>([
        [
            'the stored start URL',
            { start_url: 'https://example.com/start', steps: [{ type: 'pageview', url: '/pricing' }, CLICK] },
            'https://example.com/start',
        ],
        [
            'a first step that is an exact pageview of a full URL',
            { start_url: null, steps: [{ type: 'pageview', url: 'https://example.com/pricing' }, CLICK] },
            'https://example.com/pricing',
        ],
        [
            'nothing for a first step that only contains a URL',
            {
                start_url: null,
                steps: [{ type: 'pageview', url: 'https://example.com/pricing', url_matching: 'contains' }, CLICK],
            },
            null,
        ],
        [
            'nothing for an exact pageview of a path',
            { start_url: '', steps: [{ type: 'pageview', url: '/pricing' }, CLICK] },
            null,
        ],
        ['nothing for a journey that starts with a click', { start_url: null, steps: [CLICK, CLICK] }, null],
    ])('a run starts from %s', (_, journey, expected) => {
        expect(journeyRunStartUrl(journey)).toBe(expected)
    })

    test.each<[string, Parameters<typeof runSummary>[0], string]>([
        ['a clean pass', { status: 'passed', steps: [step(0), step(1)] }, 'Passed'],
        [
            'a pass with one visual change',
            { status: 'passed', steps: [step(0), step(1, { visual_change: 'changed' })] },
            'Passed · 1 step looks different',
        ],
        [
            'a pass with two visual changes',
            {
                status: 'passed',
                steps: [step(0, { visual_change: 'changed' }), step(1, { visual_change: 'changed' })],
            },
            'Passed · 2 steps look different',
        ],
        [
            'a failure on a clipped element',
            {
                status: 'failed',
                steps: [
                    step(0),
                    step(1, { status: 'failed', failure_reason: 'element_not_visible' }),
                    step(2, { status: 'skipped' }),
                ],
            },
            'Failed at step 2: element not visible',
        ],
    ])('summarizes %s', (_, run, expected) => {
        expect(runSummary(run)).toBe(expected)
    })
})
