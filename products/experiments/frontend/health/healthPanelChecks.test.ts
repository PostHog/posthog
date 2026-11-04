import { type ExperimentExposureQueryResponse, NodeKind } from '~/queries/schema/schema-general'

import type { ExperimentHealthApi, ExperimentHealthCheckResultApi } from '../generated/api.schemas'
import {
    type ExposureChecksState,
    type HealthChipState,
    type HealthPanelCheck,
    exposureChecksState,
    healthChipState,
    healthPanelChecks,
} from './healthPanelChecks'
import type { HealthPanelFinding } from './healthPanelFindings'

const check = (
    key: ExperimentHealthCheckResultApi['key'],
    status: ExperimentHealthCheckResultApi['status']
): HealthPanelCheck => ({ key, name: key, status, reason: null })

const finding = (severity: HealthPanelFinding['severity']): HealthPanelFinding => ({
    code: 'no_metric',
    subcode: null,
    reason: null,
    severity,
    title: 'No metrics defined',
    detail: '',
    evidence: {},
    actions: [],
})

const EXPOSURES = {
    kind: NodeKind.ExperimentExposureQuery,
    timeseries: [],
    total_exposures: { control: 600, test: 400 },
    date_range: { date_from: '2026-10-01', date_to: '2026-10-02' },
    health_findings: [],
    health_checks: [
        { key: 'zero_exposures', name: 'Exposures not received since launch', status: 'passed', reason: null },
        { key: 'srm', name: 'Split of users across variants', status: 'finding', reason: null },
    ],
} satisfies ExperimentExposureQueryResponse

const EXPOSURES_WITHOUT_CHECKS = { ...EXPOSURES, health_checks: undefined }

describe('healthPanelChecks', () => {
    test.each<{ name: string; isExperimentDraft: boolean; expected: string[] }>([
        {
            name: 'the checks of the exposure answer join those of the experiment read, problems first',
            isExperimentDraft: false,
            expected: ['srm:finding', 'split_changed_mid_run:not_checked', 'no_metric:passed', 'zero_exposures:passed'],
        },
        {
            name: 'a draft lists no exposure check that a reset left in the page',
            isExperimentDraft: true,
            expected: ['split_changed_mid_run:not_checked', 'no_metric:passed'],
        },
    ])('$name', ({ isExperimentDraft, expected }) => {
        // The flag history check is left out: its note and the checks it serves report when it can't read the history.
        const health = {
            findings: [],
            checks: [
                check('no_metric', 'passed'),
                check('split_changed_mid_run', 'not_checked'),
                check('flag_history', 'passed'),
            ],
        }
        expect(
            healthPanelChecks(health, EXPOSURES, isExperimentDraft)?.map(({ key, status }) => `${key}:${status}`)
        ).toEqual(expected)
    })

    it('lists the exposure checks when the health response has no checks', () => {
        const healthWithoutChecks = { findings: [] } as unknown as ExperimentHealthApi

        expect(healthPanelChecks(healthWithoutChecks, EXPOSURES, false)?.map(({ key }) => key)).toEqual([
            'srm',
            'zero_exposures',
        ])
    })

    test.each<{
        name: string
        isLaunched: boolean
        exposures: ExperimentExposureQueryResponse | null
        loading: boolean
        expected: ExposureChecksState
    }>([
        {
            name: 'a draft has no exposure checks',
            isLaunched: false,
            exposures: null,
            loading: false,
            expected: 'not_launched',
        },
        {
            name: 'an answer with checks is ready while it reloads',
            isLaunched: true,
            exposures: EXPOSURES,
            loading: true,
            expected: 'ready',
        },
        { name: 'the first load is pending', isLaunched: true, exposures: null, loading: true, expected: 'pending' },
        {
            name: 'a failed load misses the checks',
            isLaunched: true,
            exposures: null,
            loading: false,
            expected: 'missing',
        },
        {
            name: 'an answer cached before the checks misses them',
            isLaunched: true,
            exposures: EXPOSURES_WITHOUT_CHECKS,
            loading: false,
            expected: 'missing',
        },
    ])('$name', ({ isLaunched, exposures, loading, expected }) => {
        expect(exposureChecksState(isLaunched, exposures, loading)).toEqual(expected)
    })

    test.each<{
        name: string
        findings: HealthPanelFinding[] | null
        checks: HealthPanelCheck[] | null
        exposureChecks: ExposureChecksState
        expected: Partial<HealthChipState>
    }>([
        {
            name: 'no chip without server findings',
            findings: null,
            checks: null,
            exposureChecks: 'ready',
            expected: { kind: 'hidden' },
        },
        {
            name: 'issues count no info finding',
            findings: [finding('critical'), finding('warning'), finding('info')],
            checks: [],
            exposureChecks: 'ready',
            expected: { kind: 'issues', count: 2, hasCritical: true },
        },
        {
            name: 'an issue shows while the exposure checks run',
            findings: [finding('warning')],
            checks: [],
            exposureChecks: 'pending',
            expected: { kind: 'issues', count: 1, hasCritical: false },
        },
        {
            name: 'no verdict while the exposure checks run',
            findings: [],
            checks: [check('no_metric', 'passed')],
            exposureChecks: 'pending',
            expected: { kind: 'pending' },
        },
        {
            name: 'the label counts the passed checks and the notes',
            findings: [finding('info')],
            checks: [check('no_metric', 'passed'), check('flag_state', 'passed'), check('srm', 'not_applicable')],
            exposureChecks: 'ready',
            expected: { kind: 'checks', label: 'No problems found (2\u00a0checks) · 1\u00a0note' },
        },
        {
            name: 'the label says so when no check applies',
            findings: [],
            checks: [check('no_metric', 'not_applicable')],
            exposureChecks: 'not_launched',
            expected: { kind: 'checks', label: 'No checks apply yet' },
        },
    ])('$name', ({ findings, checks, exposureChecks, expected }) => {
        expect(healthChipState(findings, checks, exposureChecks)).toMatchObject(expected)
    })
})
