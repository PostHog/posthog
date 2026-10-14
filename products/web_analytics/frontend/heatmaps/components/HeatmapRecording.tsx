import { BindLogic, useActions, useValues } from 'kea'
import { useRef } from 'react'

import { LemonBanner, LemonDivider, LemonInput, LemonLabel, LemonSegmentedButton } from '@posthog/lemon-ui'

import { hasWildcard, heatmapPageUrl } from 'lib/components/heatmaps/heatmapUrlMatch'
import type { HeatmapUrlFilter, HeatmapUrlMatchMode } from 'lib/components/heatmaps/heatmapUrlMatch'
import ViewRecordingsPlaylistButton from 'lib/components/ViewRecordingButton/ViewRecordingsPlaylistButton'

import { SceneContent } from '~/layout/scenes/components/SceneContent'

import { ClickmapSettings } from './ClickmapSettings'
import { FilterPanel } from './FilterPanel'
import { FixedReplayHeatmapBrowser } from './FixedReplayHeatmapBrowser'
import { heatmapsBrowserLogic } from './heatmapsBrowserLogic'
import { HeatmapsWarnings } from './HeatmapsWarnings'

function urlMatchSummary(
    url: string | undefined,
    urlFilter: HeatmapUrlFilter | null,
    mode: HeatmapUrlMatchMode
): string {
    if (!url?.trim()) {
        return 'Enter the URL of the page to show data for.'
    }
    if (!urlFilter) {
        return 'Enter a full URL, starting with https://'
    }
    if (hasWildcard(url)) {
        return 'Shows every URL that fits this pattern. * stands for any text, everything else is matched as written.'
    }
    if (mode === 'page') {
        return `Shows every visit to ${heatmapPageUrl(url) ?? 'this page'}, whatever the query string.`
    }
    return 'Shows only visits to this exact URL, including its query string.'
}

function UrlSearchHeader(): JSX.Element {
    const logic = heatmapsBrowserLogic()
    const { replayIframeData, recordingUrlFilter, recordingUrlMatchMode } = useValues(logic)
    const { setReplayIframeDataURL, setRecordingUrlMatchMode } = useActions(logic)
    const isWildcard = hasWildcard(replayIframeData?.url ?? '')

    return (
        <div className="mt-2 w-full">
            <LemonLabel htmlFor="heatmap-recording-data-url">Heatmap data URL</LemonLabel>
            <div className="text-xs text-muted mb-1">Add * for wildcards to aggregate data from multiple pages</div>
            <div className="flex flex-wrap items-center gap-2">
                <LemonInput
                    id="heatmap-recording-data-url"
                    value={replayIframeData?.url}
                    onChange={(s) => setReplayIframeDataURL(s)}
                    className="truncate flex-1 min-w-60"
                    size="small"
                    data-attr="heatmap-recording-data-url"
                />
                <LemonSegmentedButton
                    size="small"
                    value={recordingUrlMatchMode}
                    onChange={(mode) => setRecordingUrlMatchMode(mode)}
                    disabledReason={isWildcard ? 'A URL with * is always matched as a pattern' : undefined}
                    options={[
                        { value: 'page', label: 'This page', 'data-attr': 'heatmap-recording-match-page' },
                        { value: 'exact', label: 'Exact URL', 'data-attr': 'heatmap-recording-match-exact' },
                    ]}
                />
            </div>
            <div className="text-xs text-muted mt-1">
                {urlMatchSummary(replayIframeData?.url, recordingUrlFilter, recordingUrlMatchMode)}
            </div>
        </div>
    )
}

export function HeatmapRecording({ embedded = false }: { embedded?: boolean }): JSX.Element {
    const iframeRef = useRef<HTMLIFrameElement | null>(null)

    const logicProps = { ref: iframeRef }

    const logic = heatmapsBrowserLogic({ iframeRef })

    const { hasValidReplayIframeData } = useValues(logic)

    if (!hasValidReplayIframeData) {
        return (
            <LemonBanner type="warning" dismissKey="heatmaps-no-replay-iframe-data-warning">
                <div className="flex items-center justify-between gap-4">
                    <p>This view is based on session recording data. Please open a session recording to view it.</p>
                    <ViewRecordingsPlaylistButton filters={{}} type="secondary" size="small" />
                </div>
            </LemonBanner>
        )
    }

    const content = (
        <>
            <HeatmapsWarnings />
            <div className="overflow-hidden w-full min-h-screen">
                <UrlSearchHeader />
                <LemonDivider className="my-4" />
                <FilterPanel clickmapSettings={<ClickmapSettings iframeRef={iframeRef} />} />
                <LemonDivider className="my-4" />
                <div className="relative flex flex-1 overflow-hidden min-h-screen">
                    <FixedReplayHeatmapBrowser iframeRef={iframeRef} />
                </div>
            </div>
        </>
    )

    return (
        <BindLogic logic={heatmapsBrowserLogic} props={logicProps}>
            {embedded ? content : <SceneContent>{content}</SceneContent>}
        </BindLogic>
    )
}
