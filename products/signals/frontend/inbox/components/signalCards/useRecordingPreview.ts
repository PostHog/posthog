import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { sessionRecordingInfoLogic } from 'lib/components/ViewRecordingButton/sessionRecordingInfoLogic'
import { RecordingPlayerType, useRecordingButton } from 'lib/components/ViewRecordingButton/ViewRecordingButton'
import { Dayjs } from 'lib/dayjs'

// Long enough for a thumbnail render to land, short enough that a reader still sees the frame appear.
const THUMBNAIL_RETRY_MS = 45_000

export interface RecordingPreviewProps {
    sessionId: string
    /** Instant the player seeks to when the frame is clicked. */
    seekTime?: Dayjs
    /** Image of that moment, shown as the frame's background while it can be fetched. */
    thumbnailSrc?: string
    alt: string
}

export interface RecordingPreviewState {
    /** The thumbnail to show right now, or undefined while waiting for a retry or after giving up. */
    src: string | undefined
    onThumbnailError: () => void
    openRecording: () => void
    disabledReason: JSX.Element | string | null
    hasRecording: boolean | undefined
    recordingCheckLoading: boolean
}

/** Thumbnail retry and recording availability for a recording preview frame, shared by the Lemon and quill frames. */
export function useRecordingPreview({
    sessionId,
    seekTime,
    thumbnailSrc,
}: Omit<RecordingPreviewProps, 'alt'>): RecordingPreviewState {
    // A replay signal reaches the inbox before its frame finishes rendering, so the first fetch usually 404s.
    // One delayed retry covers that; between the two the frame is unmounted, so nothing waits on a dead image.
    const [attempt, setAttempt] = useState(0)
    const [waiting, setWaiting] = useState(false)
    const [gaveUp, setGaveUp] = useState(false)

    useEffect(() => {
        setAttempt(0)
        setWaiting(false)
        setGaveUp(false)
    }, [thumbnailSrc])

    useEffect(() => {
        if (!waiting) {
            return
        }
        const timer = setTimeout(() => {
            setAttempt(1)
            setWaiting(false)
        }, THUMBNAIL_RETRY_MS)
        return () => clearTimeout(timer)
    }, [waiting])

    const onThumbnailError = (): void => (attempt === 0 ? setWaiting(true) : setGaveUp(true))

    const src = thumbnailSrc && !waiting && !gaveUp ? `${thumbnailSrc}?attempt=${attempt}` : undefined

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

    return { src, onThumbnailError, openRecording, disabledReason, hasRecording, recordingCheckLoading }
}
