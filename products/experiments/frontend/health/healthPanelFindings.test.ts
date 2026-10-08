import type { ExperimentHealthApi, ExperimentHealthFindingApi } from '../generated/api.schemas'
import { type ExposureHealthInput, healthPanelFindings } from './healthPanelFindings'

const serverFinding = (code: ExperimentHealthFindingApi['code']): ExperimentHealthFindingApi => ({
    code,
    subcode: null,
    severity: 'warning',
    title: code,
    detail: code,
    evidence: {},
    actions: [],
    diagnostic_ref: null,
})

// The exposure query returns a series for every configured variant, with zero counts when nobody was exposed.
const NO_EXPOSURES = {
    timeseries: [{ variant: 'control' }, { variant: 'test' }],
    total_exposures: { control: 0, test: 0 },
}

const UNEVEN_EXPOSURES = {
    timeseries: [{ variant: 'control' }, { variant: 'test' }],
    total_exposures: { control: 600, test: 400 },
    sample_ratio_mismatch: { expected: { control: 500, test: 500 }, p_value: 0.0001 },
    bias_risk: { multiple_variant_percentage: 5 },
}

describe('healthPanelFindings', () => {
    test.each<{
        name: string
        health: ExperimentHealthApi | null
        exposures: Record<string, unknown> | null
        isExperimentDraft: boolean
        hoursSinceStart: number | null
        expected: string[] | null
    }>([
        {
            name: 'no panel without server findings, so the page keeps its own warnings',
            health: null,
            exposures: UNEVEN_EXPOSURES,
            isExperimentDraft: false,
            hoursSinceStart: 72,
            expected: null,
        },
        {
            name: 'no exposure finding before the exposures load',
            health: { findings: [serverFinding('no_metric')] },
            exposures: null,
            isExperimentDraft: false,
            hoursSinceStart: 72,
            expected: ['no_metric'],
        },
        {
            name: 'no zero-exposure finding on a draft',
            health: { findings: [serverFinding('flag_live_before_launch')] },
            exposures: NO_EXPOSURES,
            isExperimentDraft: true,
            hoursSinceStart: null,
            expected: ['flag_live_before_launch'],
        },
        {
            name: 'no users exposed a day after launch',
            health: { findings: [] },
            exposures: NO_EXPOSURES,
            isExperimentDraft: false,
            hoursSinceStart: 24,
            expected: ['zero_exposures'],
        },
        {
            name: 'no zero-exposure finding in the first day',
            health: { findings: [] },
            exposures: NO_EXPOSURES,
            isExperimentDraft: false,
            hoursSinceStart: 23,
            expected: [],
        },
        {
            name: 'a finding the server already sent is not added again from the exposures',
            health: { findings: [serverFinding('bias_risk_multiple_excluded')] },
            exposures: UNEVEN_EXPOSURES,
            isExperimentDraft: false,
            hoursSinceStart: 72,
            expected: ['bias_risk_multiple_excluded', 'srm'],
        },
    ])('$name', ({ health, exposures, isExperimentDraft, hoursSinceStart, expected }) => {
        const input = { exposures, isExperimentDraft, hoursSinceStart } as ExposureHealthInput

        expect(healthPanelFindings(health, input)?.map(({ code }) => code) ?? null).toEqual(expected)
    })
})
