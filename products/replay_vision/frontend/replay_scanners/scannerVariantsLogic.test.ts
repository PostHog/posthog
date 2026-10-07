import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { scoutFleetLogic } from 'products/signals/frontend/inbox/logics/scoutFleetLogic'
import type { SignalScoutRunSummary } from 'products/signals/frontend/inbox/types'

import type { ExperimentVariantsReadoutApi, VariantsAnalysisStateApi } from '../generated/api.schemas'
import {
    UNATTRIBUTED_VARIANT,
    scannerVariantsLogic,
    variantAnalysisRunDisabledReason,
    variantComparisonState,
    variantFilterOptions,
    variantObservationsUrl,
} from './scannerVariantsLogic'

const analysis = (overrides: Partial<VariantsAnalysisStateApi>): VariantsAnalysisStateApi => ({
    scout_config_id: 'scout-1',
    scout_enabled: true,
    recorded_at: '2026-10-02T09:00:00Z',
    scanner_version: 2,
    current: true,
    ...overrides,
})

const readout: ExperimentVariantsReadoutApi = {
    experiment: null,
    window: { total_observations: 3, first_observation_at: null, last_observation_at: null },
    variants: [],
    differences: null,
    unattributed_count: 0,
    analysis: null,
}

const ANALYSIS_SKILL = 'signals-scout-checkout-variant-analysis'

const analysisRun = (status: string): SignalScoutRunSummary =>
    ({
        run_id: 'run-1',
        skill_name: ANALYSIS_SKILL,
        status,
        created_at: new Date().toISOString(),
        started_at: new Date().toISOString(),
        completed_at: null,
    }) as SignalScoutRunSummary

const runNowMocks = (runResponse: [number, Record<string, unknown>]): Parameters<typeof useMocks>[0] => ({
    get: {
        '/api/projects/:team/vision/scanners/:id/variants/': () => [200, readout],
        '/api/projects/:team/signals/scout/configs/': () => [200, []],
        '/api/projects/:team/signals/scout/runs/recent-per-scout/': () => [200, []],
    },
    post: { '/api/projects/:team/signals/scout/configs/:id/run/': () => runResponse },
})

describe('scannerVariantsLogic', () => {
    it.each([
        ['no scout', null, false, 'no_scout'],
        // The scout list can know about a scout the readout loaded before, and the CTA must not offer a second.
        ['a scout the readout has not seen yet', null, true, 'pending'],
        ['a scout that has not run', analysis({ recorded_at: null }), true, 'pending'],
        ['an analysis of an older scanner version', analysis({ current: false }), true, 'updating'],
        ['a current analysis', analysis({}), true, 'ready'],
    ] as const)('reads %s as %s', (_name, state, hasScout, expected) => {
        expect(variantComparisonState(state, hasScout)).toBe(expected)
    })

    // The readout counts only succeeded observations, but every observation that has not succeeded
    // also has no variant, so the "No variant" link must narrow to succeeded ones to match its count.
    it.each([
        ['a variant', 'control', null],
        ['no variant', UNATTRIBUTED_VARIANT, 'succeeded'],
    ])('links %s to the observations its count reads', (_name, variantKey, expectedStatus) => {
        const params = new URL(variantObservationsUrl('scanner-1', variantKey), 'http://localhost').searchParams

        expect(params.get('variant')).toBe(variantKey)
        expect(params.get('status')).toBe(expectedStatus)
    })

    // A link or an old URL can name a variant the experiment no longer lists, and the always-on filter
    // must still show it as selected instead of an empty dropdown.
    it.each([
        ['every variant', null, [null, 'control', 'test', UNATTRIBUTED_VARIANT]],
        ['a listed variant', 'test', [null, 'control', 'test', UNATTRIBUTED_VARIANT]],
        ['a variant not in the list', 'old-arm', [null, 'control', 'test', 'old-arm', UNATTRIBUTED_VARIANT]],
        ['no variant', UNATTRIBUTED_VARIANT, [null, 'control', 'test', UNATTRIBUTED_VARIANT]],
    ])('offers %s in the variant filter', (_name, current, expected) => {
        expect(variantFilterOptions(['control', 'test'], current).map((option) => option.value)).toEqual(expected)
    })

    // Run now must stay off for an hour after any run starts, scheduled or manual, so repeated clicks
    // can't stack runs, and must open again once the hour has passed.
    it.each([
        ['a run in progress', { running: true }, /^Variant analysis is running/],
        ['no observations yet', { hasObservations: false }, /^There are no observations to compare yet\.$/],
        ['a run 10 minutes ago', { lastRunStartedAt: '2026-10-07T11:50:00Z' }, /run it again in 50\s+minutes\.$/],
        ['a run just under an hour ago', { lastRunStartedAt: '2026-10-07T11:00:30Z' }, /run it again in 1\s+minute\.$/],
        ['a run over an hour ago', { lastRunStartedAt: '2026-10-07T10:59:00Z' }, /^enabled$/],
        ['no earlier run', {}, /^enabled$/],
    ])('with %s, Run now is disabled for the right reason', (_name, overrides, expected) => {
        const reason = variantAnalysisRunDisabledReason({
            running: false,
            lastRunStartedAt: null,
            hasObservations: true,
            now: new Date('2026-10-07T12:00:00Z').getTime(),
            ...overrides,
        })

        expect(reason ?? 'enabled').toMatch(expected)
    })

    // The comparison must refresh once the requested run is done, and not while it is still running,
    // or the tab keeps showing the old analysis after Run now.
    it('reloads the comparison when the run it started finishes', async () => {
        useMocks(runNowMocks([202, { skill_name: ANALYSIS_SKILL, workflow_id: 'wf-1', started: true }]))
        initKeaTests()
        const logic = scannerVariantsLogic({ scannerId: 'scanner-1' })
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadReadoutSuccess']).toFinishAllListeners()

        await expectLogic(logic, () => logic.actions.runAnalysisNow('config-1', ANALYSIS_SKILL))
            .toDispatchActions(['analysisRunStarted'])
            .toFinishAllListeners()
        await expectLogic(logic, () => scoutFleetLogic.actions.loadScoutRunsSuccess([analysisRun('in_progress')]))
            .toFinishAllListeners()
            .toNotHaveDispatchedActions(['loadReadout'])
        await expectLogic(logic, () =>
            scoutFleetLogic.actions.loadScoutRunsSuccess([analysisRun('completed')])
        ).toDispatchActions(['analysisRunSettled', 'loadReadout'])

        expect(logic.values.analysisRunRequest).toBeNull()
        logic.unmount()
    })

    // A refused start (a run in progress, a limit reached) must not leave the button on "Running…".
    it('stops waiting when the run start is refused', async () => {
        useMocks(runNowMocks([409, { detail: 'A run for this scout is already in progress.' }]))
        initKeaTests()
        const logic = scannerVariantsLogic({ scannerId: 'scanner-1' })
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadReadoutSuccess']).toFinishAllListeners()

        await expectLogic(logic, () => logic.actions.runAnalysisNow('config-1', ANALYSIS_SKILL))
            .toDispatchActions(['analysisRunSettled'])
            .toNotHaveDispatchedActions(['analysisRunStarted'])

        expect(logic.values).toMatchObject({ analysisRunRequest: null, analysisRunStarting: false })
        logic.unmount()
    })

    it('reports one tab view per mount, not one per reload', async () => {
        useMocks({ get: { '/api/projects/:team/vision/scanners/:id/variants/': () => [200, readout] } })
        initKeaTests()
        const captureSpy = jest.spyOn(posthog, 'capture')
        const logic = scannerVariantsLogic({ scannerId: 'scanner-1' })
        logic.mount()

        await expectLogic(logic).toDispatchActions(['loadReadoutSuccess']).toFinishAllListeners()
        await expectLogic(logic, () => logic.actions.loadReadout()).toFinishAllListeners()

        const views = captureSpy.mock.calls.filter(([event]) => event === 'replay_vision_variants_tab_viewed')
        expect(views).toEqual([
            [
                'replay_vision_variants_tab_viewed',
                expect.objectContaining({ scanner_id: 'scanner-1', comparison_state: 'no_scout', variant_count: 0 }),
            ],
        ])
        logic.unmount()
    })
})
