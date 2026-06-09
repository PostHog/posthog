/**
 * Color / label helpers for progress, console and status views.
 *
 * Ported from
 * apps/code/src/renderer/features/sessions/utils/contextColors.ts.
 *
 * The reference used Radix accent CSS variables (e.g. `var(--violet-9)`).
 * Those tokens don't exist in posthog/posthog, so they are mapped to PostHog's
 * design-system CSS variables (`var(--<token>)`, defined in the global theme)
 * with a Tailwind-friendly fallback hex. Keep the category set and ordering
 * identical to the reference so downstream legends line up.
 */

export type ContextCategoryKey =
    | 'systemPrompt'
    | 'tools'
    | 'rules'
    | 'skills'
    | 'mcp'
    | 'subagents'
    | 'conversation'

export interface CategoryStyle {
    key: ContextCategoryKey
    label: string
    /** A CSS color value, suitable for inline `style={{ color }}` or chart fills. */
    color: string
}

export const CONTEXT_CATEGORIES: readonly CategoryStyle[] = [
    { key: 'systemPrompt', label: 'System prompt', color: 'var(--muted)' },
    { key: 'tools', label: 'Tools', color: 'var(--purple)' },
    { key: 'rules', label: 'Rules', color: 'var(--success)' },
    { key: 'skills', label: 'Skills', color: 'var(--warning)' },
    { key: 'mcp', label: 'MCP', color: 'var(--brand-red)' },
    { key: 'subagents', label: 'Subagents', color: 'var(--brand-blue)' },
    { key: 'conversation', label: 'Conversation', color: 'var(--brand-orange)' },
] as const

/** Color for an overall context-usage bar, escalating as it fills up. */
export function getOverallUsageColor(percentage: number): string {
    if (percentage >= 90) {
        return 'var(--danger)'
    }
    if (percentage >= 75) {
        return 'var(--brand-orange)'
    }
    if (percentage >= 50) {
        return 'var(--warning)'
    }
    return 'var(--success)'
}

/** Compact token count: 1_500_000 → "1.5M", 12_000 → "12K". */
export function formatTokensCompact(tokens: number): string {
    if (tokens >= 1_000_000) {
        return `${(tokens / 1_000_000).toFixed(1)}M`
    }
    if (tokens >= 1000) {
        return `${Math.round(tokens / 1000)}K`
    }
    return tokens.toString()
}
