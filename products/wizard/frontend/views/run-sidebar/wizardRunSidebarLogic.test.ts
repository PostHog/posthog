import { MOCK_DEFAULT_USER } from 'lib/api.mock'
import { installMockEventSource, MockEventSource } from 'lib/wizard-sync/eventSource.mock'

import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { initKeaTests } from '~/test/init'

import { wizardScansDetectedSourcesRetrieve } from '../../generated/api'
import type { WizardRunApi } from '../../generated/api.schemas'
import { wizardRunSyncLogic } from '../../logics/wizardRunSyncLogic'
import { wizardRunSidebarLogic } from './wizardRunSidebarLogic'

jest.mock('../../generated/api', () => ({
    wizardRunsList: jest.fn().mockResolvedValue({ results: [], next: null }),
    getWizardRunsStreamRetrieveUrl: (_: string, id: string) => `/stream/${id}`,
    wizardScansDetectedSourcesRetrieve: jest.fn().mockResolvedValue([
        { kind: 'Stripe', warehouse_source_type: 'Stripe', first_seen_at: '', last_seen_at: '2026-05-19T10:05:00Z' },
        {
            kind: 'Postgres',
            warehouse_source_type: 'Postgres',
            first_seen_at: '',
            last_seen_at: '2026-05-18T09:00:00Z',
        },
    ]),
}))

const props = { projectId: '1', userId: MOCK_DEFAULT_USER.id }
function run(id: string): WizardRunApi {
    return { id, status: 'completed', created_by_id: props.userId } as WizardRunApi
}

describe('wizardRunSidebarLogic', () => {
    let logic: ReturnType<typeof wizardRunSidebarLogic.build>
    let restoreEventSource: () => void

    beforeEach(() => {
        localStorage.clear()
        initKeaTests()
        restoreEventSource = installMockEventSource()
        logic = wizardRunSidebarLogic(props)
        logic.mount()
    })
    afterEach(() => {
        logic.unmount()
        restoreEventSource()
        localStorage.clear()
    })

    it('dismisses one, several, or all known runs without hiding future runs, including after reload', async () => {
        await expectLogic(logic).toFinishAllListeners()
        const sync = wizardRunSyncLogic({ projectId: '1' })
        const runs = ['first', 'second', 'third'].map((id) => ({ ...run(id), status: 'running' as const }))
        sync.actions.runsLoaded(runs)
        logic.actions.clickState('navbar_sidebar')
        expect(posthog.capture).toHaveBeenCalledWith('wizard sidebar state clicked', {
            event_source: 'wizard_ui',
            project_id: '1',
            location: 'navbar_sidebar',
            run_count: 3,
            active_run_count: 3,
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
        expect(MockEventSource.instances.every((stream) => stream.readyState === MockEventSource.CLOSED)).toBe(true)
        sync.actions.runsLoaded([{ ...run('new'), status: 'running' }, ...runs])
        expect(logic.values.visibleRuns.map((run) => run.id)).toEqual(['new'])
        expect(MockEventSource.last().url).toBe('/stream/new')
        logic.unmount()

        initKeaTests()
        logic = wizardRunSidebarLogic(props)
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        wizardRunSyncLogic({ projectId: '1' }).actions.runsLoaded([run('new'), ...runs])
        expect(logic.values.visibleRuns.map((run) => run.id)).toEqual(['new'])
    })

    it('shows only the sources a scan found since the earliest visible run started', async () => {
        await expectLogic(logic).toFinishAllListeners()

        wizardRunSyncLogic({ projectId: '1' }).actions.runsLoaded([
            { ...run('current'), created_at: '2026-05-19T10:00:00Z' },
        ])

        expect(logic.values.runDetectedSources.map((source) => source.warehouse_source_type)).toEqual(['Stripe'])
    })

    it('refreshes detected sources while a run is active and until a load after it ends succeeds', async () => {
        await expectLogic(logic).toFinishAllListeners()
        const sync = wizardRunSyncLogic({ projectId: '1' })
        const retrieve = jest.mocked(wizardScansDetectedSourcesRetrieve)
        const tick = async (): Promise<number> => {
            const before = retrieve.mock.calls.length
            logic.actions.refreshDetectedSources()
            await expectLogic(logic).toFinishAllListeners()
            return retrieve.mock.calls.length - before
        }

        expect(await tick()).toBe(0)

        sync.actions.runsLoaded([{ ...run('current'), status: 'running' }])
        logic.actions.refreshDetectedSources()
        expect(await tick()).toBe(0)

        sync.actions.runsLoaded([{ ...run('current'), status: 'completed' }])
        retrieve.mockRejectedValueOnce(new Error('offline'))
        expect(await tick()).toBe(1)
        expect(await tick()).toBe(1)
        expect(await tick()).toBe(0)
    })

    test.each([
        { name: 'no runs', runs: [], dismissedBeforeLoad: [], visible: false },
        {
            name: 'a running run',
            runs: [{ ...run('a'), status: 'running', finished_at: null }],
            dismissedBeforeLoad: [],
            visible: true,
        },
        {
            name: 'a run that finished 23 hours ago',
            runs: [{ ...run('a'), finished_at: '2026-05-19T11:00:00Z' }],
            dismissedBeforeLoad: [],
            visible: true,
        },
        {
            name: 'a run that finished 25 hours ago',
            runs: [{ ...run('a'), finished_at: '2026-05-19T09:00:00Z' }],
            dismissedBeforeLoad: [],
            visible: false,
        },
        {
            name: 'a recent run dismissed in an earlier session',
            runs: [{ ...run('a'), finished_at: '2026-05-19T11:00:00Z' }],
            dismissedBeforeLoad: ['a'],
            visible: false,
        },
    ])('shows the rail tile with $name: $visible', async ({ runs, dismissedBeforeLoad, visible }) => {
        const now = jest.spyOn(Date, 'now').mockReturnValue(Date.parse('2026-05-20T10:00:00Z'))
        try {
            await expectLogic(logic).toFinishAllListeners()

            logic.actions.dismissRuns(dismissedBeforeLoad)
            wizardRunSyncLogic({ projectId: '1' }).actions.runsLoaded(runs as WizardRunApi[])

            expect(logic.values.railVisible).toBe(visible)
        } finally {
            now.mockRestore()
        }
    })

    it('keeps the rail tile until a reload once it shows', async () => {
        await expectLogic(logic).toFinishAllListeners()
        const runs = [{ ...run('a'), status: 'running' as const }]
        wizardRunSyncLogic({ projectId: '1' }).actions.runsLoaded(runs)

        logic.actions.dismissRuns(['a'])

        expect(logic.values.railVisible).toBe(true)
        logic.unmount()

        initKeaTests()
        logic = wizardRunSidebarLogic(props)
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        wizardRunSyncLogic({ projectId: '1' }).actions.runsLoaded(runs)

        expect(logic.values.railVisible).toBe(false)
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
