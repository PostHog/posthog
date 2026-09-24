import { installMockEventSource, MockEventSource } from 'lib/wizard-sync/eventSource.mock'

import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { wizardRunsList } from '../generated/api'
import type { WizardRunApi } from '../generated/api.schemas'
import { wizardRunSyncLogic } from './wizardRunSyncLogic'

jest.mock('../generated/api', () => ({
    wizardRunsList: jest.fn(),
    getWizardRunsStreamRetrieveUrl: (projectId: string, runId: string) =>
        `/api/projects/${projectId}/wizard/runs/${runId}/stream/`,
}))

const mockWizardRunsList = wizardRunsList as jest.Mock

function mockRunPages(
    activePage: { count: number; results: WizardRunApi[] },
    completedRuns: WizardRunApi[] = []
): void {
    mockWizardRunsList.mockImplementation((_projectId, { status }) =>
        Promise.resolve(
            status.includes('completed') ? { count: completedRuns.length, results: completedRuns } : activePage
        )
    )
}

function run(id: string): WizardRunApi {
    return { id, status: 'running', stage: 'executing_wizard' } as WizardRunApi
}

describe('wizardRunSyncLogic', () => {
    let restoreEventSource: () => void
    let logic: ReturnType<typeof wizardRunSyncLogic.build>

    beforeEach(() => {
        localStorage.clear()
        initKeaTests()
        restoreEventSource = installMockEventSource()
        mockWizardRunsList.mockReset()
        mockRunPages({ count: 2, results: [run('newer')] })
        logic = wizardRunSyncLogic({ projectId: '1' })
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
        restoreEventSource()
    })

    it('streams only the newest active run and switches when it changes', async () => {
        await expectLogic(logic).toFinishAllListeners()

        expect(mockWizardRunsList).toHaveBeenCalledWith('1', { status: ['created', 'running'], limit: 5 })
        expect(logic.values.activeCount).toBe(2)
        expect(logic.values.run?.id).toBe('newer')
        expect(MockEventSource.instances).toHaveLength(1)

        const firstStream = MockEventSource.last()
        firstStream.emitMessage(
            JSON.stringify({
                status: 'running',
                stage: 'executing_wizard',
                tasks: [{ name: 'Install SDK', status: 'running' }],
            })
        )
        expect(logic.values.tasks).toEqual([{ name: 'Install SDK', status: 'running' }])

        mockRunPages({ count: 1, results: [run('older')] })
        logic.actions.checkRuns()
        await expectLogic(logic).toFinishAllListeners()

        expect(firstStream.readyState).toBe(MockEventSource.CLOSED)
        expect(MockEventSource.instances).toHaveLength(2)
        expect(MockEventSource.last().url).toBe('/api/projects/1/wizard/runs/older/stream/')
        expect(logic.values.tasks).toEqual([])
    })

    it('keeps a selected run when it completes and lets another active run be selected', async () => {
        await expectLogic(logic).toFinishAllListeners()
        const newerStream = MockEventSource.last()
        const older = run('older')
        mockRunPages({ count: 2, results: [run('newer'), older] })
        logic.actions.checkRuns()
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.selectRun(older)
        expect(logic.values.run?.id).toBe('older')
        expect(newerStream.readyState).toBe(MockEventSource.CLOSED)
        expect(MockEventSource.last().url).toBe('/api/projects/1/wizard/runs/older/stream/')

        const olderStream = MockEventSource.last()
        mockRunPages({ count: 3, results: [run('latest'), run('newer'), older] })
        logic.actions.checkRuns()
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.run?.id).toBe('older')
        expect(MockEventSource.instances).toHaveLength(2)

        const completed = { ...older, status: 'completed' as const, stage: null }
        mockRunPages({ count: 2, results: [run('latest'), run('newer')] }, [completed])
        olderStream.emitMessage(JSON.stringify({ status: 'completed', stage: null, tasks: [] }))
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.run?.id).toBe('older')
        expect(logic.values.visibleRuns.map((run) => run.id)).toEqual(['latest', 'newer', 'older'])
        expect(logic.values.activeCount).toBe(2)
        expect(MockEventSource.instances).toHaveLength(2)
        expect(olderStream.readyState).toBe(MockEventSource.CLOSED)

        logic.actions.selectRun(run('latest'))
        expect(MockEventSource.instances).toHaveLength(3)
    })

    it('loads completed runs after reloading, keeps them selectable, and respects dismissal', async () => {
        await expectLogic(logic).toFinishAllListeners()
        const stream = MockEventSource.last()
        const completed = { ...run('newer'), status: 'completed' as const, stage: null }
        mockRunPages({ count: 0, results: [] }, [completed])

        stream.emitMessage(JSON.stringify({ status: 'completed', stage: null, tasks: [] }))
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.run?.status).toBe('completed')
        expect(stream.readyState).toBe(MockEventSource.CLOSED)

        logic.unmount()
        logic = wizardRunSyncLogic({ projectId: '1' })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        expect(mockWizardRunsList).toHaveBeenCalledWith('1', { status: ['completed'], limit: 5 })
        expect(logic.values.run).toEqual(completed)
        expect(MockEventSource.instances).toHaveLength(1)

        mockRunPages({ count: 1, results: [run('next')] }, [completed])
        logic.actions.checkRuns()
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.run?.id).toBe('next')
        logic.actions.selectRun(completed)
        expect(MockEventSource.last().readyState).toBe(MockEventSource.CLOSED)
        expect(MockEventSource.instances).toHaveLength(2)

        logic.actions.dismissRun('newer')
        expect(logic.values.run?.id).toBe('next')
        logic.actions.checkRuns()
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.visibleRuns.map((run) => run.id)).toEqual(['next'])
    })

    it('handles a run completing between the active and completed responses', async () => {
        await expectLogic(logic).toFinishAllListeners()
        const completed = { ...run('newer'), status: 'completed' as const, stage: null }
        mockRunPages({ count: 1, results: [run('newer')] }, [completed])
        logic.actions.checkRuns()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.visibleRuns).toEqual([completed])
        expect(logic.values.run?.status).toBe('completed')
        expect(logic.values.activeCount).toBe(0)
        expect(MockEventSource.last().readyState).toBe(MockEventSource.CLOSED)
    })

    it('keeps a dismissed run hidden while polling and streams the next run', async () => {
        await expectLogic(logic).toFinishAllListeners()
        const stream = MockEventSource.last()

        logic.actions.dismissRun('newer')
        expect(stream.readyState).toBe(MockEventSource.CLOSED)
        expect(logic.values.dismissedRunIds).toEqual(['newer'])

        logic.actions.checkRuns()
        await expectLogic(logic).toFinishAllListeners()
        expect(MockEventSource.instances).toHaveLength(1)

        mockRunPages({ count: 1, results: [run('next')] })
        logic.actions.checkRuns()
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.run?.id).toBe('next')
        expect(MockEventSource.instances).toHaveLength(2)

        mockRunPages({ count: 1, results: [run('newer')] })
        logic.actions.checkRuns()
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.dismissedRunIds).toEqual(['newer'])
        expect(MockEventSource.instances).toHaveLength(2)

        logic.unmount()
        logic = wizardRunSyncLogic({ projectId: '1' })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.dismissedRunIds).toEqual(['newer'])
        expect(MockEventSource.instances).toHaveLength(2)
    })

    it('closes the current run until the page reloads', async () => {
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.closeRun('newer')
        expect(logic.values.closedRunIds).toEqual(['newer'])
        expect(logic.values.dismissedRunIds).toEqual([])
        expect(MockEventSource.last().readyState).toBe(MockEventSource.CLOSED)

        logic.actions.checkRuns()
        await expectLogic(logic).toFinishAllListeners()
        expect(MockEventSource.instances).toHaveLength(1)

        logic.unmount()
        logic = wizardRunSyncLogic({ projectId: '1' })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.closedRunIds).toEqual([])
        expect(MockEventSource.instances).toHaveLength(2)

        mockRunPages({ count: 1, results: [run('next')] })
        logic.actions.checkRuns()
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.run?.id).toBe('next')
        expect(MockEventSource.instances).toHaveLength(3)
    })
})
