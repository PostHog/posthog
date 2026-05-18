import '../styles/tailwind.css'

import type { App } from '@modelcontextprotocol/ext-apps'
import { useCallback, useState } from 'react'
import { createRoot } from 'react-dom/client'

import {
    type ActionState,
    type SnapshotAction,
    type VisualReviewSnapshot,
    type VisualReviewSnapshotsData,
    VisualReviewSnapshotsView,
} from 'products/visual_review/mcp/apps'

import { AppWrapper } from '../components/AppWrapper'

function VisualReviewSnapshotsApp(): JSX.Element {
    return (
        <AppWrapper<VisualReviewSnapshotsData> appName="PostHog Visual Review Snapshots">
            {({ data, app }) => <VisualReviewSnapshotsContent data={data!} app={app} />}
        </AppWrapper>
    )
}

function VisualReviewSnapshotsContent({
    data,
    app,
}: {
    data: VisualReviewSnapshotsData
    app: App | null
}): JSX.Element {
    const [actionStates, setActionStates] = useState<Record<string, ActionState>>({})

    const updateState = useCallback((snapshotId: string, partial: Partial<ActionState>) => {
        setActionStates((prev) => {
            const existing = prev[snapshotId] ?? { loadingAs: null, error: null, succeededAs: null }
            return { ...prev, [snapshotId]: { ...existing, ...partial } }
        })
    }, [])

    const handleAction = useCallback(
        async (snapshot: VisualReviewSnapshot, action: SnapshotAction): Promise<void> => {
            // The view gates Approve on `result === 'changed' | 'new'` and requires
            // a current_artifact to render. If we still landed here without a
            // content_hash, refuse to dispatch rather than silently sending '' to
            // the backend (where it would produce ArtifactNotFoundError).
            if (action === 'approve' && !snapshot.current_artifact?.content_hash) {
                updateState(snapshot.id, {
                    loadingAs: null,
                    error: 'No current artifact to approve.',
                    succeededAs: null,
                })
                return
            }
            if (!app) {
                updateState(snapshot.id, {
                    loadingAs: null,
                    error: 'Actions are not available in this host. Ask the agent to approve or tolerate via chat.',
                    succeededAs: null,
                })
                return
            }
            updateState(snapshot.id, { loadingAs: action, error: null, succeededAs: null })
            try {
                const toolName =
                    action === 'approve' ? 'visual-review-runs-approve-create' : 'visual-review-runs-tolerate-create'
                const args =
                    action === 'approve'
                        ? {
                              id: snapshot.run_id,
                              snapshots: [
                                  {
                                      identifier: snapshot.identifier,
                                      // Guarded above; `!` is safe here.
                                      new_hash: snapshot.current_artifact!.content_hash,
                                  },
                              ],
                              approve_all: false,
                              commit_to_github: true,
                          }
                        : { id: snapshot.run_id, snapshot_id: snapshot.id }

                const result = await app.callServerTool({ name: toolName, arguments: args })
                if (result.isError) {
                    const message = result.content?.find((c) => c.type === 'text')?.text ?? `${action} failed.`
                    updateState(snapshot.id, { loadingAs: null, error: message })
                    return
                }
                updateState(snapshot.id, { loadingAs: null, error: null, succeededAs: action })
            } catch (err) {
                const message = err instanceof Error ? err.message : String(err)
                updateState(snapshot.id, { loadingAs: null, error: message })
            }
        },
        [app, updateState]
    )

    return <VisualReviewSnapshotsView data={data} onAction={handleAction} actionStates={actionStates} />
}

const container = document.getElementById('root')
if (container) {
    createRoot(container).render(<VisualReviewSnapshotsApp />)
}
