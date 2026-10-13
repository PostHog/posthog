import { IconClock } from '@posthog/icons'
import { LemonTag, Tooltip } from '@posthog/lemon-ui'

/**
 * Render only after the recordings API confirmed the observed session's recording no longer exists.
 * `compact` drops the label to the clock icon for the small list thumbnail; the tooltip keeps the text.
 */
export function RecordingExpiredTag({ compact = false }: { compact?: boolean }): JSX.Element {
    return (
        <Tooltip title="This recording was deleted when it passed its retention period. The analysis is still available, but the recording can no longer be played.">
            <LemonTag icon={<IconClock />} type="muted" size="small" data-attr="vision-recording-expired-tag">
                {!compact && 'Recording expired'}
            </LemonTag>
        </Tooltip>
    )
}
