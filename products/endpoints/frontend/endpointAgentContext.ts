import { deepEqual } from 'fast-equals'

import type { AttachedContextItem } from 'products/posthog_ai/frontend/api/types'

import type { endpointSceneLogicValues } from './endpointSceneLogic'

type EndpointEditorState = Pick<
    endpointSceneLogicValues,
    | 'endpoint'
    | 'viewingVersion'
    | 'localQuery'
    | 'dataFreshness'
    | 'isMaterialized'
    | 'bucketOverrides'
    | 'optionalBreakdownProperties'
> & { endpointDescription: string | null }

export function hasUnsavedEndpointChanges(state: EndpointEditorState): boolean {
    const base = state.viewingVersion ?? state.endpoint
    return (
        !!base &&
        (state.localQuery !== null ||
            (state.endpointDescription !== null && state.endpointDescription !== (base.description ?? '')) ||
            state.dataFreshness !== (base.data_freshness_seconds ?? 86400) ||
            (state.isMaterialized !== null && state.isMaterialized !== base.is_materialized) ||
            !deepEqual(state.bucketOverrides, base.bucket_overrides ?? {}) ||
            !deepEqual(
                [...state.optionalBreakdownProperties].sort(),
                [...(base.optional_breakdown_properties ?? [])].sort()
            ))
    )
}

const ENDPOINT_INSTRUCTIONS: AttachedContextItem = {
    type: 'instructions',
    hidden: true,
    dismissGroup: 'endpoint-scene',
    value:
        'The user has an endpoint open. The latest endpoint_scene_state names the endpoint, selected version, ' +
        'and tab; use it for references to "this endpoint". Fetch saved details with endpoint-get, passing the ' +
        'selected version. Use endpoint-logs for failures, endpoint-materialization-status and ' +
        'endpoints-materialization-preview for materialization, endpoint-versions for history, and ' +
        'endpoint-openapi-spec for client examples. Load the creating-an-endpoint, diagnosing-endpoint-performance, ' +
        'managing-endpoint-versions, or consuming-endpoints-from-client-code skill when relevant. ' +
        'Unsaved SQL, when attached as sql_editor_state, takes precedence over the saved query. ' +
        'For SQL suggestions use execute-sql: the open SQL editor shows an accept/reject diff. Do not save ' +
        'a suggestion with endpoint-update unless the user asks to save it. Query updates immediately create ' +
        'the latest version used by unpinned callers; there is no draft/publish stage. Settings updates can ' +
        'target a specific version. Explain that effect before a write. Approved endpoint updates refresh ' +
        'the page unless the user has unsaved work, in which case the page offers a reload. If unsaved changes ' +
        'are indicated but their contents are not attached, ask for them instead of assuming the saved state. ' +
        'Use placeholder credentials in client examples; never ask the user to paste an API key into chat.',
}

export function buildEndpointAgentContext(
    endpoint: endpointSceneLogicValues['endpoint'],
    viewingVersion: endpointSceneLogicValues['viewingVersion'],
    activeTab: string,
    hasUnsavedChanges: boolean
): AttachedContextItem[] | null {
    if (!endpoint) {
        return null
    }
    const version = viewingVersion?.version ?? endpoint.current_version
    return [
        ENDPOINT_INSTRUCTIONS,
        {
            type: 'endpoint',
            key: endpoint.name,
            label: `${endpoint.name} · v${version}`,
            dismissGroup: 'endpoint-scene',
        },
        {
            type: 'text',
            hidden: true,
            dismissGroup: 'endpoint-scene',
            value: JSON.stringify({
                endpoint_scene_state: {
                    name: endpoint.name,
                    version,
                    tab: activeTab,
                    has_unsaved_changes: hasUnsavedChanges,
                },
            }),
        },
    ]
}

export const ENDPOINT_AI_PROMPTS: Record<string, string[]> = {
    query: ['Explain this endpoint’s query', 'Help me change this endpoint’s query'],
    configuration: ['Can this endpoint be faster?', 'Explain this endpoint’s materialization settings'],
    versions: ['Compare this version with the latest version', 'Explain how to restore an older endpoint query'],
    playground: ['Help me call this endpoint from my app', 'Explain this endpoint’s parameters'],
    logs: ['Investigate recent failures for this endpoint', 'Why is this endpoint slow?'],
    history: ['Explain this endpoint’s current configuration', 'Compare this endpoint’s query versions'],
}
