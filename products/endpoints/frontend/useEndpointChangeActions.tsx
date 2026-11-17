import { useActions, useValues } from 'kea'

import { IconBug, IconCheck, IconUndo } from '@posthog/icons'

import { superpowersLogic } from 'lib/components/Superpowers/superpowersLogic'
import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'
import { objectsEqual } from 'lib/utils/objects'

import type { SceneAction } from '~/layout/scenes/sceneActions/sceneActionModel'
import { isInsightVizNode } from '~/queries/schema/node-guards'
import { EndpointRequest } from '~/queries/schema/schema-general'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { endpointLogic } from './endpointLogic'
import { endpointSceneLogic, extractBreakdownPropertyNames } from './endpointSceneLogic'

const RESOURCE_TYPE = 'endpoint'

/**
 * Save, discard and the staff debug toggle, the title row's actions, as scene actions. The change detection and the
 * save payload mirror `EndpointSceneHeader`, which keeps its own copy for the title row with the flag off.
 */
export function useEndpointChangeActions(): SceneAction[] {
    const {
        endpoint,
        localQuery,
        isMaterialized,
        viewingVersion,
        bucketOverrides,
        debugInfoExpanded,
        dataFreshness,
        optionalBreakdownProperties,
    } = useValues(endpointSceneLogic)
    const { endpointName, endpointDescription, updatingEndpoint } = useValues(endpointLogic)
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

    if (!endpoint) {
        return []
    }

    const targetVersion =
        viewingVersion && viewingVersion.version !== endpoint.current_version ? viewingVersion.version : undefined
    const hasNameChange = endpointName && endpointName !== endpoint.name
    const baseDescription = viewingVersion?.description ?? endpoint.description
    const hasDescriptionChange = endpointDescription !== null && endpointDescription !== baseDescription
    const hasQueryChange = localQuery !== null
    const baseDataFreshness = viewingVersion?.data_freshness_seconds ?? endpoint.data_freshness_seconds ?? 86400
    const hasDataFreshnessChange = dataFreshness !== baseDataFreshness
    const baseIsMaterialized = viewingVersion?.is_materialized ?? endpoint.is_materialized
    const hasIsMaterializedChange = isMaterialized !== null && isMaterialized !== baseIsMaterialized
    const baseBucketOverrides = viewingVersion?.bucket_overrides ?? endpoint.bucket_overrides ?? {}
    const hasBucketOverridesChange = !objectsEqual(bucketOverrides, baseBucketOverrides)
    const baseOptionalBreakdowns =
        viewingVersion?.optional_breakdown_properties ?? endpoint.optional_breakdown_properties ?? []
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

    const save = (): void => {
        let queryToSave = (localQuery || endpoint.query) as any
        if (queryToSave && isInsightVizNode(queryToSave)) {
            queryToSave = queryToSave.source
        }
        // A query edit can remove a breakdown after it was marked optional, and the backend rejects unknown names.
        const savedQueryBreakdowns = extractBreakdownPropertyNames(
            hasQueryChange ? queryToSave : (viewingVersion?.query ?? endpoint.query)
        )
        const updatePayload: Partial<EndpointRequest> = {
            description: hasDescriptionChange ? endpointDescription : undefined,
            data_freshness_seconds: hasDataFreshnessChange ? dataFreshness : undefined,
            query: hasQueryChange ? queryToSave : undefined,
            is_materialized: hasIsMaterializedChange ? isMaterialized : undefined,
            bucket_overrides: hasBucketOverridesChange ? bucketOverrides : undefined,
            optional_breakdown_properties: hasOptionalBreakdownChange
                ? optionalBreakdownProperties.filter((p) => savedQueryBreakdowns.includes(p))
                : undefined,
        }
        updateEndpoint(endpoint.name, updatePayload, targetVersion ? { version: targetVersion } : undefined)
    }

    const discard = (): void => {
        setEndpointDescription(baseDescription || '')
        setDataFreshness(baseDataFreshness)
        setIsMaterialized(null)
        setLocalQuery(null)
        resetBucketOverrides(baseBucketOverrides)
        resetOptionalBreakdownProperties(baseOptionalBreakdowns)
    }

    const saveDisabledReason =
        getAccessControlDisabledReason(AccessControlResourceType.Endpoint, AccessControlLevel.Editor) ??
        (updatingEndpoint
            ? 'Update in progress'
            : !hasChanges
              ? 'No changes to save'
              : hasQueryChange && targetVersion
                ? 'Query can only be changed when on the latest version'
                : undefined)

    return [
        {
            group: 'edit',
            section: 'changes',
            id: `${RESOURCE_TYPE}-menubar-save-changes`,
            label: 'Save changes',
            icon: <IconCheck />,
            disabledReason: saveDisabledReason,
            onSelect: save,
            pinned: { order: 3, variant: 'primary' },
        },
        {
            group: 'edit',
            section: 'changes',
            id: `${RESOURCE_TYPE}-menubar-discard-changes`,
            label: 'Discard changes',
            icon: <IconUndo />,
            disabledReason: hasChanges ? undefined : 'No changes to discard',
            onSelect: discard,
            pinned: { order: 2, variant: 'secondary' },
        },
        ...(superpowersEnabled
            ? ([
                  {
                      group: 'staff',
                      type: 'checkbox',
                      id: `${RESOURCE_TYPE}-menubar-debug-info`,
                      label: 'Debug info',
                      icon: <IconBug />,
                      tooltip: 'Visible to staff (and during impersonation) only',
                      checked: debugInfoExpanded,
                      onCheckedChange: setDebugInfoExpanded,
                      pinned: { order: 1, variant: 'secondary' },
                  },
              ] satisfies SceneAction[])
            : []),
    ]
}
