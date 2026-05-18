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
            const existing = prev[snapshotId] ?? { loading: false, error: null, succeededAs: null }
            return { ...prev, [snapshotId]: { ...existing, ...partial } }
        })
    }, [])

    const fallbackToChat = useCallback(
        (snapshot: VisualReviewSnapshot, action: SnapshotAction) => {
            const verb = action === 'approve' ? 'Approve' : 'Tolerate'
            app?.sendMessage({
                role: 'user',
                content: [
                    {
                        type: 'text',
                        text: `${verb} snapshot "${snapshot.identifier}" (id ${snapshot.id}) in run ${snapshot.run_id}.`,
                    },
                ],
            })
        },
        [app]
    )

    const handleAction = useCallback(
        async (snapshot: VisualReviewSnapshot, action: SnapshotAction): Promise<void> => {
            if (!app) {
                fallbackToChat(snapshot, action)
                return
            }
            updateState(snapshot.id, { loading: true, error: null, succeededAs: null })
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
                                      new_hash: snapshot.current_artifact?.content_hash ?? '',
                                  },
                              ],
                              approve_all: false,
                              commit_to_github: true,
                          }
                        : { id: snapshot.run_id, snapshot_id: snapshot.id }

                const result = await app.callServerTool({ name: toolName, arguments: args })
                if (result.isError) {
                    const message = result.content?.find((c) => c.type === 'text')?.text ?? `${action} failed.`
                    updateState(snapshot.id, { loading: false, error: message })
                    return
                }
                updateState(snapshot.id, { loading: false, error: null, succeededAs: action })
            } catch (err) {
                const message = err instanceof Error ? err.message : String(err)
                updateState(snapshot.id, { loading: false, error: message })
            }
        },
        [app, fallbackToChat, updateState]
    )

    return <VisualReviewSnapshotsView data={data} onAction={handleAction} actionStates={actionStates} />
}

const container = document.getElementById('root')
if (container) {
    createRoot(container).render(<VisualReviewSnapshotsApp />)
}
