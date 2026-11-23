import type { SignalReportCheckApi } from 'products/signals/frontend/generated/api.schemas'

import { SignalReportArtefact } from '../../types'
import type { CheckObservationContent } from './artefactTypes'
import {
    checkObservationsByCheck,
    interimCheckTag,
    monitoringTimeline,
    ReportCheckObservation,
} from './reportCheckObservations'
import type { ReportCheckRowData } from './reportCheckPresentation'

const STARTED_AT = '2026-10-01T00:00:00Z'

function makeRow(
    timing: Partial<NonNullable<SignalReportCheckApi['monitoring_timing']>>,
    config: Record<string, unknown> = {}
): ReportCheckRowData {
    return {
        check: {
            id: 'check-1',
            config,
            monitoring_timing: {
                state: 'scheduled',
                final_verification_state: null,
                started_at: STARTED_AT,
                ends_at: '2026-10-11T00:00:00Z',
                next_measurement_at: '2026-10-06T00:00:00Z',
                ...timing,
            },
        } as unknown as SignalReportCheckApi,
        reportStatus: 'monitoring',
        tag: { label: 'Scheduled', type: 'primary' },
        detail: '',
        cancelled: false,
        cancellable: true,
    }
}

function observation(id: string, content: CheckObservationContent): ReportCheckObservation {
    return { id, content: { monitoring_started_at: STARTED_AT, observed_value: 1, ...content } }
}

describe('reportCheckObservations', () => {
    it('groups interim measurements under their own check, newest first', () => {
        const artefacts = [
            { id: 'a-old', type: 'check_observation', created_at: '2026-10-01T00:00:00Z', content: { check_id: 'a' } },
            { id: 'b', type: 'check_observation', created_at: '2026-10-02T00:00:00Z', content: { check_id: 'b' } },
            { id: 'a-new', type: 'check_observation', created_at: '2026-10-03T00:00:00Z', content: { check_id: 'a' } },
            { id: 'verdict', type: 'check_result', created_at: '2026-10-04T00:00:00Z', content: { check_id: 'a' } },
        ] as unknown as SignalReportArtefact[]
        const grouped = checkObservationsByCheck(artefacts)
        expect(grouped.get('a')?.map(({ id }) => id)).toEqual(['a-new', 'a-old'])
        expect(grouped.get('b')?.map(({ id }) => id)).toEqual(['b'])
    })

    it('places this window’s measurements and leaves out an earlier Monitoring period’s', () => {
        const timeline = monitoringTimeline(
            makeRow({}),
            [
                observation('latest', { title: 't', measured_at: '2026-10-05T00:00:00Z', matches: false }),
                observation('first', { title: 't', measured_at: '2026-10-02T00:00:00Z', matches: true }),
                observation('earlier-period', {
                    title: 't',
                    measured_at: '2026-09-28T00:00:00Z',
                    monitoring_started_at: '2026-09-25T00:00:00Z',
                    matches: true,
                }),
            ],
            Date.parse('2026-10-06T00:00:00Z')
        )
        expect(timeline).toMatchObject({ elapsed: 0.5, nextPosition: 0.5 })
        expect(timeline?.measurements.map(({ id, position }) => [id, position])).toEqual([
            ['first', 0.1],
            ['latest', 0.4],
        ])
    })

    it.each<
        [
            string,
            Partial<NonNullable<SignalReportCheckApi['monitoring_timing']>>,
            boolean | null,
            string,
            Record<string, unknown>?,
        ]
    >([
        ['an on-track latest measurement', {}, true, 'On track'],
        ['an off-track latest measurement', {}, false, 'Not on track'],
        [
            'an off-track measurement after the last interim run',
            { state: 'no_interim_measurements' },
            false,
            'Not on track',
        ],
        ['a latest measurement that errored', {}, null, 'Scheduled'],
        ['final verification', { state: 'paused', final_verification_state: 'verifying' }, false, 'Scheduled'],
        [
            'a minimum-evidence check short of samples',
            {},
            false,
            'Scheduled',
            { monitoring: { purpose: 'minimum_evidence' } },
        ],
    ])('labels the check from %s', (_, timing, matches, label, config = {}) => {
        const row = makeRow(timing, config)
        const timeline = monitoringTimeline(
            row,
            [observation('latest', { title: 't', measured_at: '2026-10-05T00:00:00Z', matches })],
            Date.parse('2026-10-06T00:00:00Z')
        )
        expect(interimCheckTag(row, timeline).label).toBe(label)
    })
})
