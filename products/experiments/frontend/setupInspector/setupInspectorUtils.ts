import { isEventPropertyFilter, isPersonPropertyFilter } from 'lib/components/PropertyFilters/utils'
import { dayjs } from 'lib/dayjs'
import { humanFriendlyNumber, percentage } from 'lib/utils/numbers'

import { AnyPropertyFilter, PropertyFilterType } from '~/types'

import type {
    EventPropertyFilterApi,
    ExperimentSetupContextInputApi,
    ExperimentSetupContextResponseApi,
    PersonPropertyFilterApi,
    PropertyOperatorApi,
    SetupContextSectionStatusEnumApi,
    _ExperimentSetupPropertyFilterListApi,
} from 'products/experiments/frontend/generated/api.schemas'

export const SECTION_STATUS_LABELS: Record<SetupContextSectionStatusEnumApi, string> = {
    ok: 'OK',
    skipped: 'Skipped',
    timed_out: 'Timed out',
    error: 'Error',
}

export interface SetupInspectorInputs {
    targetEvent: string | null
    targetUrlContains: string
    targetProperties: AnyPropertyFilter[]
    metricEvent: string | null
    metricProperties: AnyPropertyFilter[]
    previousExperimentsLimit: number
    sharedMetricsLimit: number
}

export const DEFAULT_SETUP_INSPECTOR_INPUTS: SetupInspectorInputs = {
    targetEvent: null,
    targetUrlContains: '',
    targetProperties: [],
    metricEvent: null,
    metricProperties: [],
    previousExperimentsLimit: 10,
    sharedMetricsLimit: 10,
}

export interface IdentityFact {
    label: string
    value: string
}

// Staff see the inspector on the same terms as the experiment debug panel, and only with the flag on.
// Under impersonation the flags and the user are the customer's, so the button shows and the endpoint
// decides, because it evaluates the flag for the staff user behind the session.
export function canInspectSetupContext({
    isImpersonated,
    superpowersEnabled,
    flagEnabled,
}: {
    isImpersonated: boolean
    superpowersEnabled: boolean
    flagEnabled: boolean
}): boolean {
    return isImpersonated || (superpowersEnabled && flagEnabled)
}

// The endpoint accepts only event and person filters, so the other filter types the picker can
// produce are dropped here instead of failing the whole request with a 400.
export function toApiPropertyFilters(filters: AnyPropertyFilter[]): _ExperimentSetupPropertyFilterListApi {
    return filters.flatMap((filter): (EventPropertyFilterApi | PersonPropertyFilterApi)[] => {
        if (!isEventPropertyFilter(filter) && !isPersonPropertyFilter(filter)) {
            return []
        }
        const base = {
            key: filter.key,
            operator: filter.operator as PropertyOperatorApi,
            value: filter.value as EventPropertyFilterApi['value'],
        }
        return [
            filter.type === PropertyFilterType.Event
                ? { ...base, type: 'event' as const }
                : { ...base, type: 'person' as const },
        ]
    })
}

// A field that depends on an event the inspector no longer has is left out, so a stale value in a
// disabled input does not turn the request into a 400.
export function toSetupContextInput(inputs: SetupInspectorInputs): ExperimentSetupContextInputApi {
    const targetProperties = inputs.targetEvent ? toApiPropertyFilters(inputs.targetProperties) : []
    const metricProperties = inputs.metricEvent ? toApiPropertyFilters(inputs.metricProperties) : []
    const targetUrlContains = inputs.targetEvent === '$pageview' ? inputs.targetUrlContains.trim() : ''
    return {
        target_event: inputs.targetEvent || null,
        target_url_contains: targetUrlContains || null,
        target_properties: targetProperties.length ? targetProperties : null,
        metric_event: inputs.metricEvent || null,
        metric_properties: metricProperties.length ? metricProperties : null,
        previous_experiments_limit: inputs.previousExperimentsLimit,
        shared_metrics_limit: inputs.sharedMetricsLimit,
    }
}

export function describeSetupContextError(error: unknown): string {
    const { status, detail, attr } = (error ?? {}) as { status?: number; detail?: string; attr?: string }
    if (status === 404) {
        return 'The setup context is off for you. Turn on the experiment-setup-context feature flag for your user, then try again.'
    }
    if (status === 400 && detail) {
        return attr ? `${attr}: ${detail}` : detail
    }
    return detail || "Couldn't read the setup context. Try again, and check the server logs if it keeps failing."
}

export function formatShare(share: number | null | undefined): string {
    return share === null || share === undefined ? 'Not reported' : percentage(share, 1)
}

export function formatCount(count: number | null | undefined): string {
    return count === null || count === undefined ? 'Not reported' : humanFriendlyNumber(count)
}

export function formatYesNo(value: boolean): string {
    return value ? 'Yes' : 'No'
}

// Absolute times, because a reader compares a launch date against a result date in the same row.
export function formatTimestamp(timestamp: string | null | undefined): string {
    return timestamp ? dayjs(timestamp).format('D MMM YYYY HH:mm') : 'None'
}

export function formatPropertyFilters(filters: _ExperimentSetupPropertyFilterListApi): string {
    if (!filters.length) {
        return 'None'
    }
    return filters
        .map((filter) => {
            const value = Array.isArray(filter.value) ? filter.value.join(' or ') : String(filter.value ?? '')
            return `${filter.type ?? 'event'} ${filter.key} ${filter.operator ?? 'exact'} ${value}`.trim()
        })
        .join('; ')
}

function formatLibShares(libs: { lib: string | null; share: number | null }[], emptyText: string): string {
    const reported = libs.filter((lib) => lib.share !== null)
    if (!reported.length) {
        return emptyText
    }
    return reported.map((lib) => `${lib.lib ?? 'unknown'} ${formatShare(lib.share)}`).join(', ')
}

// Support answers identity and bucketing tickets from server-and-web evaluation, local evaluation and
// the anonymous share, so the drawer shows them first. Each value restates fields of the response and
// adds no threshold of its own.
export function summarizeIdentity(context: ExperimentSetupContextResponseApi): IdentityFact[] {
    const sdk = context.sdk_profile.status === 'ok' ? context.sdk_profile.data : null
    const surface = context.target_surface.status === 'ok' ? context.target_surface.data : null
    const sdkUnavailable = `SDK profile: ${SECTION_STATUS_LABELS[context.sdk_profile.status].toLowerCase()}`

    return [
        {
            label: 'Same flag evaluated on a server and on the web',
            value: sdk
                ? `${formatYesNo(sdk.evaluated_on_server_and_web)} (${formatCount(sdk.flags_evaluated_on_server_and_web)} of ${formatCount(sdk.flags_seen)} flags)`
                : sdkUnavailable,
        },
        {
            label: 'Evaluated locally, by SDK',
            value: sdk
                ? formatLibShares(
                      sdk.libs.map((lib) => ({ lib: lib.lib, share: lib.locally_evaluated_share })),
                      'No SDK reports local evaluation'
                  )
                : sdkUnavailable,
        },
        {
            label: 'Anonymous share of flag calls, by SDK',
            value: sdk
                ? formatLibShares(
                      sdk.libs.map((lib) => ({ lib: lib.lib, share: lib.anonymous_share })),
                      'No SDK reports whether users are identified'
                  )
                : sdkUnavailable,
        },
        {
            label: 'Anonymous share on the target surface',
            value: surface
                ? formatShare(surface.anonymous_share)
                : `Target surface: ${SECTION_STATUS_LABELS[context.target_surface.status].toLowerCase()}`,
        },
    ]
}
