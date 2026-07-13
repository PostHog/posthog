import { dayjs } from 'lib/dayjs'

import { NodeKind } from '~/queries/schema/schema-general'

import type {
    ClassifierScannerConfig,
    MonitorScannerConfig,
    ReplayScanner,
    ScorerScannerConfig,
    SummarizerScannerConfig,
} from './types'
import { DEFAULT_MODEL, DEFAULT_PROVIDER, OBSERVATION_CREDITS_BY_MODEL } from './types'

export type ScannerTemplateIcon = 'warning' | 'notebook' | 'target' | 'thumbs-down' | 'check'

interface BaseTemplate {
    key: string
    name: string
    description: string
    icon: ScannerTemplateIcon
    scanner_name: string
    scanner_description: string
}

interface MonitorTemplate extends BaseTemplate {
    scanner_type: 'monitor'
    scanner_config: MonitorScannerConfig
}

interface SummarizerTemplate extends BaseTemplate {
    scanner_type: 'summarizer'
    scanner_config: SummarizerScannerConfig
}

interface ClassifierTemplate extends BaseTemplate {
    scanner_type: 'classifier'
    scanner_config: ClassifierScannerConfig
}

interface ScorerTemplate extends BaseTemplate {
    scanner_type: 'scorer'
    scanner_config: ScorerScannerConfig
}

export type ScannerTemplate = MonitorTemplate | SummarizerTemplate | ClassifierTemplate | ScorerTemplate

export const defaultScannerTemplates: readonly ScannerTemplate[] = [
    {
        key: 'dead_end',
        name: 'Dead ends',
        description: 'Detect sessions where the user gets stuck on a page with no clear path forward.',
        icon: 'warning',
        scanner_type: 'monitor',
        scanner_name: 'Dead-end pages',
        scanner_description: 'Flag sessions where the user appears stuck with no obvious next action.',
        scanner_config: {
            prompt: 'Answer yes if the user appears stuck on a page: scrolling without engaging, hovering over elements with no clear CTA, or abandoning the session shortly after arriving. Otherwise answer no.',
        },
    },
    {
        key: 'session_summary',
        name: 'Session summary',
        description: 'Generate a short narrative of what the user actually did in the session.',
        icon: 'notebook',
        scanner_type: 'summarizer',
        scanner_name: 'Session summary',
        scanner_description: 'A short narrative summary of the session.',
        scanner_config: {
            prompt: "Summarize what the user did in this session: which pages they visited, what they tried to accomplish, and any notable moments like errors, confusion, or successful completions. Be concrete and don't speculate.",
            length: 'medium',
        },
    },
    {
        key: 'user_intent',
        name: 'User intent',
        description: 'Classify the session by what the user appeared to be trying to do.',
        icon: 'target',
        scanner_type: 'classifier',
        scanner_name: 'User intent',
        scanner_description: 'Tag each session with the likely intent behind it.',
        scanner_config: {
            prompt: 'Classify what the user appeared to be trying to accomplish in this session, based on their primary actions. Pick from the configured tag vocabulary.',
            tags: ['browsing', 'purchasing', 'researching', 'support', 'account_management', 'returning_task'],
            multi_label: false,
        },
    },
    {
        key: 'frustration_score',
        name: 'Frustration score',
        description: 'Score how much friction or frustration the user appeared to experience.',
        icon: 'thumbs-down',
        scanner_type: 'scorer',
        scanner_name: 'Frustration score',
        scanner_description: 'Numeric score for how frustrated the user appeared.',
        scanner_config: {
            prompt: 'Score how frustrated the user appeared during this session. 0 means a smooth session with no visible friction. 10 means clear, sustained frustration: rage clicks, repeated failures, abandonment. Use the full range; most sessions land somewhere in the middle.',
            scale: { min: 0, max: 10, label: 'frustration' },
        },
    },
    {
        key: 'session_outcome',
        name: 'Session outcome',
        description: 'Tag each session with what actually happened: task completed, abandoned, errored, etc.',
        icon: 'check',
        scanner_type: 'classifier',
        scanner_name: 'Session outcome',
        scanner_description: 'Classify the outcome of each session.',
        scanner_config: {
            prompt: 'Classify what happened in this session. Did the user complete what they were trying to do, abandon partway through, hit an error that blocked them, or just browse without a clear task? Pick from the configured tag vocabulary.',
            tags: ['task_completed', 'task_abandoned', 'blocked_by_error', 'browsing_only', 'inconclusive'],
            multi_label: false,
        },
    },
] as const

export function findScannerTemplate(key: string | undefined): ScannerTemplate | undefined {
    if (!key) {
        return undefined
    }
    return defaultScannerTemplates.find((t) => t.key === key)
}

export function newScanner(templateKey?: string | null): ReplayScanner {
    const base = {
        id: 'new',
        enabled: true,
        sampling_rate: 1,
        sampling_mode: 'comprehensive' as const,
        query: { kind: NodeKind.RecordingsQuery },
        provider: DEFAULT_PROVIDER,
        model: DEFAULT_MODEL,
        emits_signals: false,
        scanner_version: 1,
        last_swept_at: dayjs().toISOString(),
        created_at: dayjs().toISOString(),
        updated_at: dayjs().toISOString(),
        created_by: null,
        estimated_monthly_observations: null,
        feedback_themes: null,
        estimated_monthly_credits: null,
        // Seed price for the unsaved scanner; the server-computed value takes over after the first save.
        credits_per_observation: OBSERVATION_CREDITS_BY_MODEL[DEFAULT_MODEL],
    } as const

    const template = findScannerTemplate(templateKey ?? undefined)
    if (template) {
        return {
            ...base,
            name: template.scanner_name,
            description: template.scanner_description,
            scanner_type: template.scanner_type,
            // Cloned so an in-place form mutation can never corrupt the module-level template.
            scanner_config: structuredClone(template.scanner_config),
        } as ReplayScanner
    }
    return {
        ...base,
        name: '',
        description: '',
        scanner_type: 'monitor',
        scanner_config: { prompt: '' },
    }
}
