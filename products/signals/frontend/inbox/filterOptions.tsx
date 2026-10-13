import { JSX } from 'react'

import {
    IconBrain,
    IconBug,
    IconCalendar,
    IconClock,
    IconCompass,
    IconDatabase,
    IconEye,
    IconGear,
    IconGithub,
    IconGraph,
    IconList,
    IconReceipt,
    IconRefresh,
    IconStack,
    IconSupport,
} from '@posthog/icons'
import { LemonTagType } from '@posthog/lemon-ui'

import type {
    InboxCreatedWindow,
    InboxRankingSortField,
    InboxSortDirection,
    InboxSortField,
} from './logics/inboxFiltersLogic'
import { SignalReportPriority } from './types'
import { prettifyScoutSkillName } from './utils/scoutRunsWindow'

/**
 * Single source of truth for per-priority color. P0–P4 each get a DISTINCT hue so
 * users can tell them apart at a glance (red → orange → amber → blue → gray).
 * Consumed by the priority badge, the priority monogram, and the filter dots.
 */
export const PRIORITY_TAG_TYPE: Record<SignalReportPriority, LemonTagType> = {
    P0: 'danger', // red
    P1: 'warning', // orange
    P2: 'caution', // amber
    P3: 'highlight', // blue
    P4: 'muted', // gray
}

/**
 * Human meaning of each priority code, mirroring the criteria the research agent judges against
 * (see products/signals/backend/report_generation/research.py). Surfaced in the priority badge
 * tooltip and the priority filter so users don't have to guess what P0–P4 mean.
 */
export const PRIORITY_MEANING: Record<SignalReportPriority, { label: string; description: string }> = {
    P0: {
        label: 'Critical',
        description: 'Production errors, a broken core flow, data loss, or a security vulnerability.',
    },
    P1: { label: 'High', description: 'Significant user-facing impact or a clear regression.' },
    P2: { label: 'Medium', description: 'A clear improvement opportunity, or a contained issue with workarounds.' },
    P3: { label: 'Low', description: 'A minor improvement or low-impact issue.' },
    P4: { label: 'Minimal', description: 'Cosmetic or negligible impact, or an optional investigation.' },
}

/** Matching CSS accent per priority, for non-LemonTag surfaces (filter dots, monograms). */
export const PRIORITY_ACCENT: Record<SignalReportPriority, string> = {
    P0: 'var(--red-9, #e5484d)',
    P1: 'var(--orange-9, #f76b15)',
    P2: 'var(--amber-9, #ffc53d)',
    P3: 'var(--blue-9, #3b9eff)',
    P4: 'var(--muted, #8f8f8f)',
}

// Port of desktop `@posthog/ui/features/inbox/filterOptions`. Drives the Source /
// Sort filter popovers. Source-product values match the backend
// `source_product` values.

export interface InboxSortOption {
    label: string
    field: InboxSortField
    direction: InboxSortDirection
    icon: JSX.Element
    description?: string
}

export const INBOX_SORT_OPTIONS: InboxSortOption[] = [
    { label: 'Priority first', field: 'priority', direction: 'asc', icon: <IconList /> },
    { label: 'Last updated first', field: 'updated_at', direction: 'desc', icon: <IconRefresh /> },
    { label: 'Newest first', field: 'created_at', direction: 'desc', icon: <IconCalendar /> },
    { label: 'Oldest first', field: 'created_at', direction: 'asc', icon: <IconClock /> },
]

/**
 * The three ranking model scores the staff UI shows, in display order. Each reads one outcome head.
 * The model serves more heads, but the sort menu, the card tag and the activity log lead with these.
 */
export interface InboxRankingScore {
    field: InboxRankingSortField
    head: string
    name: string
    sortLabel: string
    /** The short word the card tag uses after the lift ("2.1x fix"). */
    tagLabel: string
    description: string
}

export const INBOX_RANKING_SCORES: InboxRankingScore[] = [
    {
        field: 'ranking_open',
        head: 'open',
        name: 'Open',
        sortLabel: 'Most likely to be opened',
        tagLabel: 'open',
        description: 'A person opens the report within 3 days.',
    },
    {
        field: 'ranking_action',
        head: 'action',
        name: 'Engage',
        sortLabel: 'Most likely to be acted on',
        tagLabel: 'engage',
        description: 'A person acts on the report within 7 days.',
    },
    {
        field: 'ranking_fixed',
        head: 'fixed',
        name: 'Fix',
        sortLabel: 'Most likely to be fixed',
        tagLabel: 'fix',
        description: 'Someone fixes the problem within 21 days.',
    },
]

/** Staff-only sorts by the ranking model's served probability for one score. Descending only. */
export const INBOX_MODEL_SORT_OPTIONS: InboxSortOption[] = INBOX_RANKING_SCORES.map((score) => ({
    label: score.sortLabel,
    field: score.field,
    direction: 'desc',
    icon: <IconBrain />,
    description: score.description,
}))

const RANKING_SCORE_BY_FIELD = Object.fromEntries(INBOX_RANKING_SCORES.map((score) => [score.field, score])) as Record<
    InboxRankingSortField,
    InboxRankingScore
>

export function isRankingSortField(field: InboxSortField): field is InboxRankingSortField {
    return field in RANKING_SCORE_BY_FIELD
}

export function rankingScoreForField(field: InboxRankingSortField): InboxRankingScore {
    return RANKING_SCORE_BY_FIELD[field]
}

export function rankingScoreForHead(head: string): InboxRankingScore | undefined {
    return INBOX_RANKING_SCORES.find((score) => score.head === head)
}

export const INBOX_CREATED_WINDOW_OPTIONS: { value: InboxCreatedWindow; label: string; hours: number }[] = [
    { value: '24h', label: 'Last 24 hours', hours: 24 },
    { value: '3d', label: 'Last 3 days', hours: 3 * 24 },
    { value: '7d', label: 'Last 7 days', hours: 7 * 24 },
    { value: '14d', label: 'Last 14 days', hours: 14 * 24 },
]

/** The `created_after` bound for a window, computed at request time so a long-open tab never sends a stale bound. */
export function createdAfterForWindow(window: InboxCreatedWindow | null, now: number = Date.now()): string | undefined {
    const option = INBOX_CREATED_WINDOW_OPTIONS.find((o) => o.value === window)
    return option ? new Date(now - option.hours * 60 * 60 * 1000).toISOString() : undefined
}

export const INBOX_SOURCE_OPTIONS: { value: string; label: string; icon: JSX.Element }[] = [
    { value: 'replay_vision', label: 'Replay vision', icon: <IconEye /> },
    { value: 'error_tracking', label: 'Error tracking', icon: <IconBug /> },
    { value: 'llm_analytics', label: 'AI observability', icon: <IconBrain /> },
    { value: 'github', label: 'GitHub', icon: <IconGithub /> },
    { value: 'linear', label: 'Linear', icon: <IconStack /> },
    { value: 'zendesk', label: 'Zendesk', icon: <IconReceipt /> },
    { value: 'conversations', label: 'Support', icon: <IconSupport /> },
    { value: 'pganalyze', label: 'pganalyze', icon: <IconDatabase /> },
    { value: 'analytics', label: 'Product analytics', icon: <IconGraph /> },
    {
        value: 'engineering_analytics',
        label: 'Engineering analytics',
        icon: <IconGear />,
    },
    { value: 'signals_scout', label: 'Scout', icon: <IconCompass /> },
]

/** Priority codes in rank order (P0 highest → P4 lowest), driving the Priority filter popover. */
export const INBOX_PRIORITY_OPTIONS: SignalReportPriority[] = ['P0', 'P1', 'P2', 'P3', 'P4']

export function inboxSortOptionKey(field: InboxSortField, direction: InboxSortDirection): string {
    return `${field}:${direction}`
}

export function inboxPriorityFilterLabel(selected: SignalReportPriority[]): string {
    if (selected.length === 0) {
        return 'All priorities'
    }
    // Codes are short (P0–P4), so list them in rank order rather than collapsing to a count.
    return [...selected].sort().join(', ')
}

export function inboxSourceFilterLabel(selected: string[], selectedScouts: string[] = []): string {
    const parts: string[] = []
    if (selected.length === 1) {
        parts.push(INBOX_SOURCE_OPTIONS.find((o) => o.value === selected[0])?.label ?? selected[0])
    } else if (selected.length > 1) {
        parts.push(`${selected.length} sources`)
    }
    if (selectedScouts.length === 1) {
        // "Scout · " disambiguates from same-named source products (e.g. the error tracking
        // scout vs the error tracking source), matching the report rows' attribution label.
        parts.push(`Scout · ${prettifyScoutSkillName(selectedScouts[0])}`)
    } else if (selectedScouts.length > 1) {
        parts.push(`${selectedScouts.length} scouts`)
    }
    return parts.length > 0 ? parts.join(' · ') : 'All sources'
}
