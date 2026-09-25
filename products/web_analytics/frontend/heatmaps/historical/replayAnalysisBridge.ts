import { sessionRecordingDataCoordinatorLogic } from 'scenes/session-recordings/player/sessionRecordingDataCoordinatorLogic'
import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'
import { snapshotDataLogic } from 'scenes/session-recordings/player/snapshotDataLogic'

import { ReplayAnalysisInput, ReplayAnalysisResult, ReplayPageAnalyzer } from './replayPageAnalysis'

declare global {
    interface Window {
        historicalHeatmap?: {
            load: () => void
            ready: () => boolean
            analyze: (input: ReplayAnalysisInput) => Promise<ReplayAnalysisResult>
            render: (windowId: number, timestamp: number, signature?: string[], height?: number) => Promise<boolean>
            scroll: (y: number) => Promise<number>
        }
    }
}

export function installReplayAnalysisBridge(sessionRecordingId: string): () => void {
    let analyzer: ReplayPageAnalyzer | undefined
    window.historicalHeatmap = {
        load: () => snapshotDataLogic.findMounted({ sessionRecordingId })?.actions.loadAllSources(),
        ready: () => !!snapshotDataLogic.findMounted({ sessionRecordingId })?.values.allSourcesLoaded,
        analyze: async (input) => {
            const logic = sessionRecordingDataCoordinatorLogic.findMounted({ sessionRecordingId })
            if (!logic || !window.historicalHeatmap?.ready()) {
                throw new Error('Recording is not ready')
            }
            sessionRecordingPlayerLogic.findMounted({ sessionRecordingId, playerKey: 'exporter' })?.actions.setPause()
            analyzer?.destroy()
            const windows = Object.fromEntries(
                Object.entries(logic.values.playableSnapshotsByWindowId).filter(
                    ([windowId]) => !logic.values.oversizedMutationRanges[Number(windowId)]?.length
                )
            )
            analyzer = new ReplayPageAnalyzer(windows)
            const result = await analyzer.analyze(input)
            result.partial ||=
                Object.keys(windows).length < Object.keys(logic.values.playableSnapshotsByWindowId).length
            return result
        },
        render: async (windowId, timestamp, signature, height) =>
            analyzer?.render(windowId, timestamp, signature, height) ?? false,
        scroll: async (y) => analyzer?.scroll(y) ?? 0,
    }
    return () => {
        analyzer?.destroy()
        delete window.historicalHeatmap
    }
}
