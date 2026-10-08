import { useActions, useValues } from 'kea'
import React from 'react'

import { HeatmapCanvas } from 'lib/components/heatmaps/HeatmapCanvas'
import { ReplaySnapshotFrame } from 'scenes/session-recordings/player/ReplaySnapshotFrame'

import { heatmapsBrowserLogic } from './heatmapsBrowserLogic'
import { RecordingClickmapOverlay } from './RecordingClickmapOverlay'

export function FixedReplayHeatmapBrowser({
    iframeRef,
}: {
    iframeRef?: React.MutableRefObject<HTMLIFrameElement | null>
}): JSX.Element | null {
    const logic = heatmapsBrowserLogic()

    const { replayIframeData, hasValidReplayIframeData, widthOverride, heightOverride } = useValues(logic)
    const { onIframeLoad } = useActions(logic)

    return hasValidReplayIframeData ? (
        <div className="flex flex-row gap-x-2 w-full">
            <div className="relative flex-1 w-full h-full">
                <div className="flex justify-center h-full w-full overflow-auto">
                    <div
                        className="relative"
                        // eslint-disable-next-line react/forbid-dom-props
                        style={{ width: widthOverride, height: heightOverride }}
                    >
                        <HeatmapCanvas positioning="absolute" widthOverride={widthOverride} context="in-app" />
                        <RecordingClickmapOverlay iframeRef={iframeRef} />
                        <ReplaySnapshotFrame
                            id="heatmap-iframe"
                            snapshotRef={iframeRef}
                            title="Heatmap replay browser"
                            className="bg-white"
                            style={{ width: widthOverride, height: heightOverride }}
                            html={replayIframeData?.html ?? ''}
                            // allow-same-origin lets the app measure the snapshot's elements for the
                            // clickmap overlay. NEVER add allow-scripts: combined with allow-same-origin
                            // that would let recorded customer-page content run script on the app origin.
                            // The app only ever reads geometry from the snapshot, never its content.
                            sandbox="allow-same-origin"
                            onSnapshotLoad={onIframeLoad}
                        />
                    </div>
                </div>
            </div>
        </div>
    ) : null
}
