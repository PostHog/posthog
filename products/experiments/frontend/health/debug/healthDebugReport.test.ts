import type { ExperimentWarning } from 'scenes/experiments/experimentLogic'

import type { ExperimentHealthApi, ExperimentHealthFindingApi } from '../../generated/api.schemas'
import { type HealthDebugInput, buildHealthDebugChecks } from './healthDebugReport'

const PAUSED: ExperimentHealthFindingApi = {
    code: 'flag_off_while_running',
    subcode: 'running_but_flag_disabled',
    reason: null,
    severity: 'warning',
    title: 'The experiment is paused',
    detail: '',
    evidence: {},
    actions: ['open_feature_flag'],
    diagnostic_ref: 'A5',
}

const input = (overrides: Partial<HealthDebugInput>): HealthDebugInput => ({
    health: { findings: [], checks: [] },
    browserWarning: null,
    browserNoMetricsWarning: false,
    isExperimentDraft: false,
    exposures: null,
    exposuresLoading: false,
    serverExposures: null,
    serverExposuresLoading: false,
    ...overrides,
})

describe('buildHealthDebugChecks', () => {
    test.each<{
        name: string
        health: ExperimentHealthApi | null
        browserWarning: ExperimentWarning | null
        browserNoMetricsWarning: boolean
        extra?: Partial<HealthDebugInput>
        expected: string[]
    }>([
        {
            name: 'browser rules agree with the server',
            health: { findings: [PAUSED], checks: [] },
            browserWarning: { key: 'running_but_flag_disabled' },
            browserNoMetricsWarning: false,
            expected: [],
        },
        {
            name: 'a flag-state warning only the server finds',
            health: { findings: [PAUSED], checks: [] },
            browserWarning: null,
            browserNoMetricsWarning: false,
            expected: ['flag_state:disagrees'],
        },
        {
            name: 'a flag-state subcode the page does not know, while the browser finds nothing',
            health: { findings: [{ ...PAUSED, subcode: 'running_but_unknown_case' }], checks: [] },
            browserWarning: null,
            browserNoMetricsWarning: false,
            expected: ['flag_state:disagrees'],
        },
        {
            name: 'no metrics on the page while the server counts one',
            health: { findings: [], checks: [] },
            browserWarning: null,
            browserNoMetricsWarning: true,
            expected: ['no_metric:disagrees'],
        },
        {
            name: "an SRM finding in the server's exposure answer only",
            health: { findings: [], checks: [] },
            browserWarning: null,
            browserNoMetricsWarning: false,
            extra: {
                exposures: { total_exposures: {}, timeseries: [], date_range: { date_from: null } } as any,
                serverExposures: {
                    status: 'ready',
                    computed_at: null,
                    totals: null,
                    findings: [{ ...PAUSED, code: 'srm', subcode: null, severity: 'warning' }],
                    error: null,
                },
            },
            expected: ['srm:drift'],
        },
        {
            name: 'the same SRM finding in both answers while the health request failed',
            health: null,
            browserWarning: null,
            browserNoMetricsWarning: false,
            extra: {
                exposures: {
                    total_exposures: {},
                    timeseries: [],
                    date_range: { date_from: null },
                    health_findings: [{ ...PAUSED, code: 'srm', subcode: null, severity: 'warning' }],
                } as any,
                serverExposures: {
                    status: 'ready',
                    computed_at: null,
                    totals: null,
                    findings: [{ ...PAUSED, code: 'srm', subcode: null, severity: 'warning' }],
                    error: null,
                },
            },
            expected: [],
        },
        {
            name: 'nothing to compare without server health',
            health: null,
            browserWarning: { key: 'running_but_flag_disabled' },
            browserNoMetricsWarning: true,
            expected: [],
        },
    ])('$name', ({ health, browserWarning, browserNoMetricsWarning, extra, expected }) => {
        const checks = buildHealthDebugChecks(input({ health, browserWarning, browserNoMetricsWarning, ...extra }))

        expect(
            checks.filter(({ difference }) => difference).map(({ check, difference }) => `${check}:${difference}`)
        ).toEqual(expected)
    })
})
