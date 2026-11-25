import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { initKeaTests } from '~/test/init'

import {
    webAnalyticsContentAutopilotProfilesCreate,
    webAnalyticsContentAutopilotProfilesDestroy,
    webAnalyticsContentAutopilotProfilesDiscover,
    webAnalyticsContentAutopilotProfilesList,
    webAnalyticsContentAutopilotProfilesPartialUpdate,
} from '../generated/api'
import { contentAutopilotLogic } from './contentAutopilotLogic'
import { EXAMPLE_PROFILE, EXAMPLE_SECOND_PROFILE } from './contentAutopilotStoryFixtures'

jest.mock('../generated/api', () => ({
    webAnalyticsContentAutopilotProfilesCreate: jest.fn(),
    webAnalyticsContentAutopilotProfilesDestroy: jest.fn(),
    webAnalyticsContentAutopilotProfilesDiscover: jest.fn(),
    webAnalyticsContentAutopilotProfilesList: jest.fn(),
    webAnalyticsContentAutopilotProfilesPartialUpdate: jest.fn(),
}))

jest.mock('lib/lemon-ui/LemonToast/LemonToast', () => ({
    lemonToast: { success: jest.fn(), error: jest.fn() },
}))

const mockProfilesCreate = jest.mocked(webAnalyticsContentAutopilotProfilesCreate)
const mockProfilesDestroy = jest.mocked(webAnalyticsContentAutopilotProfilesDestroy)
const mockProfilesList = jest.mocked(webAnalyticsContentAutopilotProfilesList)

const paginated = <T>(results: T[]): { count: number; next: null; previous: null; results: T[] } => ({
    count: results.length,
    next: null,
    previous: null,
    results,
})

describe('contentAutopilotLogic', () => {
    let logic: ReturnType<typeof contentAutopilotLogic.build> | null

    beforeEach(() => {
        jest.clearAllMocks()
        initKeaTests()
        logic = null

        mockProfilesList.mockResolvedValue(paginated([EXAMPLE_PROFILE]))
        mockProfilesCreate.mockResolvedValue(EXAMPLE_SECOND_PROFILE)
        mockProfilesDestroy.mockResolvedValue(undefined)
        jest.mocked(webAnalyticsContentAutopilotProfilesDiscover).mockResolvedValue({
            name: EXAMPLE_PROFILE.name ?? '',
            domain: EXAMPLE_PROFILE.domain,
            source_urls: EXAMPLE_PROFILE.source_urls,
            content_boundaries: EXAMPLE_PROFILE.content_boundaries,
            sitemap_detected: true,
            warnings: [],
        })
        jest.mocked(webAnalyticsContentAutopilotProfilesPartialUpdate).mockResolvedValue(EXAMPLE_PROFILE)
    })

    afterEach(() => {
        logic?.unmount()
    })

    const mountWorkspace = async (): Promise<ReturnType<typeof contentAutopilotLogic.build>> => {
        logic = contentAutopilotLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        return logic
    }

    it('sends typed profile payloads to the generated API clients', async () => {
        const mountedLogic = await mountWorkspace()
        const projectId = String(MOCK_DEFAULT_TEAM.id)

        expect(mockProfilesList).toHaveBeenCalledWith(projectId, { limit: 100, offset: 0 })

        mountedLogic.actions.beginOnboarding()
        mountedLogic.actions.setProfileDraft({
            name: 'Example blog',
            domain: 'https://blog.example.com',
            sourceUrls: 'https://blog.example.com/sitemap.xml',
            contentBoundaries: '/blog',
            brandRules: 'Use sentence case',
        })

        await expectLogic(mountedLogic, () => mountedLogic.actions.saveProfile()).toFinishAllListeners()

        expect(mockProfilesCreate).toHaveBeenCalledWith(projectId, {
            name: 'Example blog',
            domain: 'https://blog.example.com',
            source_urls: ['https://blog.example.com/sitemap.xml'],
            content_boundaries: ['/blog'],
            brand_rules: ['Use sentence case'],
        })
    })

    it('switches profiles and resets the profile draft', async () => {
        mockProfilesList.mockResolvedValue(paginated([EXAMPLE_PROFILE, EXAMPLE_SECOND_PROFILE]))
        const mountedLogic = await mountWorkspace()

        await expectLogic(mountedLogic, () =>
            mountedLogic.actions.selectProfile(EXAMPLE_SECOND_PROFILE.id)
        ).toFinishAllListeners()

        expect(mountedLogic.values.profile?.id).toBe(EXAMPLE_SECOND_PROFILE.id)
        expect(mountedLogic.values.profileDraft.domain).toBe(EXAMPLE_SECOND_PROFILE.domain)
    })

    it('returns to onboarding once the last site is deleted', async () => {
        const mountedLogic = await mountWorkspace()
        mockProfilesList.mockResolvedValue(paginated([]))

        await expectLogic(mountedLogic, () =>
            mountedLogic.actions.deleteProfile(EXAMPLE_PROFILE.id)
        ).toFinishAllListeners()

        expect(mockProfilesDestroy).toHaveBeenCalledWith(String(MOCK_DEFAULT_TEAM.id), EXAMPLE_PROFILE.id)
        expect(mountedLogic.values.siteProfiles).toEqual([])
        expect(mountedLogic.values.profile).toBeNull()
        expect(mountedLogic.values.onboardingOpen).toBe(true)
    })

    it('keeps load failures distinct from an empty workspace and clears them on retry', async () => {
        mockProfilesList.mockRejectedValueOnce({ detail: 'Site profiles are temporarily unavailable.' })
        silenceKeaLoadersErrors()
        const mountedLogic = await mountWorkspace()
        resumeKeaLoadersErrors()

        expect(mountedLogic.values.workspaceInitialized).toBe(true)
        expect(mountedLogic.values.workspaceError).toBe('Site profiles are temporarily unavailable.')
        expect(mountedLogic.values.siteProfiles).toEqual([])

        mockProfilesList.mockResolvedValue(paginated([EXAMPLE_PROFILE]))
        await expectLogic(mountedLogic, () => mountedLogic.actions.loadWorkspace()).toFinishAllListeners()

        expect(mountedLogic.values.workspaceError).toBeNull()
        expect(mountedLogic.values.profile?.id).toBe(EXAMPLE_PROFILE.id)
    })
})
