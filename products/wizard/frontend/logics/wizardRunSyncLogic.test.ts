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

function mockRunPages(activePage: { count: number; results: WizardRunApi[] }, recentRuns: WizardRunApi[] = []): void {
    mockWizardRunsList.mockImplementation((_projectId, { status }) =>
        Promise.resolve(status ? activePage : { count: recentRuns.length, results: recentRuns })
    )
}

function run(id: string): WizardRunApi {
    return { id, status: 'running', stage: 'executing_wizard' } as WizardRunApi
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
    })

    afterEach(() => {
        logic.unmount()
        restoreEventSource()
        jest.restoreAllMocks()
    })

    it('streams only the newest active run and switches when it changes', async () => {
        await expectLogic(logic).toFinishAllListeners()

        expect(mockWizardRunsList).toHaveBeenCalledWith('1', {
            status: ['created', 'running'],
            created_after: '2026-09-28T00:00:00Z',
            limit: 5,
        })
        expect(mockWizardRunsList).toHaveBeenCalledWith('1', {
            created_after: '2026-09-28T00:00:00Z',
            limit: 5,
        })
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

    it.each(['completed', 'failed', 'cancelled'] as const)(
        'loads %s runs after reloading and switches to the next active run',
        async (status) => {
            await expectLogic(logic).toFinishAllListeners()
            const stream = MockEventSource.last()
            const terminal = { ...run('newer'), status, stage: null }
            mockRunPages({ count: 0, results: [] }, [terminal])

            stream.emitMessage(JSON.stringify({ status, stage: null, tasks: [] }))
            await expectLogic(logic).toFinishAllListeners()
            expect(logic.values.run?.status).toBe(status)
            expect(stream.readyState).toBe(MockEventSource.CLOSED)

            logic.unmount()
            logic = wizardRunSyncLogic({ projectId: '1' })
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()
            expect(mockWizardRunsList).toHaveBeenCalledWith('1', {
                created_after: '2026-09-28T00:00:00Z',
                limit: 5,
            })
            expect(logic.values.run).toEqual(terminal)
            expect(MockEventSource.instances).toHaveLength(1)

            mockRunPages({ count: 1, results: [run('next')] }, [terminal])
            logic.actions.checkRuns()
            await expectLogic(logic).toFinishAllListeners()
            expect(logic.values.run?.id).toBe('next')
            expect(MockEventSource.instances).toHaveLength(2)
        }
    )

    it('handles a run completing between the active and completed responses', async () => {
        await expectLogic(logic).toFinishAllListeners()
        mockRunPages({ count: 1, results: [run('newer')] }, [run('newer')])
        logic.actions.checkRuns()
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.runs.map((run) => run.id)).toEqual(['newer'])

        const completed = { ...run('newer'), status: 'completed' as const, stage: null }
        mockRunPages({ count: 1, results: [run('newer')] }, [completed])
        logic.actions.checkRuns()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.runs).toEqual([completed])
        expect(logic.values.run?.status).toBe('completed')
        expect(MockEventSource.last().readyState).toBe(MockEventSource.CLOSED)
    })
})
