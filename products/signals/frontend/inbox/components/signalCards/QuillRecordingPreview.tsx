import { IconPlay } from '@posthog/icons'
import { Spinner, Text, cn } from '@posthog/quill'

import { RecordingPreviewProps, useRecordingPreview } from './useRecordingPreview'

/**
 * Quill sibling of `RecordingPreview`: a 16:9 frame for a moment in a recording that opens the player modal
 * at `seekTime`. Disables itself, instead of opening an empty player, when the recording wasn't captured or has expired.
 */
export function QuillRecordingPreview({ sessionId, seekTime, thumbnailSrc, alt }: RecordingPreviewProps): JSX.Element {
    const { src, onThumbnailError, openRecording, disabledReason, hasRecording, recordingCheckLoading } =
        useRecordingPreview({ sessionId, seekTime, thumbnailSrc })

    return (
        <>
            <button
                type="button"
                onClick={openRecording}
                disabled={!!disabledReason || recordingCheckLoading}
                title={typeof disabledReason === 'string' ? disabledReason : undefined}
                aria-label="Play recording"
                data-attr="inbox-signal-recording-preview"
                className="group relative aspect-video w-full cursor-pointer overflow-hidden rounded-md border border-border bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-default disabled:opacity-70"
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
                        onError={onThumbnailError}
                    />
                )}
                <div
                    className={cn(
                        'absolute inset-0 flex items-center justify-center transition-colors motion-reduce:transition-none',
                        !src && 'group-hover:bg-fill-hover'
                    )}
                >
                    {/* A token-coloured disc keeps the play glyph legible over any frame, in light and dark. */}
                    <span className="flex size-12 items-center justify-center rounded-full bg-background text-foreground shadow-sm">
                        {recordingCheckLoading ? <Spinner /> : <IconPlay className="size-6" aria-hidden />}
                    </span>
                </div>
            </button>
            {hasRecording === false && (
                <Text size="xs" variant="muted" className="m-0">
                    This recording is no longer available.
                </Text>
            )}
        </>
    )
}
