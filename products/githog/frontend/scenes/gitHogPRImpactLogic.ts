import { actions, afterMount, kea, key, path, props, reducers } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { getCurrentTeamId } from 'lib/utils/getAppContext'

import type { gitHogPRImpactLogicType } from './gitHogPRImpactLogicType'

export interface GitHogPRImpactLogicProps {
    owner: string
    name: string
    number: number | string
}

export interface FlagReference {
    key: string
    file_paths: string[]
    occurrences: number
}

export interface VariantReach {
    variant: string
    users_affected: number
}

export interface FlagReach {
    key: string
    users_affected: number
    sessions_affected: number
    call_count: number
    variants: VariantReach[]
    has_data: boolean
    is_server_side: boolean
}

export interface EventReference {
    name: string
    file_paths: string[]
    occurrences: number
}

export interface EventReach {
    name: string
    users_affected: number
    sessions_affected: number
    call_count: number
    has_data: boolean
    is_server_side: boolean
}

export interface DashboardReference {
    kind: 'insight' | 'dashboard'
    id: number
    name: string
    short_id: string | null
    matched_keys: string[]
}

export interface LLMPick {
    kind: 'flag' | 'event' | 'dashboard' | 'issue' | 'page'
    key: string
    reason: string
}

export interface WebPathReach {
    path: string
    pageviews: number
    unique_visitors: number
    sessions: number
    has_data: boolean
    matched_from: 'diff_literal' | 'llm_tool'
}

export interface AffectedEstimate {
    headline: string
    unit: 'users' | 'events' | 'requests' | 'unknown'
    lower: number | null
    upper: number | null
    share_lower: number | null
    share_upper: number | null
    confidence: 'high' | 'medium' | 'low'
    rationale: string
}

export interface LLMAnalysis {
    headline: string
    summary: string
    affected: AffectedEstimate | null
    audience: string[]
    top_picks: LLMPick[]
    caveats: string[]
    tool_calls_used: number
}

export interface RelatedSignal {
    kind: 'flag' | 'event'
    key: string
    matched_tokens: string[]
    users_affected: number
    sessions_affected: number
    call_count: number
    is_server_side: boolean
    has_data: boolean
}

export interface IssueReference {
    id: string
    name: string
    status: string
    occurrences: number
    users_affected: number
    sample_message: string
    matched_terms: string[]
}

export interface PRImpactReport {
    flag_references: FlagReference[]
    per_flag_reach: FlagReach[]
    intersection_users: number
    intersection_sessions: number
    lookback_days: number
    event_references: EventReference[]
    per_event_reach: EventReach[]
    dashboard_references: DashboardReference[]
    issue_references: IssueReference[]
    related_signals: RelatedSignal[]
    web_paths: WebPathReach[]
    changed_files: string[]
    known_flag_count: number
    known_event_count: number
    llm_analysis: LLMAnalysis | null
    notes: string[]
}

export const gitHogPRImpactLogic = kea<gitHogPRImpactLogicType>([
    props({} as GitHogPRImpactLogicProps),
    key((p) => `${p.owner}/${p.name}#${p.number}`),
    path((prKey) => ['scenes', 'githog', 'gitHogPRImpactLogic', prKey]),
    actions({
        setLookbackDays: (lookbackDays: number) => ({ lookbackDays }),
        setError: (message: string | null) => ({ message }),
    }),
    reducers({
        lookbackDays: [30 as number, { setLookbackDays: (_, { lookbackDays }) => lookbackDays }],
        reportError: [
            null as string | null,
            {
                setError: (_, { message }) => message,
                computeImpact: () => null,
            },
        ],
    }),
    loaders(({ props, values, actions }) => ({
        report: [
            null as PRImpactReport | null,
            {
                computeImpact: async ({ refresh = false }: { refresh?: boolean } = {}) => {
                    const repository = `${props.owner}/${props.name}`
                    try {
                        return await api.create<PRImpactReport>(
                            `api/environments/${getCurrentTeamId()}/githog/impact/from_pr/`,
                            {
                                repository,
                                pr_number: Number(props.number),
                                lookback_days: values.lookbackDays,
                                refresh,
                            }
                        )
                    } catch (e: any) {
                        const detail = e?.data?.detail ?? e?.message ?? String(e)
                        actions.setError(String(detail))
                        throw e
                    }
                },
            },
        ],
    })),
    afterMount(({ actions }) => {
        actions.computeImpact()
    }),
])
