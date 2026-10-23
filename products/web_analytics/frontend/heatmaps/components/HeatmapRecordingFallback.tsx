import { useActions, useValues } from 'kea'

import { IconRewindPlay } from '@posthog/icons'
import { LemonBanner, LemonButton, Spinner } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import ViewRecordingsPlaylistButton from 'lib/components/ViewRecordingButton/ViewRecordingsPlaylistButton'
import { colonDelimitedDuration } from 'lib/utils/durations'

import { buildRecordingFiltersForUrl, heatmapRecordingFallbackLogic } from './heatmapRecordingFallbackLogic'

export interface HeatmapRecordingFallbackProps {
    url: string
    showEmptyState?: boolean
    guidedSelection?: boolean
    onRecordingHandoff?: (matchingRecordingCount: number) => void
}

export function HeatmapRecordingFallback({
    url,
    showEmptyState = false,
    guidedSelection = false,
    onRecordingHandoff,
}: HeatmapRecordingFallbackProps): JSX.Element | null {
    const logic = heatmapRecordingFallbackLogic({ url, selectionMode: guidedSelection ? 'guided' : 'default' })
    const { matchingRecordings, matchingRecordingsLoading } = useValues(logic)
    const { openRecording } = useActions(logic)

    if (matchingRecordingsLoading && showEmptyState) {
        return (
            <div className="flex items-center gap-2 text-muted">
                <Spinner /> Looking for recordings from the last 30 days
            </div>
        )
    }

    if (!matchingRecordings?.length) {
        return showEmptyState ? (
            <LemonBanner type="info">
                <div className="flex flex-col gap-2">
                    <p className="mb-0">
                        No recordings of this page in the last 30 days. Try a wider date range in Session replay.
                    </p>
                    <ViewRecordingsPlaylistButton
                        filters={buildRecordingFiltersForUrl(url)}
                        label="Find recordings in Session replay"
                        type="secondary"
                        size="small"
                        className="w-fit"
                        onClick={() => onRecordingHandoff?.(0)}
                        data-attr="heatmap-recording-fallback-view-recordings"
                    />
                </div>
            </LemonBanner>
        ) : null
    }

    return (
        <div className="flex flex-col gap-3">
            <p className="mb-0">
                {guidedSelection
                    ? 'Choose a recording, then pause at the moment you want to analyze.'
                    : 'Open a recording and choose “View heatmap” at the moment you want to analyze.'}
            </p>
            <div className="flex flex-wrap gap-2">
                {matchingRecordings.map((recording) => (
                    <LemonButton
                        key={recording.id}
                        data-attr="heatmap-recording-fallback-open-recording"
                        type="secondary"
                        size="small"
                        icon={<IconRewindPlay />}
                        onClick={() => openRecording(recording)}
                    >
                        <span className="flex items-center gap-1">
                            {guidedSelection ? <span>Choose moment ·</span> : null}
                            <TZLabel time={recording.start_time} />
                            {recording.recording_duration ? (
                                <span className="text-muted">
                                    · {colonDelimitedDuration(recording.recording_duration)}
                                </span>
                            ) : null}
                        </span>
                    </LemonButton>
                ))}
            </div>
        </div>
    )
}
