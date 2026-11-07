import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { IconPlay } from '@posthog/icons'
import { Button, type ButtonProps } from '@posthog/quill'

import { sessionRecordingInfoLogic } from 'lib/components/ViewRecordingButton/sessionRecordingInfoLogic'
import { RecordingPlayerType, useRecordingButton } from 'lib/components/ViewRecordingButton/ViewRecordingButton'
import { Dayjs } from 'lib/dayjs'

/**
 * Quill stand-in for `ViewRecordingButton` in the signal cards: opens the recording in the player modal
 * at `timestamp`, and disables with the reason when the recording wasn't captured.
 */
export function QuillSignalRecordingButton({
    sessionId,
    timestamp,
    label,
    checkRecordingExists = false,
    variant,
    size,
    loading,
    className,
}: {
    sessionId: string
    timestamp?: Dayjs
    label: React.ReactNode
    /** Check via the batched API whether the recording exists, and disable when it doesn't. */
    checkRecordingExists?: boolean
    variant?: ButtonProps['variant']
    size?: ButtonProps['size']
    loading?: boolean
    className?: string
}): JSX.Element {
    const { checkRecordingInfo } = useActions(sessionRecordingInfoLogic)
    const { getRecordingExists } = useValues(sessionRecordingInfoLogic)

    useEffect(() => {
        if (checkRecordingExists && sessionId) {
            checkRecordingInfo(sessionId)
        }
    }, [checkRecordingExists, sessionId, checkRecordingInfo])

    const { onClick, disabledReason } = useRecordingButton({
        sessionId,
        timestamp,
        openPlayerIn: RecordingPlayerType.Modal,
        hasRecording: checkRecordingExists && sessionId ? getRecordingExists(sessionId) : undefined,
    })

    return (
        <Button
            variant={variant}
            size={size}
            loading={loading}
            disabledReason={disabledReason}
            onClick={onClick}
            className={className}
            data-ph-capture-attribute-view-recording-checked-existence={checkRecordingExists}
        >
            {label}
            <IconPlay />
        </Button>
    )
}
