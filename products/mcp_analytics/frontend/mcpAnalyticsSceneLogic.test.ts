import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { urls } from 'scenes/urls'

import { initKeaTests } from '~/test/init'

import { mcpAnalyticsFiltersLogic } from './mcpAnalyticsFiltersLogic'
import { mcpAnalyticsOnboardingLogic } from './mcpAnalyticsOnboardingLogic'
import { mcpAnalyticsSceneLogic } from './mcpAnalyticsSceneLogic'
import { mcpAnalyticsToolDetailLogic } from './mcpAnalyticsToolDetailLogic'
import { mcpFacetsLogic } from './mcpFacetsLogic'
import { mcpToolDetailSceneLogic } from './mcpToolDetailSceneLogic'

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

    // Both UIs share these scene logics, so a data logic mounted here would run the redesign's queries with the flag off.
    it.each([
        ['the tabs scene', () => mcpAnalyticsSceneLogic()],
        ['the tool scene', () => mcpToolDetailSceneLogic({ toolName: 'search_docs' })],
    ])('%s mounts none of the redesign data logics', (_label, build) => {
        jest.spyOn(mockApi, 'query').mockResolvedValue({ results: [] } as any)
        const unmount = build().mount()

        expect(mcpAnalyticsFiltersLogic.isMounted()).toBe(false)
        expect(mcpFacetsLogic.isMounted()).toBe(false)
        expect(mcpAnalyticsToolDetailLogic.findMounted({ toolName: 'search_docs' })).toBeNull()
        unmount()
    })

    it('resolves a low-volume automatic landing after signals loaded before the scene mounted', async () => {
        jest.spyOn(mockApi, 'query').mockResolvedValue({
            results: [[1, 1, 1, '2026-07-01T00:00:00Z']],
        } as any)
        router.actions.push(urls.mcpAnalyticsDashboard(), { landing: 'auto', date_from: '-7d' })

        onboardingLogic = mcpAnalyticsOnboardingLogic()
        onboardingLogic.mount()
        await expectLogic(onboardingLogic).toFinishAllListeners()

        sceneLogic = mcpAnalyticsSceneLogic()
        sceneLogic.mount()

        expect(router.values.location.pathname.endsWith(urls.mcpAnalyticsActivity())).toBe(true)
        expect(router.values.searchParams).toEqual({ date_from: '-7d' })
    })

    it('keeps the automatic landing unresolved until the first tool call arrives', async () => {
        jest.spyOn(mockApi, 'query').mockResolvedValue({
            results: [[1, 0, 0, '1970-01-01T00:00:00Z']],
        } as any)
        router.actions.push(urls.mcpAnalyticsDashboard(), { landing: 'auto', date_from: '-7d' })

        onboardingLogic = mcpAnalyticsOnboardingLogic()
        onboardingLogic.mount()
        await expectLogic(onboardingLogic).toFinishAllListeners()
        sceneLogic = mcpAnalyticsSceneLogic()
        sceneLogic.mount()

        expect(router.values.location.pathname.endsWith(urls.mcpAnalyticsDashboard())).toBe(true)
        expect(router.values.searchParams).toEqual({ landing: 'auto', date_from: '-7d' })

        jest.spyOn(mockApi, 'query').mockResolvedValue({
            results: [[1, 1, 1, '2026-07-01T00:00:00Z']],
        } as any)
        await expectLogic(onboardingLogic, () => onboardingLogic.actions.loadSignals()).toFinishAllListeners()

        expect(router.values.location.pathname.endsWith(urls.mcpAnalyticsActivity())).toBe(true)
        expect(router.values.searchParams).toEqual({ date_from: '-7d' })
    })
})
