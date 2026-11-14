import { initKeaTests } from '~/test/init'

import { surveysSiteSnapshotRetrieve } from 'products/surveys/frontend/generated/api'
import type { SiteSnapshotApi } from 'products/surveys/frontend/generated/api.schemas'

import { surveySiteSnapshotLogic } from './surveySiteSnapshotLogic'

jest.mock('products/surveys/frontend/generated/api', () => ({
    ...jest.requireActual('products/surveys/frontend/generated/api'),
    surveysSiteSnapshotRetrieve: jest.fn(),
}))

const mockRetrieve = surveysSiteSnapshotRetrieve as jest.MockedFunction<typeof surveysSiteSnapshotRetrieve>

const RENDERING: SiteSnapshotApi = {
    status: 'rendering',
    exported_asset_id: 7,
    page_url: 'https://example.com/pricing',
    viewport_width: 1440,
    site_style: null,
}

describe('surveySiteSnapshotLogic', () => {
    beforeEach(() => {
        jest.useFakeTimers()
        initKeaTests()
    })

    afterEach(() => {
        jest.useRealTimers()
    })

    it.each([
        ['a render that never finishes', () => mockRetrieve.mockResolvedValue(RENDERING)],
        ['a request that keeps failing', () => mockRetrieve.mockRejectedValue(new Error('offline'))],
    ])('gives up on %s', async (_name, mockResponse) => {
        mockResponse()
        const logic = surveySiteSnapshotLogic({ surveyId: 'survey-id', device: 'desktop', urlCondition: ':' })
        logic.mount()

        for (let minute = 0; minute <= 6 && !logic.values.gaveUp; minute++) {
            await jest.advanceTimersByTimeAsync(60_000)
        }

        expect(logic.values.gaveUp).toBe(true)
        logic.unmount()
    })
})
