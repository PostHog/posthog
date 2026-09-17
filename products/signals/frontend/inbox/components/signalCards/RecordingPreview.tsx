import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { IconPlay } from '@posthog/icons'
import { Spinner } from '@posthog/lemon-ui'

import { sessionRecordingInfoLogic } from 'lib/components/ViewRecordingButton/sessionRecordingInfoLogic'
import { RecordingPlayerType, useRecordingButton } from 'lib/components/ViewRecordingButton/ViewRecordingButton'
import { Dayjs } from 'lib/dayjs'

interface RecordingPreviewProps {
    sessionId: string
    /** Instant the player seeks to when the frame is clicked. */
    seekTime?: Dayjs
    /** Image of that moment, shown as the frame's background while it can be fetched. */
    thumbnailSrc?: string
    alt: string
}

/**
 * 16:9 preview frame for a moment in a recording. The whole frame is the play affordance: clicking
 * it opens the recording in the player modal at `seekTime`. Disables itself, instead of opening an
 * empty player, when the recording wasn't captured or has expired.
 */
export function RecordingPreview({ sessionId, seekTime, thumbnailSrc, alt }: RecordingPreviewProps): JSX.Element {
    const [thumbnailFailed, setThumbnailFailed] = useState(false)

    const src = thumbnailFailed ? undefined : thumbnailSrc

    const { checkRecordingInfo } = useActions(sessionRecordingInfoLogic)
    const { getRecordingExists, isRecordingExistsLoading } = useValues(sessionRecordingInfoLogic)
    useEffect(() => {
        checkRecordingInfo(sessionId)
    }, [sessionId, checkRecordingInfo])
    const hasRecording = getRecordingExists(sessionId)
    const recordingCheckLoading = isRecordingExistsLoading(sessionId)

    const { onClick: openRecording, disabledReason } = useRecordingButton({
        sessionId,
        timestamp: seekTime,
        openPlayerIn: RecordingPlayerType.Modal,
        hasRecording,
    })

    return (
        <>
            <button
                type="button"
                onClick={openRecording}
                disabled={!!disabledReason || recordingCheckLoading}
                title={typeof disabledReason === 'string' ? disabledReason : undefined}
                aria-label="Play recording"
                data-attr="inbox-signal-recording-preview"
                className="group relative w-full aspect-video rounded overflow-hidden border bg-surface-secondary mb-2 cursor-pointer disabled:cursor-default disabled:opacity-70"
            >
                {src && (
                    // Defer this full-frame screenshot: the evidence rail opens expanded and can hold
                    // one preview per replay signal, so eager loading fetches frames never scrolled to.
                    <img
                        src={src}
                        alt={alt}
                        className="absolute inset-0 size-full object-cover"
                        loading="lazy"
                        decoding="async"
                        onError={() => setThumbnailFailed(true)}
                    />
                )}
                <div
                    className={clsx(
                        'absolute inset-0 flex items-center justify-center transition-colors motion-reduce:transition-none',
                        src ? 'bg-black/20 group-hover:bg-black/30' : 'group-hover:bg-fill-highlight-100'
                    )}
                >
                    {recordingCheckLoading ? (
                        <Spinner className={clsx('text-2xl', src ? 'text-white' : 'text-tertiary')} />
                    ) : (
                        <IconPlay
                            className={clsx('size-10 drop-shadow', src ? 'text-white' : 'text-tertiary')}
                            aria-hidden
                        />
                    )}
                </div>
            </button>
            {hasRecording === false && (
                <p className="text-xs text-tertiary mb-2">This recording is no longer available.</p>
            )}
        </>
    )
}
