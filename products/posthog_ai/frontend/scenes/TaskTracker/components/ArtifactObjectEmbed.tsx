import { Dashboard } from 'scenes/dashboard/Dashboard'
import { SessionRecordingPlayer } from 'scenes/session-recordings/player/SessionRecordingPlayer'
import { SessionRecordingPlayerMode } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'

import { Query } from '~/queries/Query/Query'
import { NodeKind } from '~/queries/schema/schema-general'
import { DashboardPlacement, InsightShortId } from '~/types'

import type { PostHogObjectRef } from '../taskRunArtifacts'

/**
 * The live object a reference points at, rendered with the same components its own page uses.
 * Kept in its own module so the insight, dashboard and replay code loads only when one opens.
 */
export default function ArtifactObjectEmbed({ objectKind, objectId }: PostHogObjectRef): JSX.Element | null {
    if (objectKind === 'insight') {
        return (
            <div className="flex min-h-full flex-col p-4">
                <div className="flex min-h-96 flex-1 flex-col rounded-md border border-primary bg-surface-primary">
                    <Query
                        uniqueKey={`task-artifact-${objectId}`}
                        query={{ kind: NodeKind.SavedInsightNode, shortId: objectId as InsightShortId }}
                        embedded
                        readOnly
                    />
                </div>
            </div>
        )
    }
    if (objectKind === 'hogql') {
        // The SQL itself is the object id for this kind.
        return (
            <div className="p-4">
                <Query
                    uniqueKey={`task-artifact-sql-${objectId}`}
                    query={{ kind: NodeKind.DataTableNode, source: { kind: NodeKind.HogQLQuery, query: objectId } }}
                    readOnly
                />
            </div>
        )
    }
    if (objectKind === 'dashboard') {
        return (
            <div className="p-4">
                <Dashboard id={objectId} placement={DashboardPlacement.Builtin} />
            </div>
        )
    }
    if (objectKind === 'replay') {
        return (
            <div className="h-full p-4">
                <SessionRecordingPlayer
                    sessionRecordingId={objectId}
                    playerKey={`task-artifact-${objectId}`}
                    mode={SessionRecordingPlayerMode.Standard}
                    autoPlay={false}
                    noMeta
                    withSidebar={false}
                />
            </div>
        )
    }
    return null
}
