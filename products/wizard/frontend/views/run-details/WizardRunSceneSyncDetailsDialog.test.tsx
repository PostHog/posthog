import { installMockEventSource, MockEventSource } from 'lib/wizard-sync/eventSource.mock'

import { act, cleanup, render } from '@testing-library/react'
import { Provider } from 'kea'
import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { wizardRunsRetrieve } from '../../generated/api'
import type { WizardRunApi } from '../../generated/api.schemas'
import { loadWizardRunArtifacts } from '../../lib/wizardApi'
import { wizardRunDetailsLogic } from '../../logics/wizardRunDetailsLogic'
import { wizardRunSyncLogic } from '../../logics/wizardRunSyncLogic'
import { WizardRunSceneSyncDetailsDialog } from './WizardRunSceneSyncDetailsDialog'

jest.mock('../../generated/api', () => ({
    wizardRunsList: jest.fn().mockResolvedValue({ results: [], next: null }),
    wizardRunsRetrieve: jest.fn(),
    wizardRunsTasksRetrieve: jest.fn().mockResolvedValue({ tasks: [] }),
    getWizardRunsStreamRetrieveUrl: (_: string, runId: string) => `/stream/${runId}`,
}))
jest.mock('../../lib/wizardApi', () => ({ loadWizardRunArtifacts: jest.fn().mockResolvedValue([]) }))
jest.mock('./WizardRunDetailsDialog', () => ({ WizardRunDetailsDialog: () => null }))

describe('WizardRunSceneSyncDetailsDialog', () => {
    it('keeps its stream across detail refreshes and reuses the dialog artifact request', async () => {
        initKeaTests()
        const restoreEventSource = installMockEventSource()
        const run: WizardRunApi = {
            id: 'example-run',
            team_id: 1,
            created_by_id: 1,
            created_by: null,
            environment: 'cloud',
            workspace: { type: 'git_repository', repository: 'example/project' },
            program: {
                id: 'posthog-integration',
                name: 'PostHog integration',
                description: 'Set up PostHog',
                wizard_version: '2.6.0',
                command: [],
                tags: [],
                required_programs: [],
                supported_environments: ['local', 'cloud'],
            },
            status: 'running',
            stage: 'executing_wizard',
            error_code: null,
            error_message: null,
            created_at: '2026-09-23T10:00:00Z',
            updated_at: '2026-09-23T10:01:00Z',
            started_at: '2026-09-23T10:00:00Z',
            finished_at: null,
            deadline_at: null,
        }
        jest.mocked(wizardRunsRetrieve).mockResolvedValue(run)
        const sync = wizardRunSyncLogic({ projectId: '1' })
        const details = wizardRunDetailsLogic()
        try {
            render(
                <Provider>
                    <WizardRunSceneSyncDetailsDialog projectId="1" onRunAgain={jest.fn()} />
                </Provider>
            )
            await act(async () => {
                details.actions.selectRun(run, 'wizard_datatable')
                await expectLogic(details).toFinishAllListeners()
                await expectLogic(sync).toFinishAllListeners()
            })
            const stream = MockEventSource.last()
            expect(MockEventSource.instances).toHaveLength(1)

            await act(async () => {
                details.actions.loadRunDetailsSuccess({ ...run, updated_at: '2026-09-23T10:02:00Z' })
                await expectLogic(sync).toFinishAllListeners()
            })
            expect(MockEventSource.instances).toHaveLength(1)
            expect(stream.readyState).not.toBe(MockEventSource.CLOSED)
            expect(loadWizardRunArtifacts).toHaveBeenCalledTimes(1)

            act(() => details.actions.selectRun(null))
            expect(stream.readyState).toBe(MockEventSource.CLOSED)
        } finally {
            cleanup()
            restoreEventSource()
        }
    })
})
