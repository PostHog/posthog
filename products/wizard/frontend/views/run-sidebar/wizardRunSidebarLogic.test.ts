import { MOCK_DEFAULT_USER } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { initKeaTests } from '~/test/init'

import type { WizardRunApi } from '../../generated/api.schemas'
import { wizardRunSyncLogic } from '../../logics/wizardRunSyncLogic'
import { wizardRunSidebarLogic } from './wizardRunSidebarLogic'

jest.mock('../../generated/api', () => ({ wizardRunsList: jest.fn().mockResolvedValue({ results: [], next: null }) }))

const props = { projectId: '1', userId: MOCK_DEFAULT_USER.id }
function run(id: string): WizardRunApi {
    return { id, status: 'completed', created_by_id: props.userId } as WizardRunApi
}

describe('wizardRunSidebarLogic', () => {
    let logic: ReturnType<typeof wizardRunSidebarLogic.build>

    beforeEach(() => {
        localStorage.clear()
        initKeaTests()
        logic = wizardRunSidebarLogic(props)
        logic.mount()
    })
    afterEach(() => {
        logic.unmount()
        localStorage.clear()
    })

    it('dismisses one, several, or all known runs without hiding future runs, including after reload', async () => {
        await expectLogic(logic).toFinishAllListeners()
        const sync = wizardRunSyncLogic({ projectId: '1' })
        const runs = ['first', 'second', 'third'].map(run)
        sync.actions.runsLoaded(runs)
        logic.actions.clickState()
        expect(posthog.capture).toHaveBeenCalledWith('wizard sidebar state clicked', {
            event_source: 'wizard_ui',
            project_id: '1',
            run_count: 3,
            active_run_count: 0,
        })
        logic.actions.dismissRuns(['first'])
        expect(posthog.capture).toHaveBeenCalledWith('wizard sidebar state dismissed', {
            event_source: 'wizard_ui',
            project_id: '1',
            run_count: 1,
            remaining_run_count: 2,
        })
        expect(logic.values.visibleRuns.map((run) => run.id)).toEqual(['second', 'third'])
        logic.actions.dismissRuns(logic.values.visibleRuns.map((run) => run.id))
        expect(posthog.capture).toHaveBeenLastCalledWith('wizard sidebar state dismissed', {
            event_source: 'wizard_ui',
            project_id: '1',
            run_count: 2,
            remaining_run_count: 0,
        })
        expect(logic.values.visibleRuns).toEqual([])
        sync.actions.runsLoaded([run('new'), ...runs])
        expect(logic.values.visibleRuns.map((run) => run.id)).toEqual(['new'])
        logic.unmount()

        initKeaTests()
        logic = wizardRunSidebarLogic(props)
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        wizardRunSyncLogic({ projectId: '1' }).actions.runsLoaded([run('new'), ...runs])
        expect(logic.values.visibleRuns.map((run) => run.id)).toEqual(['new'])
    })

    it('scopes dismissals to the current project and user', async () => {
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.dismissRuns(['first'])
        logic.unmount()
        logic = wizardRunSidebarLogic({ projectId: '2', userId: props.userId + 1 })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.dismissedRunIds).toEqual([])
    })
})
