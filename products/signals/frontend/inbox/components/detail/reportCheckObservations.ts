import { SignalReportArtefact } from '../../types'
import type { CheckObservationContent } from './artefactTypes'
import type { ReportCheckRowData } from './reportCheckPresentation'

export interface ReportCheckObservation {
    id: string
    content: CheckObservationContent
}

export interface MonitoringTimelineMeasurement {
    id: string
    measuredAt: string
    /** Fraction of the observation window, from 0 at its start to 1 at its end. */
    position: number
    matches: boolean | null
}

export interface MonitoringTimeline {
    startedAt: string
    endsAt: string
    nextMeasurementAt: string | null
    nextPosition: number | null
    elapsed: number
    now: number
    /** Oldest first, so the last entry is the latest measurement. */
    measurements: MonitoringTimelineMeasurement[]
}

/** While the window is open, the latest measurement is more useful than the schedule. */
const INTERIM_TAG_STATES = ['scheduled', 'due', 'no_interim_measurements']

/** Interim measurements per check, newest first. */
export function checkObservationsByCheck(artefacts: SignalReportArtefact[]): Map<string, ReportCheckObservation[]> {
    const observations = new Map<string, ReportCheckObservation[]>()
    const ordered = artefacts
        .filter((artefact) => artefact.type === 'check_observation')
        .sort((a, b) => b.created_at.localeCompare(a.created_at))
    for (const artefact of ordered) {
        const content = artefact.content as CheckObservationContent
        if (!content?.check_id) {
            continue
        }
        observations.set(content.check_id, [
            ...(observations.get(content.check_id) ?? []),
            { id: artefact.id, content },
        ])
    }
    return observations
}

export function monitoringTimeline(
    row: ReportCheckRowData,
    observations: ReportCheckObservation[],
    now: number
): MonitoringTimeline | null {
    const timing = row.reportStatus === 'monitoring' ? row.check.monitoring_timing : null
    const start = Date.parse(timing?.started_at ?? '')
    const end = Date.parse(timing?.ends_at ?? '')
    if (!timing?.started_at || !timing.ends_at || !(end > start)) {
        return null
    }
    const position = (time: number): number => Math.min(Math.max((time - start) / (end - start), 0), 1)
    const next = Date.parse(timing.next_measurement_at ?? '')
    return {
        startedAt: timing.started_at,
        endsAt: timing.ends_at,
        nextMeasurementAt: Number.isFinite(next) ? (timing.next_measurement_at ?? null) : null,
        nextPosition: Number.isFinite(next) ? position(next) : null,
        elapsed: position(now),
        now,
        measurements: observations
            // A restarted Monitoring period keeps the earlier period's measurements, which belong to another window.
            .filter(
                ({ content }) =>
                    content.measured_at &&
                    content.monitoring_started_at &&
                    Date.parse(content.monitoring_started_at) === start
            )
            .map(({ id, content }) => ({
                id,
                measuredAt: content.measured_at as string,
                position: position(Date.parse(content.measured_at as string)),
                matches: typeof content.matches === 'boolean' ? content.matches : null,
            }))
            .sort((a, b) => a.measuredAt.localeCompare(b.measuredAt)),
    }
}

export function interimCheckTag(
    row: ReportCheckRowData,
    timeline: MonitoringTimeline | null
): ReportCheckRowData['tag'] & { description?: string } {
    const timing = row.check.monitoring_timing
    const latest = timeline?.measurements.at(-1)
    if (
        !timing ||
        timing.final_verification_state ||
        !INTERIM_TAG_STATES.includes(timing.state) ||
        latest?.matches == null ||
        // Too few samples on a minimum-evidence check leads to assessment, not to a failed implementation.
        ('monitoring' in row.check.config && row.check.config.monitoring?.purpose === 'minimum_evidence')
    ) {
        return row.tag
    }
    return latest.matches
        ? {
              label: 'On track',
              type: 'success',
              description: 'This report will be resolved at the end of the monitoring window if the goal is met.',
          }
        : {
              label: 'Not on track',
              type: 'warning',
              description:
                  'If this metric fails at the end of the monitoring window, a new report will be opened to research why and attempt a new solution.',
          }
}
