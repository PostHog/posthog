import type { ExperimentWarning } from 'scenes/experiments/experimentLogic'

import type { ExperimentHealthApi, ExperimentHealthFindingApi } from '../generated/api.schemas'
import { type HealthDebugInput, buildHealthDebugChecks } from './healthDebugReport'

const PAUSED: ExperimentHealthFindingApi = {
    code: 'flag_off_while_running',
    subcode: 'running_but_flag_disabled',
    severity: 'warning',
    title: 'The experiment is paused',
    detail: '',
    evidence: {},
    actions: ['open_feature_flag'],
    diagnostic_ref: 'A5',
}

const input = (overrides: Partial<HealthDebugInput>): HealthDebugInput => ({
    health: { findings: [] },
    panelFindings: [],
    browserWarning: null,
    browserNoMetricsWarning: false,
    pageMetricCounts: { primary: 1, secondary: 0 },
    isExperimentDraft: false,
    hoursSinceStart: 72,
    exposures: null,
    exposuresLoading: false,
    multipleVariantHandling: 'exclude',
    ...overrides,
})

describe('buildHealthDebugChecks', () => {
    test.each<{
        name: string
        health: ExperimentHealthApi | null
        browserWarning: ExperimentWarning | null
        browserNoMetricsWarning: boolean
        expected: string[]
    }>([
        {
            name: 'browser rules agree with the server',
            health: { findings: [PAUSED] },
            browserWarning: { key: 'running_but_flag_disabled' },
            browserNoMetricsWarning: false,
            expected: [],
        },
        {
            name: 'a flag-state warning only the server finds',
            health: { findings: [PAUSED] },
            browserWarning: null,
            browserNoMetricsWarning: false,
            expected: ['flag_state'],
        },
        {
            name: 'a flag-state subcode the page does not know, while the browser finds nothing',
            health: { findings: [{ ...PAUSED, subcode: 'running_but_unknown_case' }] },
            browserWarning: null,
            browserNoMetricsWarning: false,
            expected: ['flag_state'],
        },
        {
            name: 'no metrics on the page while the server counts one',
            health: { findings: [] },
            browserWarning: null,
            browserNoMetricsWarning: true,
            expected: ['no_metric'],
        },
        {
            name: 'nothing to compare without server health',
            health: null,
            browserWarning: { key: 'running_but_flag_disabled' },
            browserNoMetricsWarning: true,
            expected: [],
        },
    ])('$name', ({ health, browserWarning, browserNoMetricsWarning, expected }) => {
        const checks = buildHealthDebugChecks(input({ health, browserWarning, browserNoMetricsWarning }))

        expect(checks.filter(({ differs }) => differs).map(({ check }) => check)).toEqual(expected)
    })
})
