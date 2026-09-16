import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { urls } from 'scenes/urls'

import { initKeaTests } from '~/test/init'

import { mcpAnalyticsOnboardingLogic } from './mcpAnalyticsOnboardingLogic'
import { mcpAnalyticsSceneLogic } from './mcpAnalyticsSceneLogic'

jest.mock('lib/api')
jest.mock('lib/utils/product-intents', () => ({ addProductIntent: jest.fn() }))

const mockApi = api as jest.Mocked<typeof api>

describe('mcpAnalyticsSceneLogic', () => {
    let onboardingLogic: ReturnType<typeof mcpAnalyticsOnboardingLogic.build>
    let sceneLogic: ReturnType<typeof mcpAnalyticsSceneLogic.build>

    beforeEach(() => {
        jest.clearAllMocks()
        initKeaTests()
    })

    afterEach(() => {
        sceneLogic?.unmount()
        onboardingLogic?.unmount()
    })

    it.each([
        ['low volume', 1, urls.mcpAnalyticsActivity()],
        ['enough volume for metrics', 400, urls.mcpAnalyticsOverview()],
    ])(
        'resolves the automatic landing for %s after signals loaded before the scene mounted',
        async (_label, toolCallsTotal, expectedPath) => {
            jest.spyOn(mockApi, 'query').mockResolvedValue({
                results: [[1, toolCallsTotal, toolCallsTotal, '2026-07-01T00:00:00Z']],
            } as any)
            router.actions.push(urls.mcpAnalyticsOverview(), { landing: 'auto', date_from: '-7d' })

            onboardingLogic = mcpAnalyticsOnboardingLogic()
            onboardingLogic.mount()
            await expectLogic(onboardingLogic).toFinishAllListeners()

            sceneLogic = mcpAnalyticsSceneLogic()
            sceneLogic.mount()

            expect(router.values.location.pathname.endsWith(expectedPath)).toBe(true)
            expect(router.values.searchParams).toEqual({ date_from: '-7d' })
        }
    )

    it('keeps the automatic landing unresolved until the first tool call arrives', async () => {
        jest.spyOn(mockApi, 'query').mockResolvedValue({
            results: [[1, 0, 0, '1970-01-01T00:00:00Z']],
        } as any)
        router.actions.push(urls.mcpAnalyticsOverview(), { landing: 'auto', date_from: '-7d' })

        onboardingLogic = mcpAnalyticsOnboardingLogic()
        onboardingLogic.mount()
        await expectLogic(onboardingLogic).toFinishAllListeners()
        sceneLogic = mcpAnalyticsSceneLogic()
        sceneLogic.mount()

        expect(router.values.location.pathname.endsWith(urls.mcpAnalyticsOverview())).toBe(true)
        expect(router.values.searchParams).toEqual({ landing: 'auto', date_from: '-7d' })

        jest.spyOn(mockApi, 'query').mockResolvedValue({
            results: [[1, 1, 1, '2026-07-01T00:00:00Z']],
        } as any)
        await expectLogic(onboardingLogic, () => onboardingLogic.actions.loadSignals()).toFinishAllListeners()

        expect(router.values.location.pathname.endsWith(urls.mcpAnalyticsActivity())).toBe(true)
        expect(router.values.searchParams).toEqual({ date_from: '-7d' })
    })
})
