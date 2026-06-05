import { useActions, useValues } from 'kea'

import { IconBug } from '@posthog/icons'
import { LemonButton, LemonLabel, LemonSwitch } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { superpowersLogic } from 'lib/components/Superpowers/superpowersLogic'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'
import { objectsEqual } from 'lib/utils/objects'

import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { EndpointRequest } from '~/queries/schema/schema-general'
import { isInsightVizNode } from '~/queries/utils'
import { AccessControlLevel, AccessControlResourceType, EndpointType, EndpointVersionType } from '~/types'

import { endpointLogic } from './endpointLogic'
import { endpointSceneLogic, extractBreakdownPropertyNames } from './endpointSceneLogic'

export const EndpointSceneHeader = (): JSX.Element => {
    const {
        endpoint,
        endpointLoading,
        localQuery,
        isMaterialized,
        viewingVersion,
        bucketOverrides,
        debugInfoExpanded,
        dataFreshness,
        optionalBreakdownProperties,
    } = useValues(endpointSceneLogic)
    const { endpointName, endpointDescription } = useValues(endpointLogic)
    const { setEndpointDescription, updateEndpoint } = useActions(endpointLogic)
    const {
        setLocalQuery,
        setDataFreshness,
        setIsMaterialized,
        resetBucketOverrides,
        resetOptionalBreakdownProperties,
        setDebugInfoExpanded,
    } = useActions(endpointSceneLogic)
    const { superpowersEnabled } = useValues(superpowersLogic)

    // SceneTitleSection takes a boolean `canEdit` rather than disabled/disabledReason, so we can't
    // wrap it with AccessControlAction — use the same helper AccessControlAction relies on internally.
    const editAccessDisabledReason = getAccessControlDisabledReason(
        AccessControlResourceType.Endpoint,
        AccessControlLevel.Editor
    )

    // When viewing a non-current version, target that version for updates
    const targetVersion =
        viewingVersion && viewingVersion.version !== endpoint?.current_version ? viewingVersion.version : undefined

    const hasNameChange = endpointName && endpointName !== endpoint?.name
    // When viewing a version, compare against that version's description
    const baseDescription = viewingVersion?.description ?? endpoint?.description
    const hasDescriptionChange = endpointDescription !== null && endpointDescription !== baseDescription
    const hasQueryChange = localQuery !== null
    // When viewing a version, compare against that version's values
    const baseDataFreshness = viewingVersion?.data_freshness_seconds ?? endpoint?.data_freshness_seconds ?? 86400
    const hasDataFreshnessChange = dataFreshness !== baseDataFreshness
    const baseIsMaterialized = viewingVersion?.is_materialized ?? endpoint?.is_materialized
    const hasIsMaterializedChange = isMaterialized !== null && isMaterialized !== baseIsMaterialized
    const baseBucketOverrides = viewingVersion?.bucket_overrides ?? endpoint?.bucket_overrides ?? {}
    const hasBucketOverridesChange = !objectsEqual(bucketOverrides, baseBucketOverrides)
    const baseOptionalBreakdowns =
        viewingVersion?.optional_breakdown_properties ?? endpoint?.optional_breakdown_properties ?? []
    const hasOptionalBreakdownChange = !objectsEqual(
        [...optionalBreakdownProperties].sort(),
        [...baseOptionalBreakdowns].sort()
    )
    const hasChanges =
        hasNameChange ||
        hasDescriptionChange ||
        hasQueryChange ||
        hasDataFreshnessChange ||
        hasIsMaterializedChange ||
        hasBucketOverridesChange ||
        hasOptionalBreakdownChange

    const handleSave = (): void => {
        let queryToSave = (localQuery || endpoint?.query) as any

        if (queryToSave && isInsightVizNode(queryToSave)) {
            queryToSave = queryToSave.source
        }

        if (!endpoint) {
            return
        }

        // Prune the optional list against the query actually being saved — a query edit can
        // remove a breakdown after it was marked optional, and the backend rejects unknown names.
        const savedQueryBreakdowns = extractBreakdownPropertyNames(
            hasQueryChange ? queryToSave : (viewingVersion?.query ?? endpoint.query)
        )
        const prunedOptionalBreakdowns = optionalBreakdownProperties.filter((p) => savedQueryBreakdowns.includes(p))

        const updatePayload: Partial<EndpointRequest> = {
            description: hasDescriptionChange ? endpointDescription : undefined,
            data_freshness_seconds: hasDataFreshnessChange ? dataFreshness : undefined,
            query: hasQueryChange ? queryToSave : undefined,
            is_materialized: hasIsMaterializedChange ? isMaterialized : undefined,
            bucket_overrides: hasBucketOverridesChange ? bucketOverrides : undefined,
            optional_breakdown_properties: hasOptionalBreakdownChange ? prunedOptionalBreakdowns : undefined,
        }

        updateEndpoint(endpoint.name, updatePayload, targetVersion ? { version: targetVersion } : undefined)
    }

    const handleDiscardChanges = (): void => {
        if (!endpoint) {
            return
        }
        // Reset to viewed version values if viewing a specific version
        const sourceDescription = viewingVersion?.description ?? endpoint.description
        const sourceDataFreshness = viewingVersion?.data_freshness_seconds ?? endpoint.data_freshness_seconds ?? 86400
        setEndpointDescription(sourceDescription || '')
        setDataFreshness(sourceDataFreshness)
        setIsMaterialized(null)
        setLocalQuery(null)
        resetBucketOverrides(viewingVersion?.bucket_overrides ?? endpoint.bucket_overrides ?? {})
        resetOptionalBreakdownProperties(
            viewingVersion?.optional_breakdown_properties ?? endpoint.optional_breakdown_properties ?? []
        )
    }

    return (
        <>
            <SceneTitleSection
                name={endpointName || endpoint?.name}
                description={endpointDescription ?? viewingVersion?.description ?? endpoint?.description}
                resourceType={{ type: 'endpoints' }}
                canEdit={!editAccessDisabledReason}
                // onNameChange={} - we explicitly disallow this
                onDescriptionChange={(description) => setEndpointDescription(description)}
                isLoading={endpointLoading && !endpoint}
                renameDebounceMs={200}
                actions={
                    <>
                        {superpowersEnabled && endpoint && (
                            <LemonSwitch
                                bordered
                                checked={debugInfoExpanded}
                                onChange={setDebugInfoExpanded}
                                label={
                                    <span className="inline-flex items-center gap-1">
                                        <IconBug />
                                        Debug info
                                    </span>
                                }
                                tooltip="Visible to staff (and during impersonation) only"
                            />
                        )}
                        {endpoint && (
                            <LemonButton
                                type="secondary"
                                onClick={handleDiscardChanges}
                                disabledReason={!hasChanges && 'No changes to discard'}
                            >
                                Discard changes
                            </LemonButton>
                        )}
                        <AccessControlAction
                            resourceType={AccessControlResourceType.Endpoint}
                            minAccessLevel={AccessControlLevel.Editor}
                        >
                            <LemonButton
                                type="primary"
                                onClick={handleSave}
                                disabledReason={
                                    !endpoint
                                        ? 'Endpoint not loaded'
                                        : !hasChanges
                                          ? 'No changes to save'
                                          : hasQueryChange && targetVersion
                                            ? 'Query can only be changed when on the latest version'
                                            : undefined
                                }
                            >
                                Update
                            </LemonButton>
                        </AccessControlAction>
                    </>
                }
            />
            {superpowersEnabled && endpoint && debugInfoExpanded && (
                <DebugInfoPanel endpoint={endpoint} viewingVersion={viewingVersion} />
            )}
        </>
    )
}

interface DebugInfoPanelProps {
    endpoint: EndpointType
    viewingVersion: EndpointVersionType | null
}

function DebugInfoPanel({ endpoint, viewingVersion }: DebugInfoPanelProps): JSX.Element {
    const savedQueryId = endpoint.materialization?.saved_query_id
    // Prefer the version being viewed; fall back to the endpoint's current version UUID.
    const versionId = viewingVersion?.version_id ?? endpoint.current_version_id

    return (
        <div className="flex flex-col gap-2 border-dashed border rounded p-2 bg-bg-light">
            <div className="inline-flex flex-wrap gap-6">
                <DebugField label="Endpoint ID" value={endpoint.id} />
                {versionId && <DebugField label="Version ID" value={versionId} />}
                {savedQueryId ? (
                    <DebugField label="Saved query ID" value={savedQueryId} />
                ) : (
                    <div className="flex flex-col">
                        <LemonLabel>Saved query ID</LemonLabel>
                        <span className="text-xs text-muted">Not materialized</span>
                    </div>
                )}
            </div>
        </div>
    )
}

function DebugField({ label, value }: { label: string; value: string }): JSX.Element {
    return (
        <div className="flex flex-col">
            <LemonLabel>{label}</LemonLabel>
            <LemonButton
                type="secondary"
                size="xsmall"
                onClick={() => {
                    navigator.clipboard.writeText(value)
                    lemonToast.success(`${label} copied to clipboard`)
                }}
                className="font-mono text-xs"
            >
                {value}
            </LemonButton>
        </div>
    )
}
