import type { ExperimentExposureQueryResponse } from '~/queries/schema/schema-general'

import type { ExperimentHealthApi, ExperimentHealthFindingApi } from '../generated/api.schemas'
import { healthPanelFindings } from './healthPanelFindings'

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

const UNEVEN_EXPOSURES = {
    timeseries: [{ variant: 'control' }, { variant: 'test' }],
    total_exposures: { control: 600, test: 400 },
    health_findings: [serverFinding('srm'), serverFinding('bias_risk_multiple_excluded')],
} as unknown as ExperimentExposureQueryResponse

describe('healthPanelFindings', () => {
    test.each<{
        name: string
        health: ExperimentHealthApi | null
        exposures: ExperimentExposureQueryResponse | null
        isExperimentDraft: boolean
        expected: string[] | null
    }>([
        {
            name: 'no panel without server findings, so the page keeps its own warnings',
            health: null,
            exposures: UNEVEN_EXPOSURES,
            isExperimentDraft: false,
            expected: null,
        },
        {
            name: 'no exposure finding before the exposures load',
            health: { findings: [serverFinding('no_metric')] },
            exposures: null,
            isExperimentDraft: false,
            expected: ['no_metric'],
        },
        {
            name: 'the findings of the exposure answer join those of the experiment read',
            health: { findings: [serverFinding('no_metric')] },
            exposures: UNEVEN_EXPOSURES,
            isExperimentDraft: false,
            expected: ['no_metric', 'srm', 'bias_risk_multiple_excluded'],
        },
        {
            name: 'a draft shows no finding of the exposure answer that a reset left in the page',
            health: { findings: [serverFinding('flag_live_before_launch')] },
            exposures: UNEVEN_EXPOSURES,
            isExperimentDraft: true,
            expected: ['flag_live_before_launch'],
        },
        {
            name: 'a code the experiment read sent is not added again from the exposure answer',
            health: { findings: [serverFinding('bias_risk_multiple_excluded')] },
            exposures: UNEVEN_EXPOSURES,
            isExperimentDraft: false,
            expected: ['bias_risk_multiple_excluded', 'srm'],
        },
    ])('$name', ({ health, exposures, isExperimentDraft, expected }) => {
        expect(healthPanelFindings(health, exposures, isExperimentDraft)?.map(({ code }) => code) ?? null).toEqual(
            expected
        )
    })
})
