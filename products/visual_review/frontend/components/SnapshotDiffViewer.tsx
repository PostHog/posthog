import type { SnapshotApi } from '../generated/api.schemas'

interface SnapshotDiffViewerProps {
    snapshot: SnapshotApi
}

export function SnapshotDiffViewer({ snapshot }: SnapshotDiffViewerProps): JSX.Element {
    const baselineUrl = snapshot.baseline_artifact?.download_url
    const currentUrl = snapshot.current_artifact?.download_url
    const diffUrl = snapshot.diff_artifact?.download_url

    return (
        <div className="flex flex-col gap-4">
            <h3 className="text-lg font-semibold">{snapshot.identifier}</h3>
            <div className="grid grid-cols-3 gap-4">
                <div className="flex flex-col gap-2">
                    <span className="text-sm font-medium text-muted">Baseline</span>
                    <div className="border rounded overflow-hidden bg-bg-light">
                        {baselineUrl ? (
                            <img src={baselineUrl} alt="Baseline" className="w-full h-auto" />
                        ) : (
                            <div className="p-4 text-center text-muted">No baseline</div>
                        )}
                    </div>
                </div>
                <div className="flex flex-col gap-2">
                    <span className="text-sm font-medium text-muted">Current</span>
                    <div className="border rounded overflow-hidden bg-bg-light">
                        {currentUrl ? (
                            <img src={currentUrl} alt="Current" className="w-full h-auto" />
                        ) : (
                            <div className="p-4 text-center text-muted">No current</div>
                        )}
                    </div>
                </div>
                <div className="flex flex-col gap-2">
                    <span className="text-sm font-medium text-muted">Diff</span>
                    <div className="border rounded overflow-hidden bg-bg-light">
                        {diffUrl ? (
                            <img src={diffUrl} alt="Diff" className="w-full h-auto" />
                        ) : (
                            <div className="p-4 text-center text-muted">No diff</div>
                        )}
                    </div>
                </div>
            </div>
            {snapshot.diff_percentage !== null && (
                <div className="text-sm text-muted">
                    Diff: {snapshot.diff_percentage.toFixed(2)}% ({snapshot.diff_pixel_count} pixels)
                </div>
            )}
        </div>
    )
}
