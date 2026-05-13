import { actions, afterMount, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'

import type { founderValidationLogicType } from './founderValidationLogicType'

// Polling cadence while a validation run is in progress. The disposables plugin auto-pauses
// these intervals when the tab is hidden, so we don't burn quota in background tabs.
const POLL_INTERVAL_MS = 2000
const POLL_DISPOSABLE_KEY = 'founder-validation-poll'

// TODO: replace with generated types once `hogli build:openapi` is rerun against the new
// FounderProject serializer. These mirror products/founder_mode/backend/logic/validation/schemas.py.
export type Confidence = 'low' | 'medium' | 'high'
export type Severity = 'low' | 'medium' | 'high'
export type RiskCategory = 'market' | 'technical' | 'regulatory' | 'execution' | 'timing' | 'other'
export type ValidationStatus = 'pending' | 'running' | 'completed' | 'failed'

export interface IdeationInput {
    what: string
    how: string
    who: string
    problem: string
}

export interface Competitor {
    name: string
    description: string
    positioning: string
    pricing: string | null
    strengths: string[]
    weaknesses: string[]
}

export interface Differentiation {
    summary: string
    moat: string
    gap_in_market: string
}

export interface Assumption {
    statement: string
    risk_if_false: string
    current_confidence: Confidence
}

export interface ValidationExperiment {
    assumption_index: number
    name: string
    description: string
    cost_estimate: string
    success_signal: string
}

export interface Risk {
    category: RiskCategory
    description: string
    severity: Severity
}

export interface Verdict {
    score: number
    confidence: Confidence
    reasoning: string
    next_steps: string[]
}

export interface ValidationReport {
    competitors: Competitor[]
    differentiation: Differentiation
    assumptions: Assumption[]
    experiments: ValidationExperiment[]
    risks: Risk[]
    verdict: Verdict
}

export interface ValidationEnvelope {
    status: ValidationStatus
    report: ValidationReport | null
    error: string
    ideation_hash?: string
    started_at?: string
    completed_at?: string
    failed_at?: string
    trace_id?: string | null
}

export interface FounderProject {
    id: string
    name: string
    ideation: IdeationInput | Record<string, unknown>
    validation: ValidationEnvelope | Record<string, never>
    gtm: Record<string, unknown>
    mvp: Record<string, unknown>
    created_by: number | null
    created_at: string
    updated_at: string
}

export interface FounderValidationLogicProps {
    projectId: string
}

const projectUrl = (projectId: string): string => `api/projects/@current/founder_projects/${projectId}/`
const runValidationUrl = (projectId: string): string => `${projectUrl(projectId)}run_validation/`

export const founderValidationLogic = kea<founderValidationLogicType>([
    path(['products', 'founder_mode', 'frontend', 'components', 'founderValidationLogic']),
    props({} as FounderValidationLogicProps),
    key((props) => props.projectId),

    actions({
        startPolling: true,
        stopPolling: true,
    }),

    loaders(({ props }) => ({
        project: [
            null as FounderProject | null,
            {
                loadProject: async () => api.get<FounderProject>(projectUrl(props.projectId)),
                regenerate: async () => api.create<FounderProject>(runValidationUrl(props.projectId)),
            },
        ],
    })),

    reducers({
        isPolling: [
            false,
            {
                startPolling: () => true,
                stopPolling: () => false,
            },
        ],
    }),

    selectors({
        validation: [
            (s) => [s.project],
            (project): ValidationEnvelope | null => {
                const v = project?.validation
                if (!v || !('status' in v)) {
                    return null
                }
                return v as ValidationEnvelope
            },
        ],
        status: [(s) => [s.validation], (validation): ValidationStatus | null => validation?.status ?? null],
        report: [(s) => [s.validation], (validation): ValidationReport | null => validation?.report ?? null],
        errorMessage: [(s) => [s.validation], (validation): string => validation?.error ?? ''],
        isRunning: [(s) => [s.status], (status): boolean => status === 'pending' || status === 'running'],
        ideation: [
            (s) => [s.project],
            (project): IdeationInput | null => {
                const i = project?.ideation
                if (!i || !('what' in i)) {
                    return null
                }
                return i as IdeationInput
            },
        ],
    }),

    listeners(({ actions, values, cache }) => ({
        loadProjectSuccess: () => {
            // Toggle polling to match server state. Reload-on-mount + auto-poll-while-running
            // means the founder always sees fresh state without manual refresh.
            if (values.isRunning && !values.isPolling) {
                actions.startPolling()
            } else if (!values.isRunning && values.isPolling) {
                actions.stopPolling()
            }
        },
        regenerateSuccess: () => {
            if (!values.isPolling) {
                actions.startPolling()
            }
        },
        startPolling: () => {
            cache.disposables.add(() => {
                const id = setInterval(() => actions.loadProject(), POLL_INTERVAL_MS)
                return () => clearInterval(id)
            }, POLL_DISPOSABLE_KEY)
        },
        stopPolling: () => {
            cache.disposables.dispose(POLL_DISPOSABLE_KEY)
        },
    })),

    afterMount(({ actions }) => {
        actions.loadProject()
    }),
])
