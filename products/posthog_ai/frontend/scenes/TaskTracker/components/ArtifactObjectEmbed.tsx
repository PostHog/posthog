import { useValues } from 'kea'

import { NotFound } from 'lib/components/NotFound'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { humanFriendlyNumber } from 'lib/utils/numbers'
import { cohortEditLogic } from 'scenes/cohorts/cohortEditLogic'
import { Dashboard } from 'scenes/dashboard/Dashboard'
import { featureFlagLogic } from 'scenes/feature-flags/featureFlagLogic'
import { FeatureFlagReleaseConditionsReadonly } from 'scenes/feature-flags/FeatureFlagReleaseConditionsReadonly'
import { FlagActiveToggleTag } from 'scenes/feature-flags/FlagActiveToggleTag'
import { SessionRecordingPlayer } from 'scenes/session-recordings/player/SessionRecordingPlayer'
import { SessionRecordingPlayerMode } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'

import { Query } from '~/queries/Query/Query'
import { NodeKind } from '~/queries/schema/schema-general'
import { DashboardPlacement, InsightShortId } from '~/types'

import { PRODUCT_OBJECT_EMBEDS, type PostHogObjectRef } from '../taskRunArtifacts'

function EmbedLoading(): JSX.Element {
    return (
        <div className="flex flex-col gap-2 p-4">
            <LemonSkeleton className="h-6 w-48" />
            <LemonSkeleton className="h-32" />
        </div>
    )
}

function FlagEmbed({ id }: { id: number }): JSX.Element {
    const { featureFlag, featureFlagLoading, featureFlagMissing } = useValues(featureFlagLogic({ id }))
    if (featureFlagMissing) {
        return <NotFound object="feature flag" />
    }
    if (featureFlagLoading && !featureFlag.id) {
        return <EmbedLoading />
    }
    return (
        <div className="flex flex-col gap-4 p-4">
            <div className="flex flex-wrap items-center gap-2">
                <span className="font-semibold">{featureFlag.key}</span>
                <FlagActiveToggleTag active={featureFlag.active} />
            </div>
            {featureFlag.is_remote_configuration ? (
                <p className="m-0 text-sm text-secondary">Remote config flags do not use release conditions.</p>
            ) : (
                <FeatureFlagReleaseConditionsReadonly
                    id={String(featureFlag.id)}
                    filters={featureFlag.filters}
                    isDisabled={!featureFlag.active}
                    evaluationRuntime={featureFlag.evaluation_runtime}
                />
            )}
        </div>
    )
}

function CohortEmbed({ id }: { id: number }): JSX.Element {
    const { cohort, cohortLoading, cohortMissing, query } = useValues(cohortEditLogic({ id }))
    if (cohortMissing) {
        return <NotFound object="cohort" />
    }
    if (cohortLoading && cohort.id !== id) {
        return <EmbedLoading />
    }
    return (
        <div className="flex flex-col gap-3 p-4">
            {cohort.count != null ? (
                <span className="text-sm text-secondary">
                    {humanFriendlyNumber(cohort.count)} {cohort.count === 1 ? 'person' : 'persons'}
                </span>
            ) : null}
            <div className="overflow-hidden rounded-md border border-primary bg-surface-primary">
                <Query
                    uniqueKey={`task-artifact-cohort-${id}`}
                    query={{ ...query, full: false, embedded: true, showOpenEditorButton: false }}
                    readOnly
                />
            </div>
        </div>
    )
}

function EmbedBody({ objectKind, objectId }: PostHogObjectRef): JSX.Element | null {
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
    if (objectKind === 'flag') {
        return <FlagEmbed id={Number(objectId)} />
    }
    if (objectKind === 'cohort') {
        return <CohortEmbed id={Number(objectId)} />
    }
    const ProductEmbed = PRODUCT_OBJECT_EMBEDS.get(objectKind)
    return ProductEmbed ? <ProductEmbed objectId={objectId} /> : null
}

/**
 * The live object a reference points at, rendered with the same components its own page uses.
 * Kept in its own module so the insight, dashboard and replay code loads only when one opens.
 */
export function ArtifactObjectEmbed(ref: PostHogObjectRef): JSX.Element {
    // These are LemonUI page components inside the quill artifacts pane, so they need PostHog's own color tokens back.
    return (
        <div data-not-quill className="h-full">
            <EmbedBody {...ref} />
        </div>
    )
}
