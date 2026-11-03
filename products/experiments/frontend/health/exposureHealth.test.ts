import {
    type ExperimentExposureHealthCheck,
    type ExperimentExposureQueryResponse,
    NodeKind,
} from '~/queries/schema/schema-general'

import { SAMPLE_RATIO_MISMATCH_DESCRIPTION, sampleRatioLine } from './exposureHealth'

const srmFinding = (
    subcode: string | null,
    severity: 'warning' | 'info' = 'warning'
): NonNullable<ExperimentExposureQueryResponse['health_findings']>[number] => ({
    code: 'srm',
    subcode,
    reason: null,
    severity,
    title: 'Users are not split as configured',
    detail: `Server detail for ${subcode ?? 'a mismatch'}`,
    evidence: {},
    actions: [],
    diagnostic_ref: 'A2',
})

const MISMATCH = {
    kind: NodeKind.ExperimentExposureQuery,
    timeseries: [],
    total_exposures: { control: 600, test: 400 },
    date_range: { date_from: '2026-10-01', date_to: '2026-10-02' },
    sample_ratio_mismatch: { expected: { control: 500, test: 500 }, p_value: 0.00001 },
    health_findings: [srmFinding('split_changed')],
    health_checks: [],
} satisfies ExperimentExposureQueryResponse

const SRM_NOT_APPLICABLE: ExperimentExposureHealthCheck = {
    key: 'srm',
    name: 'Sample ratio mismatch',
    status: 'not_applicable',
    reason: 'The split assigns nobody, because every release condition sets a variant override',
}

describe('sampleRatioLine', () => {
    it.each([
        {
            desc: 'a mismatch after a split change',
            exposures: MISMATCH,
            followsServer: true,
            expected: {
                tone: 'warning',
                label: 'Sample ratio mismatch after a split change',
                tooltip: 'Server detail for split_changed',
            },
        },
        {
            desc: 'a mismatch the server reports without a cause',
            exposures: { ...MISMATCH, health_findings: [srmFinding(null)] },
            followsServer: true,
            expected: {
                tone: 'warning',
                label: 'Sample ratio mismatch detected',
                tooltip: 'Server detail for a mismatch',
            },
        },
        {
            desc: 'a mismatch the server reports as info',
            exposures: { ...MISMATCH, health_findings: [srmFinding(null, 'info')] },
            followsServer: true,
            expected: { tone: 'info', label: 'Sample ratio mismatch detected' },
        },
        {
            desc: 'a split that every variant override bypasses',
            exposures: { ...MISMATCH, health_findings: [], health_checks: [SRM_NOT_APPLICABLE] },
            followsServer: true,
            expected: null,
        },
        {
            desc: 'a reader without the health panel',
            exposures: MISMATCH,
            followsServer: false,
            expected: {
                tone: 'warning',
                label: 'Sample ratio mismatch detected',
                tooltip: SAMPLE_RATIO_MISMATCH_DESCRIPTION,
            },
        },
        {
            desc: 'an answer cached before the server ran its checks',
            exposures: { ...MISMATCH, health_findings: undefined },
            followsServer: true,
            expected: {
                tone: 'warning',
                label: 'Sample ratio mismatch detected',
                tooltip: SAMPLE_RATIO_MISMATCH_DESCRIPTION,
            },
        },
    ])('follows the server only with the health panel: $desc', ({ exposures, followsServer, expected }) => {
        expect(sampleRatioLine(exposures, followsServer)).toEqual(expected && expect.objectContaining(expected))
    })
})
