import type {
    ClassifierScannerConfig,
    MonitorScannerConfig,
    ScorerScannerConfig,
    SummarizerScannerConfig,
} from './types'

export type ScannerTemplateIcon =
    | 'bolt'
    | 'warning'
    | 'notebook'
    | 'target'
    | 'thumbs-down'
    | 'star'
    | 'search'
    | 'magic'
    | 'bug'
    | 'check'

interface BaseTemplate {
    key: string
    name: string
    description: string
    icon: ScannerTemplateIcon
    scanner_name: string
    scanner_description: string
}

export interface MonitorTemplate extends BaseTemplate {
    scanner_type: 'monitor'
    scanner_config: MonitorScannerConfig
}

export interface SummarizerTemplate extends BaseTemplate {
    scanner_type: 'summarizer'
    scanner_config: SummarizerScannerConfig
}

export interface ClassifierTemplate extends BaseTemplate {
    scanner_type: 'classifier'
    scanner_config: ClassifierScannerConfig
}

export interface ScorerTemplate extends BaseTemplate {
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
            prompt: 'Return true if the user appears stuck on a page — scrolling without engaging, hovering over elements with no clear CTA, or abandoning the session shortly after arriving. Otherwise return false.',
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
            prompt: 'Summarize what the user did in this session. Mention the main pages they visited, the primary actions they took, and any notable moments (errors, confusion, completed flows). Be concrete and avoid speculation.',
            length: 'medium',
            emits_embeddings: false,
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
            prompt: "Classify what the user appeared to be trying to accomplish in this session. Choose the single best-fitting tag from the available options based on the user's primary actions.",
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
            prompt: 'Score how much frustration the user appeared to experience in this session. 0 means the session was smooth and the user accomplished what they came for. 10 means the user was visibly frustrated — rage clicks, repeated failures, abandonment. Use the full range.',
            scale: { min: 0, max: 10, label: 'frustration' },
        },
    },
    {
        key: 'session_outcome',
        name: 'Session outcome',
        description: 'Tag each session with what actually happened — task completed, abandoned, errored, etc.',
        icon: 'check',
        scanner_type: 'classifier',
        scanner_name: 'Session outcome',
        scanner_description: 'Classify the outcome of each session.',
        scanner_config: {
            prompt: 'Classify what happened in this session. Did the user complete what they were trying to do, abandon partway through, encounter an error that blocked them, or just browse without a clear task? Pick the single best-fitting outcome.',
            tags: ['task_completed', 'task_abandoned', 'blocked_by_error', 'browsing_only', 'inconclusive'],
            multi_label: false,
        },
    },
] as const

export type ScannerTemplateKey = (typeof defaultScannerTemplates)[number]['key']

export function findScannerTemplate(key: string | undefined): ScannerTemplate | undefined {
    if (!key) {
        return undefined
    }
    return defaultScannerTemplates.find((t) => t.key === key)
}
