import { actions, afterMount, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'

import type { founderLandingPageLogicType } from './founderLandingPageLogicType'
import type { FounderProject } from './founderValidationLogic'

// Same polling cadence as validation.
const POLL_INTERVAL_MS = 2000
const POLL_DISPOSABLE_KEY = 'founder-landing-page-poll'

// TODO: replace with generated types once `hogli build:openapi` is rerun against the new
// LandingPageBuildSpec schema. Mirrors products/founder_mode/backend/logic/landing_page/schemas.py.

export type BrandSource = 'notebook' | 'synthesized' | 'user_questions'
export type SectionClassification = 'core' | 'optional_included' | 'optional_skipped'
export type KeywordPriority = 'high' | 'medium' | 'low'
export type LandingPageStatus = 'pending' | 'running' | 'completed' | 'failed'

export interface SourcedText {
    text: string
    sources: string[]
}

export interface Persona {
    label: string
    description: string
    sources: string[]
}

export interface UserPain {
    label: string
    description: string
    quantitative_evidence: string | null
    sources: string[]
}

export interface ProofPoint {
    kind: 'quantitative' | 'qualitative'
    statement: string
    sources: string[]
}

export interface ProjectBrief {
    product_name: SourcedText
    one_line_value_prop: SourcedText
    primary_persona: Persona
    secondary_persona: Persona | null
    top_user_pains: UserPain[]
    top_features: string[]
    proof_points: ProofPoint[]
}

export interface BrandDirection {
    source: BrandSource
    tone: SourcedText
    voice: SourcedText
    palette: SourcedText
    typography: SourcedText
    imagery: SourcedText
    references: SourcedText
    anti_references: SourcedText
}

export interface SEOKeyword {
    phrase: string
    sources: string[]
    priority: KeywordPriority
}

export interface CompetitorPositioning {
    name: string
    url: string
    pages_fetched: string[]
    positioning: string
    icp: string
    pricing: string
    cta: string
    voice_notes: string
}

export interface CoverageGap {
    competitor: string
    url: string | null
    reason: string
}

export interface PageSection {
    number: number
    name: string
    classification: SectionClassification
    why_included: string | null
    purpose: string
    copy_hooks: string
    design_notes: string
    component_recipe: string
    posthog_events: string[]
    acceptance_criteria: string[]
}

export interface SkippedSection {
    name: string
    reason: string
}

export interface SEOFrontMatter {
    title: string
    description: string
    og_image_alt: string | null
    json_ld_type: string
}

export interface PerformanceFloor {
    lcp_max_seconds: number
    cls_max: number
    lighthouse_a11y_min: number
    notes: string[]
}

export interface PostHogCustomEvent {
    name: string
    when: string
    properties: string[]
}

export interface InstrumentationGuide {
    sdk_install_cmd: string
    init_notes: string[]
    identify_notes: string[]
    custom_events: PostHogCustomEvent[]
    privacy_notes: string[]
}

export interface GlobalAcceptanceCriterion {
    statement: string
}

export interface LandingPageBuildSpec {
    project_name: string
    tldr: string[]
    project_brief: ProjectBrief
    brand: BrandDirection
    seo_keywords: SEOKeyword[]
    competitor_profiles: CompetitorPositioning[]
    coverage_gaps: CoverageGap[]
    page_sections: PageSection[]
    skipped_sections: SkippedSection[]
    seo_front_matter: SEOFrontMatter
    performance_floor: PerformanceFloor
    instrumentation: InstrumentationGuide
    global_acceptance_criteria: GlobalAcceptanceCriterion[]
}

export interface MvpEnvelope {
    status: LandingPageStatus
    page: LandingPageBuildSpec | null
    error: string
    started_at?: string
    completed_at?: string
    failed_at?: string
    trace_id?: string | null
}

export interface FounderLandingPageLogicProps {
    projectId: string
}

const projectUrl = (projectId: string): string => `api/projects/@current/founder_projects/${projectId}/`
const generateUrl = (projectId: string): string => `${projectUrl(projectId)}run_landing_page/`

export const founderLandingPageLogic = kea<founderLandingPageLogicType>([
    path(['products', 'founder_mode', 'frontend', 'components', 'founderLandingPageLogic']),
    props({} as FounderLandingPageLogicProps),
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
                generate: async () => api.create<FounderProject>(generateUrl(props.projectId)),
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
        mvp: [
            (s) => [s.project],
            (project): MvpEnvelope | null => {
                const m = project?.mvp
                if (!m || !('status' in m)) {
                    return null
                }
                return m as unknown as MvpEnvelope
            },
        ],
        status: [(s) => [s.mvp], (mvp): LandingPageStatus | null => mvp?.status ?? null],
        spec: [(s) => [s.mvp], (mvp): LandingPageBuildSpec | null => mvp?.page ?? null],
        errorMessage: [(s) => [s.mvp], (mvp): string => mvp?.error ?? ''],
        isRunning: [(s) => [s.status], (status): boolean => status === 'pending' || status === 'running'],
    }),

    listeners(({ actions, values, cache }) => ({
        loadProjectSuccess: () => {
            if (values.isRunning && !values.isPolling) {
                actions.startPolling()
            } else if (!values.isRunning && values.isPolling) {
                actions.stopPolling()
            }
        },
        generateSuccess: () => {
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
