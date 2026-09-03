import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { initKeaTests } from '~/test/init'

import {
    webAnalyticsContentAutopilotProfilesCreate,
    webAnalyticsContentAutopilotProfilesDiscover,
    webAnalyticsContentAutopilotProfilesList,
    webAnalyticsContentAutopilotProfilesPartialUpdate,
    webAnalyticsContentAutopilotProposalsEdit,
    webAnalyticsContentAutopilotProposalsExport,
    webAnalyticsContentAutopilotProposalsList,
    webAnalyticsContentAutopilotProposalsRegenerate,
    webAnalyticsContentAutopilotProposalsReject,
    webAnalyticsContentAutopilotProposalsRetrieve,
    webAnalyticsContentAutopilotRunsCancel,
    webAnalyticsContentAutopilotRunsList,
    webAnalyticsContentAutopilotRunsStart,
} from '../generated/api'
import type { ContentAutopilotProposalListApi, ContentAutopilotRunApi } from '../generated/api.schemas'
import { contentAutopilotLogic } from './contentAutopilotLogic'
import {
    EXAMPLE_PROFILE,
    EXAMPLE_PROPOSAL,
    EXAMPLE_PROPOSAL_LIST,
    EXAMPLE_RUN,
    EXAMPLE_SECOND_PROFILE,
} from './contentAutopilotStoryFixtures'

jest.mock('../generated/api', () => ({
    webAnalyticsContentAutopilotProfilesCreate: jest.fn(),
    webAnalyticsContentAutopilotProfilesDiscover: jest.fn(),
    webAnalyticsContentAutopilotProfilesList: jest.fn(),
    webAnalyticsContentAutopilotProfilesPartialUpdate: jest.fn(),
    webAnalyticsContentAutopilotProposalsEdit: jest.fn(),
    webAnalyticsContentAutopilotProposalsExport: jest.fn(),
    webAnalyticsContentAutopilotProposalsList: jest.fn(),
    webAnalyticsContentAutopilotProposalsRegenerate: jest.fn(),
    webAnalyticsContentAutopilotProposalsReject: jest.fn(),
    webAnalyticsContentAutopilotProposalsRetrieve: jest.fn(),
    webAnalyticsContentAutopilotRunsCancel: jest.fn(),
    webAnalyticsContentAutopilotRunsList: jest.fn(),
    webAnalyticsContentAutopilotRunsStart: jest.fn(),
}))

jest.mock('lib/components/ExportButton/exporter', () => ({ downloadBlob: jest.fn() }))
jest.mock('lib/lemon-ui/LemonToast/LemonToast', () => ({
    lemonToast: { success: jest.fn(), error: jest.fn() },
}))

const mockProfilesCreate = jest.mocked(webAnalyticsContentAutopilotProfilesCreate)
const mockProfilesList = jest.mocked(webAnalyticsContentAutopilotProfilesList)
const mockProposalsEdit = jest.mocked(webAnalyticsContentAutopilotProposalsEdit)
const mockProposalsList = jest.mocked(webAnalyticsContentAutopilotProposalsList)
const mockProposalsRetrieve = jest.mocked(webAnalyticsContentAutopilotProposalsRetrieve)
const mockRunsList = jest.mocked(webAnalyticsContentAutopilotRunsList)
const mockRunsStart = jest.mocked(webAnalyticsContentAutopilotRunsStart)

const paginated = <T>(results: T[]): { count: number; next: null; previous: null; results: T[] } => ({
    count: results.length,
    next: null,
    previous: null,
    results,
})

const deferred = <T>(): { promise: Promise<T>; resolve: (value: T) => void } => {
    let resolve!: (value: T) => void
    const promise = new Promise<T>((resolvePromise) => {
        resolve = resolvePromise
    })
    return { promise, resolve }
}

describe('contentAutopilotLogic', () => {
    let logic: ReturnType<typeof contentAutopilotLogic.build> | null

    beforeEach(() => {
        jest.clearAllMocks()
        initKeaTests()
        logic = null

        mockProfilesList.mockResolvedValue(paginated([EXAMPLE_PROFILE]))
        mockRunsList.mockResolvedValue(paginated([EXAMPLE_RUN]))
        mockProposalsList.mockResolvedValue(paginated([EXAMPLE_PROPOSAL_LIST]))
        mockProposalsRetrieve.mockResolvedValue(EXAMPLE_PROPOSAL)
        mockRunsStart.mockResolvedValue({ ...EXAMPLE_RUN, run_status: 'pending' })
        mockProfilesCreate.mockResolvedValue(EXAMPLE_SECOND_PROFILE)
        jest.mocked(webAnalyticsContentAutopilotProfilesDiscover).mockResolvedValue({
            name: EXAMPLE_PROFILE.name ?? '',
            domain: EXAMPLE_PROFILE.domain,
            source_urls: EXAMPLE_PROFILE.source_urls,
            content_boundaries: EXAMPLE_PROFILE.content_boundaries,
            sitemap_detected: true,
            warnings: [],
        })
        jest.mocked(webAnalyticsContentAutopilotProfilesPartialUpdate).mockResolvedValue(EXAMPLE_PROFILE)
        mockProposalsEdit.mockResolvedValue(EXAMPLE_PROPOSAL)
        jest.mocked(webAnalyticsContentAutopilotProposalsExport).mockResolvedValue({
            filename: 'web-analytics.mdx',
            markdown: EXAMPLE_PROPOSAL.proposed_markdown,
            content_package: EXAMPLE_PROPOSAL.content_package,
        })
        jest.mocked(webAnalyticsContentAutopilotProposalsRegenerate).mockResolvedValue(EXAMPLE_PROPOSAL)
        jest.mocked(webAnalyticsContentAutopilotProposalsReject).mockResolvedValue(EXAMPLE_PROPOSAL)
        jest.mocked(webAnalyticsContentAutopilotRunsCancel).mockResolvedValue(EXAMPLE_RUN)
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

    it('sends typed run and profile payloads to the generated API clients', async () => {
        const mountedLogic = await mountWorkspace()
        const projectId = String(MOCK_DEFAULT_TEAM.id)

        expect(mockProfilesList).toHaveBeenCalledWith(projectId, { limit: 100 })
        expect(mockRunsList).toHaveBeenCalledWith(projectId, { limit: 100, profile_id: EXAMPLE_PROFILE.id })
        expect(mockProposalsList).toHaveBeenCalledWith(projectId, { limit: 100, profile_id: EXAMPLE_PROFILE.id })

        await expectLogic(mountedLogic, () => mountedLogic.actions.startRun()).toFinishAllListeners()

        expect(mockRunsStart).toHaveBeenCalledWith(projectId, { profile_id: EXAMPLE_PROFILE.id })

        mountedLogic.actions.beginOnboarding()
        mountedLogic.actions.setProfileDraft({
            name: 'Example blog',
            domain: 'https://blog.example.com',
            sourceUrls: 'https://blog.example.com/sitemap.xml',
            contentBoundaries: '/blog',
            brandRules: 'Use sentence case',
            searchConsoleEnabled: false,
        })

        await expectLogic(mountedLogic, () => mountedLogic.actions.saveProfile()).toFinishAllListeners()

        expect(mockProfilesCreate).toHaveBeenCalledWith(projectId, {
            name: 'Example blog',
            domain: 'https://blog.example.com',
            source_urls: ['https://blog.example.com/sitemap.xml'],
            content_boundaries: ['/blog'],
            brand_rules: ['Use sentence case'],
            search_console_enabled: false,
        })
    })

    it('switches profiles and resets profile-specific review state', async () => {
        mockProfilesList.mockResolvedValue(paginated([EXAMPLE_PROFILE, EXAMPLE_SECOND_PROFILE]))
        const mountedLogic = await mountWorkspace()
        mountedLogic.actions.selectProposal(EXAMPLE_PROPOSAL.id)

        await expectLogic(mountedLogic, () =>
            mountedLogic.actions.selectProfile(EXAMPLE_SECOND_PROFILE.id)
        ).toFinishAllListeners()

        expect(mountedLogic.values.profile?.id).toBe(EXAMPLE_SECOND_PROFILE.id)
        expect(mountedLogic.values.profileDraft.domain).toBe(EXAMPLE_SECOND_PROFILE.domain)
        expect(mountedLogic.values.selectedProposal).toBeNull()
        expect(mockRunsList).toHaveBeenLastCalledWith(String(MOCK_DEFAULT_TEAM.id), {
            limit: 100,
            profile_id: EXAMPLE_SECOND_PROFILE.id,
        })
        expect(mockProposalsList).toHaveBeenLastCalledWith(String(MOCK_DEFAULT_TEAM.id), {
            limit: 100,
            profile_id: EXAMPLE_SECOND_PROFILE.id,
        })
    })

    it('ignores stale profile data when requests finish out of order', async () => {
        mockProfilesList.mockResolvedValue(paginated([EXAMPLE_PROFILE, EXAMPLE_SECOND_PROFILE]))
        const mountedLogic = await mountWorkspace()
        const firstRunRequest = deferred<ReturnType<typeof paginated<ContentAutopilotRunApi>>>()
        const secondRunRequest = deferred<ReturnType<typeof paginated<ContentAutopilotRunApi>>>()
        const secondRun = { ...EXAMPLE_RUN, id: '00000000-0000-4000-8000-000000000302' }
        mockRunsList
            .mockImplementationOnce(() => firstRunRequest.promise)
            .mockImplementationOnce(() => secondRunRequest.promise)

        mountedLogic.actions.selectProfile(EXAMPLE_PROFILE.id)
        mountedLogic.actions.selectProfile(EXAMPLE_SECOND_PROFILE.id)
        secondRunRequest.resolve(paginated([secondRun]))
        firstRunRequest.resolve(paginated([EXAMPLE_RUN]))
        await expectLogic(mountedLogic).toFinishAllListeners()

        expect(mountedLogic.values.profile?.id).toBe(EXAMPLE_SECOND_PROFILE.id)
        expect(mountedLogic.values.runs).toEqual([secondRun])
    })

    it('groups the proposals returned for the selected site', async () => {
        const newContent: ContentAutopilotProposalListApi = {
            ...EXAMPLE_PROPOSAL_LIST,
            id: '00000000-0000-4000-8000-000000000202',
            proposal_type: 'new_content',
        }
        mockProposalsList.mockResolvedValue(paginated([EXAMPLE_PROPOSAL_LIST, newContent]))

        const mountedLogic = await mountWorkspace()

        expect(mountedLogic.values.siteProposals.map(({ id }) => id)).toEqual([EXAMPLE_PROPOSAL_LIST.id, newContent.id])
        expect(mountedLogic.values.newContentProposals.map(({ id }) => id)).toEqual([newContent.id])
        expect(mountedLogic.values.pageImprovementProposals.map(({ id }) => id)).toEqual([EXAMPLE_PROPOSAL_LIST.id])
    })

    it('polls while work is active and stops refreshing after it settles', async () => {
        let pollWorkspace: (() => void) | undefined
        const setIntervalSpy = jest
            .spyOn(window, 'setInterval')
            .mockImplementation((handler: Parameters<typeof window.setInterval>[0]) => {
                pollWorkspace = handler as () => void
                return 1
            })
        mockRunsList.mockResolvedValueOnce(paginated([{ ...EXAMPLE_RUN, run_status: 'generating' }]))
        const mountedLogic = await mountWorkspace()
        mockRunsList.mockClear()
        mockProposalsList.mockClear()
        let resolveRuns: ((value: ReturnType<typeof paginated<ContentAutopilotRunApi>>) => void) | undefined
        mockRunsList.mockImplementationOnce(
            () =>
                new Promise((resolve) => {
                    resolveRuns = resolve
                })
        )

        const pollExpectation = expectLogic(mountedLogic, () => pollWorkspace?.()).toFinishAllListeners()

        expect(mockRunsList).toHaveBeenCalledTimes(1)
        expect(mockProposalsList).toHaveBeenCalledTimes(1)
        pollWorkspace?.()
        await Promise.resolve()
        expect(mockRunsList).toHaveBeenCalledTimes(1)
        expect(mockProposalsList).toHaveBeenCalledTimes(1)

        resolveRuns?.(paginated([EXAMPLE_RUN]))
        await pollExpectation
        expect(mountedLogic.values.activeRun).toBeNull()

        mockRunsList.mockClear()
        mockProposalsList.mockClear()
        pollWorkspace?.()
        await Promise.resolve()

        expect(mockRunsList).not.toHaveBeenCalled()
        expect(mockProposalsList).not.toHaveBeenCalled()
        setIntervalSpy.mockRestore()
    })

    it('refreshes proposals after edits and pull-request delivery', async () => {
        const mountedLogic = await mountWorkspace()
        mockProposalsList.mockClear()

        await expectLogic(mountedLogic, () =>
            mountedLogic.actions.selectProposal(EXAMPLE_PROPOSAL.id)
        ).toFinishAllListeners()
        mountedLogic.actions.setProposedMarkdown('# Reviewed web analytics guide')
        expect(mountedLogic.values.proposalHasUnsavedChanges).toBe(true)
        await expectLogic(mountedLogic, () =>
            mountedLogic.actions.saveProposal(EXAMPLE_PROPOSAL.id)
        ).toFinishAllListeners()

        expect(mockProposalsEdit).toHaveBeenCalledWith(String(MOCK_DEFAULT_TEAM.id), EXAMPLE_PROPOSAL.id, {
            proposed_markdown: '# Reviewed web analytics guide',
            content_package: EXAMPLE_PROPOSAL.content_package,
        })
        expect(mockProposalsList).toHaveBeenCalledTimes(1)
        expect(mountedLogic.values.selectedProposalId).toBeNull()
    })

    it('does not deliver Markdown that has not been saved', async () => {
        const mountedLogic = await mountWorkspace()
        await expectLogic(mountedLogic, () =>
            mountedLogic.actions.selectProposal(EXAMPLE_PROPOSAL.id)
        ).toFinishAllListeners()
        mountedLogic.actions.setProposedMarkdown('# Unsaved draft')
        silenceKeaLoadersErrors()

        await expectLogic(mountedLogic, () =>
            mountedLogic.actions.exportProposal(EXAMPLE_PROPOSAL.id)
        ).toFinishAllListeners()
        resumeKeaLoadersErrors()

        expect(webAnalyticsContentAutopilotProposalsExport).not.toHaveBeenCalled()
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
