import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'
import { HeatmapSource, HeatmapType } from '~/types'

import { savedPartialUpdate, savedRegenerateCreate, savedRetrieve } from 'products/web_analytics/frontend/generated/api'

import { computeLockedWidth, heatmapLogic, resolveHeatmapExportUrl } from './heatmapLogic'

jest.mock('products/web_analytics/frontend/generated/api', () => ({
    ...jest.requireActual('products/web_analytics/frontend/generated/api'),
    savedRetrieve: jest.fn(),
    savedPartialUpdate: jest.fn(),
    savedRegenerateCreate: jest.fn(),
}))

describe('heatmapLogic', () => {
    let logic: ReturnType<typeof heatmapLogic.build>

    beforeEach(async () => {
        initKeaTests()
        jest.mocked(savedRetrieve).mockResolvedValue({
            id: 'a-heatmap-id',
            short_id: 'sid',
            url: 'https://example.com/pricing',
            type: 'iframe',
            status: 'completed',
        } as any)
        logic = heatmapLogic({ id: 'sid' })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
    })

    afterEach(() => {
        logic.unmount()
        jest.resetAllMocks()
    })

    it('waits for the capture method to be saved before it asks for a render', async () => {
        const order: string[] = []
        jest.mocked(savedPartialUpdate).mockImplementation(async () => {
            // The save must not resolve on the same microtask it is called on, or a caller that only
            // awaits the dispatch looks like it waited for the save.
            await Promise.resolve()
            await Promise.resolve()
            order.push('saved')
            return { url: 'https://example.com/pricing', block_consent_modals: false } as any
        })
        const rendered = new Promise<void>((resolve) => {
            jest.mocked(savedRegenerateCreate).mockImplementation(async () => {
                order.push('render requested')
                resolve()
                return {} as any
            })
        })

        logic.actions.changeCaptureMethod('screenshot')
        await rendered

        expect(order).toEqual(['saved', 'render requested'])
        expect(savedPartialUpdate).toHaveBeenCalledWith(
            expect.anything(),
            expect.anything(),
            expect.objectContaining({ type: 'screenshot' })
        )
    })
})

describe('computeLockedWidth', () => {
    it.each([
        ['toolbar', [1440], 1440],
        ['toolbar', [320, 768, 1440], null],
        ['toolbar', [], null],
        ['server', [1024], null],
    ] as const)('computeLockedWidth(%s, %j) → %s', (source, capturedWidths, expected) => {
        expect(computeLockedWidth(source as HeatmapSource, [...capturedWidths])).toBe(expected)
    })
})

describe('resolveHeatmapExportUrl', () => {
    const origin = 'https://us.posthog.com'

    it.each([
        [
            'screenshot',
            '/api/environments/1/heatmap_screenshots/42/content/?width=1400',
            'https://example.com/page',
            `${origin}/api/environments/1/heatmap_screenshots/42/content/?width=1400`,
        ],
        [
            'iframe',
            '/api/environments/1/heatmap_screenshots/42/content/',
            'https://example.com/page',
            'https://example.com/page',
        ],
        ['screenshot', null, 'https://example.com/page', ''],
        ['iframe', '/api/something', null, ''],
        [
            'screenshot',
            'https://another.posthog.com/api/environments/1/heatmap_screenshots/42/content/',
            null,
            'https://another.posthog.com/api/environments/1/heatmap_screenshots/42/content/',
        ],
    ] as const)(
        'resolveHeatmapExportUrl(%s, screenshotUrl=%s, displayUrl=%s) → %s',
        (type, screenshotUrl, displayUrl, expected) => {
            expect(resolveHeatmapExportUrl(type as HeatmapType, screenshotUrl, displayUrl, origin)).toBe(expected)
        }
    )
})
