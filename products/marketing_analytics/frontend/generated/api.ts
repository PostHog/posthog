import { apiMutator } from '../../../../frontend/src/lib/api-orval-mutator'
/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import type {
    ApplySetupOpsApi,
    ApplySetupOpsResponseApi,
    ConversionGoalWriteApi,
    ConversionGoalWriteResponseApi,
    ConversionGoalsListResponseApi,
    DataSourceHealthResponseApi,
    EventSuggestionsResponseApi,
    GoalExplanationApi,
    MarketingAnalyticsDataSourcesRetrieveParams,
    MarketingAnalyticsDiagnoseRetrieveParams,
    MarketingAnalyticsExplainConversionGoalRetrieveParams,
    MarketingAnalyticsSetupPlanRetrieveParams,
    MarketingAnalyticsSuggestConversionGoalsRetrieveParams,
    MarketingAnalyticsSuggestUtmMappingsRetrieveParams,
    MarketingAnalyticsUtmAuditRetrieveParams,
    MarketingDiagnosticResponseApi,
    PatchedConversionGoalUpdateApi,
    SetupPlanResponseApi,
    UtmAuditResponseApi,
    UtmMappingSuggestionsResponseApi,
} from './api.schemas'

export const getMarketingAnalyticsApplySetupOpsCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/marketing_analytics/apply_setup_ops/`
}

/**
 * Apply one or more setup operations from the setup plan, atomically. Either every operation lands or none does — a partially-applied batch has no well-defined undo. Returns `undo_ops`, computed from the pre-change state, which can be POSTed back to reverse the batch. Only send `apply` payloads returned by setup_plan.
 * @summary Apply setup operations
 */
export const marketingAnalyticsApplySetupOpsCreate = async (
    projectId: string,
    applySetupOpsApi: ApplySetupOpsApi,
    options?: RequestInit
): Promise<ApplySetupOpsResponseApi> => {
    return apiMutator<ApplySetupOpsResponseApi>(getMarketingAnalyticsApplySetupOpsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(applySetupOpsApi),
    })
}

export const getMarketingAnalyticsConversionGoalsRetrieveUrl = (projectId: string) => {
    return `/api/projects/${projectId}/marketing_analytics/conversion_goals/`
}

/**
 * Read the configured conversion goals for the current project — each with its kind, target, last-30d count, integrated vs non-integrated split, and a misconfiguration flag. Read-only.
 * @summary List conversion goals
 */
export const marketingAnalyticsConversionGoalsRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<ConversionGoalsListResponseApi> => {
    return apiMutator<ConversionGoalsListResponseApi>(getMarketingAnalyticsConversionGoalsRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export const getMarketingAnalyticsConversionGoalsDeleteDestroyUrl = (projectId: string, conversionGoalId: string) => {
    return `/api/projects/${projectId}/marketing_analytics/conversion_goals/${conversionGoalId}/delete/`
}

/**
 * Remove one conversion goal from the project, leaving the others in place.
 * @summary Delete conversion goal
 */
export const marketingAnalyticsConversionGoalsDeleteDestroy = async (
    projectId: string,
    conversionGoalId: string,
    options?: RequestInit
): Promise<ConversionGoalWriteResponseApi> => {
    return apiMutator<ConversionGoalWriteResponseApi>(
        getMarketingAnalyticsConversionGoalsDeleteDestroyUrl(projectId, conversionGoalId),
        {
            ...options,
            method: 'DELETE',
        }
    )
}

export const getMarketingAnalyticsConversionGoalsUpdatePartialUpdateUrl = (
    projectId: string,
    conversionGoalId: string
) => {
    return `/api/projects/${projectId}/marketing_analytics/conversion_goals/${conversionGoalId}/update/`
}

/**
 * Change one conversion goal in place. Fields you send are merged into the stored goal, the rest are kept, and the goal keeps its position in the list. Sending a different `kind` replaces the goal instead, since the shapes don't share their fields.
 * @summary Update conversion goal
 */
export const marketingAnalyticsConversionGoalsUpdatePartialUpdate = async (
    projectId: string,
    conversionGoalId: string,
    patchedConversionGoalUpdateApi?: PatchedConversionGoalUpdateApi,
    options?: RequestInit
): Promise<ConversionGoalWriteResponseApi> => {
    return apiMutator<ConversionGoalWriteResponseApi>(
        getMarketingAnalyticsConversionGoalsUpdatePartialUpdateUrl(projectId, conversionGoalId),
        {
            ...options,
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(patchedConversionGoalUpdateApi),
        }
    )
}

export const getMarketingAnalyticsConversionGoalsCreateCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/marketing_analytics/conversion_goals/create/`
}

/**
 * Add one conversion goal to the project. The server assigns conversion_goal_id and appends the goal to the end of the list, leaving existing goals untouched.
 * @summary Create conversion goal
 */
export const marketingAnalyticsConversionGoalsCreateCreate = async (
    projectId: string,
    conversionGoalWriteApi: ConversionGoalWriteApi,
    options?: RequestInit
): Promise<ConversionGoalWriteResponseApi> => {
    return apiMutator<ConversionGoalWriteResponseApi>(getMarketingAnalyticsConversionGoalsCreateCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(conversionGoalWriteApi),
    })
}

export const getMarketingAnalyticsDataSourcesRetrieveUrl = (
    projectId: string,
    params?: MarketingAnalyticsDataSourcesRetrieveParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/marketing_analytics/data_sources/?${stringifiedParams}`
        : `/api/projects/${projectId}/marketing_analytics/data_sources/`
}

/**
 * Check the platform → data-warehouse side of every native marketing integration: connection state, sync recency, row counts, required-table status, and schema-mapping coverage. Read-only.
 * @summary List marketing data sources
 */
export const marketingAnalyticsDataSourcesRetrieve = async (
    projectId: string,
    params?: MarketingAnalyticsDataSourcesRetrieveParams,
    options?: RequestInit
): Promise<DataSourceHealthResponseApi> => {
    return apiMutator<DataSourceHealthResponseApi>(getMarketingAnalyticsDataSourcesRetrieveUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getMarketingAnalyticsDiagnoseRetrieveUrl = (
    projectId: string,
    params?: MarketingAnalyticsDiagnoseRetrieveParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/marketing_analytics/diagnose/?${stringifiedParams}`
        : `/api/projects/${projectId}/marketing_analytics/diagnose/`
}

/**
 * Aggregate data-source sync health, UTM attribution health, and conversion-goal config into a single per-integration diagnostic with recommended actions. Read-only.
 * @summary Diagnose marketing analytics
 */
export const marketingAnalyticsDiagnoseRetrieve = async (
    projectId: string,
    params?: MarketingAnalyticsDiagnoseRetrieveParams,
    options?: RequestInit
): Promise<MarketingDiagnosticResponseApi> => {
    return apiMutator<MarketingDiagnosticResponseApi>(getMarketingAnalyticsDiagnoseRetrieveUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getMarketingAnalyticsExplainConversionGoalRetrieveUrl = (
    projectId: string,
    params: MarketingAnalyticsExplainConversionGoalRetrieveParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/marketing_analytics/explain_conversion_goal/?${stringifiedParams}`
        : `/api/projects/${projectId}/marketing_analytics/explain_conversion_goal/`
}

/**
 * Break down a single conversion goal's events over a period by event name, utm_source, and matched integration, with a small sample of events. Read-only.
 * @summary Explain a conversion goal
 */
export const marketingAnalyticsExplainConversionGoalRetrieve = async (
    projectId: string,
    params: MarketingAnalyticsExplainConversionGoalRetrieveParams,
    options?: RequestInit
): Promise<GoalExplanationApi> => {
    return apiMutator<GoalExplanationApi>(getMarketingAnalyticsExplainConversionGoalRetrieveUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getMarketingAnalyticsSetupPlanRetrieveUrl = (
    projectId: string,
    params?: MarketingAnalyticsSetupPlanRetrieveParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/marketing_analytics/setup_plan/?${stringifiedParams}`
        : `/api/projects/${projectId}/marketing_analytics/setup_plan/`
}

/**
 * Rank everything wrong with a team's marketing analytics setup into concrete suggestions, each carrying the evidence behind it and — where one exists — an `apply` operation to pass straight to apply_setup_ops, plus a `readiness` block saying which capabilities (cost, ROAS, cost per customer, retention by channel) are unlocked and which suggestion is blocking each. Prefer this over `diagnose` when the question is 'what should I fix next': diagnose explains what is wrong, setup_plan says what to do about it in a form you can act on. Read-only.
 * @summary Get the marketing analytics setup plan
 */
export const marketingAnalyticsSetupPlanRetrieve = async (
    projectId: string,
    params?: MarketingAnalyticsSetupPlanRetrieveParams,
    options?: RequestInit
): Promise<SetupPlanResponseApi> => {
    return apiMutator<SetupPlanResponseApi>(getMarketingAnalyticsSetupPlanRetrieveUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getMarketingAnalyticsSuggestConversionGoalsRetrieveUrl = (
    projectId: string,
    params?: MarketingAnalyticsSuggestConversionGoalsRetrieveParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/marketing_analytics/suggest_conversion_goals/?${stringifiedParams}`
        : `/api/projects/${projectId}/marketing_analytics/suggest_conversion_goals/`
}

/**
 * Rank existing custom events as conversion-goal candidates by volume, UTM-tag coverage, and unique users, excluding system/autocaptured events. Read-only.
 * @summary Suggest conversion goals
 */
export const marketingAnalyticsSuggestConversionGoalsRetrieve = async (
    projectId: string,
    params?: MarketingAnalyticsSuggestConversionGoalsRetrieveParams,
    options?: RequestInit
): Promise<EventSuggestionsResponseApi> => {
    return apiMutator<EventSuggestionsResponseApi>(
        getMarketingAnalyticsSuggestConversionGoalsRetrieveUrl(projectId, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

export const getMarketingAnalyticsSuggestUtmMappingsRetrieveUrl = (
    projectId: string,
    params?: MarketingAnalyticsSuggestUtmMappingsRetrieveParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/marketing_analytics/suggest_utm_mappings/?${stringifiedParams}`
        : `/api/projects/${projectId}/marketing_analytics/suggest_utm_mappings/`
}

/**
 * Detect unmatched utm_source values from recent events and propose custom_source_mappings entries, alongside the full utm_source catalogue and current mappings. Read-only.
 * @summary Suggest UTM source mappings
 */
export const marketingAnalyticsSuggestUtmMappingsRetrieve = async (
    projectId: string,
    params?: MarketingAnalyticsSuggestUtmMappingsRetrieveParams,
    options?: RequestInit
): Promise<UtmMappingSuggestionsResponseApi> => {
    return apiMutator<UtmMappingSuggestionsResponseApi>(
        getMarketingAnalyticsSuggestUtmMappingsRetrieveUrl(projectId, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

export const getMarketingAnalyticsTestMappingCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/marketing_analytics/test_mapping/`
}

export const marketingAnalyticsTestMappingCreate = async (projectId: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getMarketingAnalyticsTestMappingCreateUrl(projectId), {
        ...options,
        method: 'POST',
    })
}

export const getMarketingAnalyticsUtmAuditRetrieveUrl = (
    projectId: string,
    params?: MarketingAnalyticsUtmAuditRetrieveParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/marketing_analytics/utm_audit/?${stringifiedParams}`
        : `/api/projects/${projectId}/marketing_analytics/utm_audit/`
}

/**
 * Cross-reference campaigns with spend from ad platforms against pageview events with UTM parameters to identify tracking issues.
 * @summary Run UTM audit
 */
export const marketingAnalyticsUtmAuditRetrieve = async (
    projectId: string,
    params?: MarketingAnalyticsUtmAuditRetrieveParams,
    options?: RequestInit
): Promise<UtmAuditResponseApi> => {
    return apiMutator<UtmAuditResponseApi>(getMarketingAnalyticsUtmAuditRetrieveUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}
