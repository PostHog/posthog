import { dayjs } from 'lib/dayjs'

// The shortest retention period the product offers (see posthog/session_recordings/data_retention.py).
const MIN_RETENTION_DAYS = 30

/**
 * Whether retention could have deleted this observation's recording. A recording keeps the retention
 * period it was captured under and the team setting can change afterwards, so age against the current
 * setting proves nothing; it only rules expiry out for sessions younger than every offered period.
 * An observation is created after its session ends, so a fresh observation's recording still exists.
 * For older ones, confirm absence against the recordings API before claiming expiry.
 */
export function couldRecordingBeExpired(observationCreatedAt: string): boolean {
    return dayjs(observationCreatedAt).isBefore(dayjs().subtract(MIN_RETENTION_DAYS, 'day'))
}
