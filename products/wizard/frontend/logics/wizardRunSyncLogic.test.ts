import { MOCK_DEFAULT_USER } from 'lib/api.mock'
import { installMockEventSource, MockEventSource } from 'lib/wizard-sync/eventSource.mock'

import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { wizardRunsList, wizardRunsRetrieve, wizardRunsTasksRetrieve } from '../generated/api'
import type {
    WizardRunApi,
    WizardRunArtifactApi,
    WizardRunTaskApi,
    WizardRunTaskListApi,
} from '../generated/api.schemas'
import { loadWizardRunArtifacts } from '../lib/wizardApi'
import { wizardRunSyncLogic } from './wizardRunSyncLogic'

jest.mock('../generated/api', () => ({
    wizardRunsList: jest.fn(),
    wizardRunsRetrieve: jest.fn(),
    wizardRunsTasksRetrieve: jest.fn().mockResolvedValue({ tasks: [] }),
    getWizardRunsStreamRetrieveUrl: (projectId: string, runId: string) =>
        `/api/projects/${projectId}/wizard/runs/${runId}/stream/`,
}))

jest.mock('../lib/wizardApi', () => ({
    loadWizardRunArtifacts: jest.fn().mockResolvedValue([]),
}))

const mockWizardRunsList = wizardRunsList as jest.Mock

function mockRunPages(activePage: { count: number; results: WizardRunApi[] }, recentRuns: WizardRunApi[] = []): void {
    const results = [
        ...activePage.results,
        ...recentRuns.filter((recent) => !activePage.results.some((active) => active.id === recent.id)),
    ]
    mockWizardRunsList.mockResolvedValue({ count: results.length, results })
}

function run(id: string): WizardRunApi {
    return {
        id,
        team_id: 1,
        status: 'running',
        stage: 'executing_wizard',
        created_by_id: MOCK_DEFAULT_USER.id,
        created_at: '2026-09-23T10:00:00Z',
        updated_at: '2026-09-23T10:01:00Z',
    } as WizardRunApi
}

describe('wizardRunSyncLogic', () => {
    let restoreEventSource: () => void
    let logic: ReturnType<typeof wizardRunSyncLogic.build>

    beforeEach(() => {
        initKeaTests()
        restoreEventSource = installMockEventSource()
        mockWizardRunsList.mockReset()
        mockRunPages({ count: 2, results: [run('newer')] })
        logic = wizardRunSyncLogic({ projectId: '1' })
        logic.mount()
        logic.actions.watchRuns('test', ['newer'])
    })

    afterEach(() => {
        logic.unmount()
        restoreEventSource()
        jest.restoreAllMocks()
        jest.useRealTimers()
    })

    it('streams the active run and switches when it changes', async () => {
        await expectLogic(logic).toFinishAllListeners()

        expect(mockWizardRunsList).toHaveBeenCalledWith('1', {
            limit: 100,
            offset: 0,
        })
        expect(logic.values.userRuns[0]?.id).toBe('newer')
        expect(MockEventSource.instances).toHaveLength(1)

        const firstStream = MockEventSource.last()
        firstStream.emitMessage(
            JSON.stringify({
                status: 'running',
                stage: 'executing_wizard',
                tasks: [{ name: 'Install SDK', status: 'running' }],
            })
        )
        expect(logic.values.tasksByRunId.newer).toEqual([{ name: 'Install SDK', status: 'running' }])

        mockRunPages({ count: 1, results: [run('older')] })
        logic.actions.watchRuns('test', ['older'])
        logic.actions.checkRuns()
        await expectLogic(logic).toFinishAllListeners()

        expect(firstStream.readyState).toBe(MockEventSource.CLOSED)
        expect(MockEventSource.instances).toHaveLength(2)
        expect(MockEventSource.last().url).toBe('/api/projects/1/wizard/runs/older/stream/')
        expect(logic.values.tasksByRunId.older).toBeUndefined()
    })

    it('caps streams and polls the remaining watched runs without mixing their tasks', async () => {
        await expectLogic(logic).toFinishAllListeners()
        const older = run('older')
        mockRunPages({ count: 2, results: [run('newer'), older] }, [run('newer'), older])
        logic.actions.checkRuns()
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.watchRuns('test', ['newer', 'older'])

        expect(logic.values.activeUserRuns.map((activeRun) => activeRun.id)).toEqual(['newer', 'older'])
        expect(MockEventSource.instances).toHaveLength(1)
        jest.mocked(wizardRunsRetrieve).mockResolvedValueOnce(run('newer')).mockResolvedValueOnce(older)
        jest.mocked(wizardRunsTasksRetrieve)
            .mockResolvedValueOnce({ tasks: [] })
            .mockResolvedValueOnce({ tasks: [{ name: 'Add events', status: 'running' } as WizardRunTaskApi] })
        logic.actions.refreshWatchedRun()
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.refreshWatchedRun()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.tasksByRunId.older).toEqual([{ name: 'Add events', status: 'running' }])
        expect(logic.values.runs.find((r) => r.id === 'older')?.status).toBe('running')
        expect(logic.values.tasksByRunId.newer).toEqual([])
    })

    it.each(['completed', 'failed', 'cancelled'] as const)(
        'loads %s runs after reloading and switches to the next active run',
        async (status) => {
            await expectLogic(logic).toFinishAllListeners()
            const stream = MockEventSource.last()
            const terminal = { ...run('newer'), status, stage: null }
            mockRunPages({ count: 0, results: [] }, [terminal])

            stream.emitMessage(JSON.stringify({ status, stage: null, tasks: [] }))
            await expectLogic(logic).toFinishAllListeners()
            expect(logic.values.userRuns[0]?.status).toBe(status)
            expect(stream.readyState).toBe(MockEventSource.CLOSED)

            logic.unmount()
            logic = wizardRunSyncLogic({ projectId: '1' })
            logic.mount()
            logic.actions.watchRuns('test', ['next'])
            await expectLogic(logic).toFinishAllListeners()
            expect(mockWizardRunsList).toHaveBeenCalledWith('1', {
                limit: 100,
                offset: 0,
            })
            expect(logic.values.userRuns).toEqual([terminal])
            expect(MockEventSource.instances).toHaveLength(1)

            mockRunPages({ count: 1, results: [run('next')] }, [terminal])
            logic.actions.checkRuns()
            await expectLogic(logic).toFinishAllListeners()
            expect(logic.values.userRuns[0]?.id).toBe('next')
            expect(MockEventSource.instances).toHaveLength(2)
        }
    )

    it('ignores runs created by other users', async () => {
        await expectLogic(logic).toFinishAllListeners()
        const initialStream = MockEventSource.last()
        const otherUserRun = { ...run('other-user'), created_by_id: MOCK_DEFAULT_USER.id + 1 }
        mockRunPages({ count: 1, results: [otherUserRun] })
        logic.actions.checkRuns()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.userRuns).toEqual([])
        expect(logic.values.activeUserRuns).toEqual([])
        expect(initialStream.readyState).toBe(MockEventSource.CLOSED)
    })

    it('keeps a completed run in the list', async () => {
        await expectLogic(logic).toFinishAllListeners()
        const completed = { ...run('newer'), status: 'completed' as const, stage: null }
        mockRunPages({ count: 1, results: [completed] })
        logic.actions.checkRuns()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.runs).toEqual([completed])
        expect(logic.values.userRuns[0]?.status).toBe('completed')
        expect(MockEventSource.last().readyState).toBe(MockEventSource.CLOSED)
    })

    it('loads history once and bounds recurring requests to the recent page', async () => {
        await expectLogic(logic).toFinishAllListeners()
        logic.unmount()
        jest.useFakeTimers()
        logic = wizardRunSyncLogic({ projectId: '1' })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        mockWizardRunsList
            .mockResolvedValueOnce({ results: [run('first')], next: '/next' })
            .mockResolvedValueOnce({ results: [run('second')], next: null })
        logic.actions.checkRuns()
        await expectLogic(logic).toFinishAllListeners()
        expect(mockWizardRunsList).toHaveBeenLastCalledWith('1', { limit: 100, offset: 100 })
        expect(logic.values.userRuns.map((run) => run.id)).toEqual(['first', 'second'])
        const previousCalls = mockWizardRunsList.mock.calls.length
        mockWizardRunsList.mockResolvedValue({ results: [run('first')], next: '/next' })
        for (let poll = 0; poll < 6; poll++) {
            jest.advanceTimersByTime(5_000)
            await expectLogic(logic).toFinishAllListeners()
        }
        expect(mockWizardRunsList.mock.calls.length - previousCalls).toBe(6)
        expect(mockWizardRunsList).toHaveBeenLastCalledWith('1', { limit: 100, offset: 0 })
        expect(logic.values.userRuns.map((run) => run.id)).toEqual(['first', 'second'])
    })

    it.each(['poll', 'focus'])(
        'discovers local runs promptly on %s without dropping older history',
        async (trigger) => {
            await expectLogic(logic).toFinishAllListeners()
            logic.unmount()
            jest.useFakeTimers()
            logic = wizardRunSyncLogic({ projectId: '1' })
            logic.mount()
            logic.actions.watchRuns('test', ['local-installation'])
            await expectLogic(logic).toFinishAllListeners()
            const history = { ...run('history'), status: 'completed' as const }
            logic.actions.runsLoaded([run('newer'), history])
            const localRun = { ...run('local-installation'), environment: 'local' as const }
            mockWizardRunsList.mockResolvedValue({ results: [localRun], next: '/older-runs' })
            const previousCalls = mockWizardRunsList.mock.calls.length

            if (trigger === 'poll') {
                jest.advanceTimersByTime(5_000)
            } else {
                window.dispatchEvent(new Event('focus'))
            }
            await expectLogic(logic).toFinishAllListeners()
            expect(mockWizardRunsList.mock.calls.length - previousCalls).toBe(1)
            expect(logic.values.userRuns.map((run) => run.id)).toEqual(['local-installation', 'newer', 'history'])
            expect(MockEventSource.last().url).toBe('/api/projects/1/wizard/runs/local-installation/stream/')
        }
    )

    it('keeps a new creation response when an older full-history poll finishes afterward', async () => {
        await expectLogic(logic).toFinishAllListeners()
        let resolvePoll!: (page: { results: WizardRunApi[]; next: null }) => void
        mockWizardRunsList.mockReturnValueOnce(
            new Promise((resolve) => {
                resolvePoll = resolve
            })
        )
        logic.actions.checkRuns()
        const createdRun = run('created-in-library')
        logic.actions.runsLoaded([createdRun], true)
        expect(logic.values.userRuns.map((run) => run.id)).toContain(createdRun.id)

        resolvePoll({ results: [run('newer')], next: null })
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.userRuns.map((run) => run.id)).toEqual([createdRun.id, 'newer'])
    })

    it.each([MOCK_DEFAULT_USER.id, MOCK_DEFAULT_USER.id + 1])(
        'restores terminal tasks for project member %s and retries a failed request',
        async (createdById) => {
            await expectLogic(logic).toFinishAllListeners()
            const completed = { ...run('newer'), created_by_id: createdById, status: 'completed' as const }
            logic.actions.runsLoaded([completed])
            jest.mocked(wizardRunsTasksRetrieve).mockRejectedValueOnce(new Error('unavailable'))
            logic.actions.loadRunData(completed)
            await expectLogic(logic).toFinishAllListeners()
            expect(logic.values.runDataErrors.newer).toBeTruthy()

            const tasks: WizardRunTaskApi[] = [
                {
                    name: 'Install SDK',
                    status: 'completed',
                    created_at: '2026-09-23T10:00:00Z',
                    started_at: null,
                    completed_at: null,
                    failed_at: null,
                    error_message: null,
                },
            ]
            jest.mocked(wizardRunsTasksRetrieve).mockResolvedValueOnce({ tasks })
            logic.actions.loadRunData(completed)
            await expectLogic(logic).toFinishAllListeners()
            expect(logic.values.tasksByRunId.newer).toEqual(tasks)
            expect(logic.values.runDataErrors.newer).toBeNull()
            expect(logic.values.runDataLoading.newer).toBe(false)
            expect(loadWizardRunArtifacts).toHaveBeenCalledWith('1', completed.id)
        }
    )

    it('loads and streams a selected teammate run before discovery finishes', async () => {
        await expectLogic(logic).toFinishAllListeners()
        const teammateRun = { ...run('teammate'), created_by_id: MOCK_DEFAULT_USER.id + 1 }
        const tasks = [{ name: 'Install SDK', status: 'running' } as WizardRunTaskApi]
        jest.mocked(wizardRunsTasksRetrieve).mockResolvedValueOnce({ tasks })
        logic.actions.watchRuns('run-details', [teammateRun.id])
        logic.actions.loadRunData(teammateRun)
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.tasksByRunId.teammate).toEqual(tasks)
        expect(logic.values.userRuns.map((run) => run.id)).not.toContain(teammateRun.id)
        const stream = MockEventSource.last()
        expect(stream.url).toBe('/api/projects/1/wizard/runs/teammate/stream/')
        stream.emitMessage(JSON.stringify({ status: 'running', tasks: [{ name: 'Install SDK', status: 'completed' }] }))
        expect(logic.values.tasksByRunId.teammate[0].status).toBe('completed')
        logic.actions.watchRuns('run-details', [])
        expect(stream.readyState).toBe(MockEventSource.CLOSED)
    })

    it('keeps a newer streamed state when an older poll response arrives', async () => {
        await expectLogic(logic).toFinishAllListeners()
        MockEventSource.last().emitMessage(
            JSON.stringify({
                status: 'running',
                stage: 'creating_artifacts',
                updated_at: '2026-09-23T10:02:00Z',
                tasks: [],
            })
        )
        logic.actions.runsLoaded([run('newer')])
        expect(logic.values.userRuns[0].stage).toBe('creating_artifacts')
    })

    it('does not let an in-flight active snapshot replace the terminal tasks or artifacts', async () => {
        await expectLogic(logic).toFinishAllListeners()
        let resolveSnapshot!: (snapshot: WizardRunTaskListApi) => void
        jest.mocked(wizardRunsTasksRetrieve).mockReturnValueOnce(
            new Promise((resolve) => {
                resolveSnapshot = resolve
            })
        )
        const artifact: WizardRunArtifactApi = {
            id: 'completed-artifact',
            artifact_type: 'pull_request',
            team_id: 1,
            run_id: 'newer',
            url: 'https://github.com/example/project/pull/1',
            number: 1,
            repository: 'example/project',
            head_branch: 'setup',
            base_branch: 'main',
            created_at: '2026-09-23T10:05:00Z',
        }
        jest.mocked(loadWizardRunArtifacts).mockResolvedValueOnce([]).mockResolvedValueOnce([artifact])
        logic.actions.loadRunData(logic.values.userRuns[0])

        await expectLogic(logic, () =>
            MockEventSource.last().emitMessage(
                JSON.stringify({
                    status: 'completed',
                    stage: null,
                    updated_at: '2026-09-23T10:05:00Z',
                    tasks: [],
                })
            )
        ).toDispatchActions(['runDataLoaded'])
        expect(logic.values.artifactsByRunId.newer).toEqual([artifact])
        resolveSnapshot({ tasks: [] })
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.userRuns[0].status).toBe('completed')
        expect(logic.values.artifactsByRunId.newer).toEqual([artifact])
    })
})
