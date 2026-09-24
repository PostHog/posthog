import { dayjs } from 'lib/dayjs'

import type { SessionRecordingRetentionPeriod } from '~/types'

// Mirrors RETENTION_PERIOD_DAYS in posthog/session_recordings/data_retention.py.
const RETENTION_PERIOD_DAYS: Partial<Record<SessionRecordingRetentionPeriod, number>> = {
    '30d': 30,
    '90d': 90,
    '1y': 365,
    '5y': 365 * 5,
}

/**
 * Days this project keeps a recording. An unset period reads as the product default of 30 days;
 * `legacy` has no fixed length, so it reads as null (unknown).
 */
export function recordingRetentionDays(period: SessionRecordingRetentionPeriod | null | undefined): number | null {
    return RETENTION_PERIOD_DAYS[period ?? '30d'] ?? null
}

/**
 * Whether retention has deleted the observed session's recording. An observation is created after
 * its session ends, so an observation older than the retention period means the recording is gone.
 * The reverse does not hold (a backfill can observe a session that was already old), so false means
 * "not provably expired" and the player's own not-found state stays the fallback.
 */
export function recordingLikelyExpired(
    observationCreatedAt: string,
    period: SessionRecordingRetentionPeriod | null | undefined
): boolean {
    const days = recordingRetentionDays(period)
    return days !== null && dayjs(observationCreatedAt).isBefore(dayjs().subtract(days, 'day'))
}
