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
        mockWizardRunsList.mockResolvedValue({ count: 2, results: [run('newer')] })
        logic = wizardRunSyncLogic({ projectId: '1' })
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
        restoreEventSource()
    })

    it('streams only the newest active run and switches when it changes', async () => {
        await expectLogic(logic).toFinishAllListeners()

        expect(mockWizardRunsList).toHaveBeenCalledWith('1', { status: ['created', 'running'], limit: 1 })
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

        mockWizardRunsList.mockResolvedValue({ count: 1, results: [run('older')] })
        logic.actions.checkActiveRuns()
        await expectLogic(logic).toFinishAllListeners()

        expect(firstStream.readyState).toBe(MockEventSource.CLOSED)
        expect(MockEventSource.instances).toHaveLength(2)
        expect(MockEventSource.last().url).toBe('/api/projects/1/wizard/runs/older/stream/')
        expect(logic.values.tasks).toEqual([])
    })

    it('keeps a finished run visible until dismissed', async () => {
        await expectLogic(logic).toFinishAllListeners()
        const stream = MockEventSource.last()
        mockWizardRunsList.mockResolvedValue({ count: 0, results: [] })

        stream.emitMessage(JSON.stringify({ status: 'completed', stage: null, tasks: [] }))
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.run?.status).toBe('completed')
        expect(stream.readyState).toBe(MockEventSource.CLOSED)

        logic.actions.dismissRun('newer')
        expect(logic.values.run).toBeNull()
    })

    it('keeps a closed run hidden while polling and streams the next run', async () => {
        await expectLogic(logic).toFinishAllListeners()
        const stream = MockEventSource.last()

        logic.actions.dismissRun('newer')
        expect(stream.readyState).toBe(MockEventSource.CLOSED)
        expect(logic.values.dismissedRunId).toBe('newer')

        logic.actions.checkActiveRuns()
        await expectLogic(logic).toFinishAllListeners()
        expect(MockEventSource.instances).toHaveLength(1)

        mockWizardRunsList.mockResolvedValue({ count: 1, results: [run('next')] })
        logic.actions.checkActiveRuns()
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.run?.id).toBe('next')
        expect(MockEventSource.instances).toHaveLength(2)
    })
})
