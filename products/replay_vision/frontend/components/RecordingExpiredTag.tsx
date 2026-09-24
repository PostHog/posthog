import { IconClock } from '@posthog/icons'
import { LemonTag, Tooltip } from '@posthog/lemon-ui'

/** Render only after the recordings API confirmed the observed session's recording no longer exists. */
export function RecordingExpiredTag(): JSX.Element {
    return (
        <Tooltip title="This recording was deleted when it passed its retention period. The analysis is still available, but the recording can no longer be played.">
            <LemonTag icon={<IconClock />} type="muted" size="small" data-attr="vision-recording-expired-tag">
                Recording expired
            </LemonTag>
        </Tooltip>
    )
}
