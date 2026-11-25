import { hogql } from 'lib/utils/hogql'

import type { SurveyApi } from 'products/surveys/frontend/generated/api.schemas'

import type { LinkedInsightDTOApi, LinkedSurveyDTOApi } from './generated/api.schemas'
import { nameTokens } from './releaseUtils'

export interface RelatedSurvey {
    id: string
    name: string
    createdAt: string
    startDate: string | null
    endDate: string | null
    linkedFlagId: number | null
    archived: boolean
}

export interface RelatedInsight {
    id: number
    shortId: string
    name: string
    createdAt: string
    lastModifiedAt: string | null
    deleted?: boolean
}

export type RelatedKind = 'survey' | 'insight'

export interface RelatedSuggestion {
    key: string
    kind: RelatedKind
    id: string
    label: string
    reason: string
    detected: boolean
}

export const SUGGESTION_LIMIT = 6

export const INSIGHT_COLUMNS = hogql.raw('id, short_id, name, created_at, last_modified_at')

export function fromInsightRow(row: unknown[]): RelatedInsight {
    const [id, shortId, name, createdAt, lastModifiedAt] = row as [number, string, string | null, string, string | null]
    return { id, shortId, name: name || 'Untitled insight', createdAt, lastModifiedAt }
}

export function toSurvey(survey: SurveyApi): RelatedSurvey {
    return {
        id: survey.id,
        name: survey.name,
        createdAt: survey.created_at,
        startDate: survey.start_date ?? null,
        endDate: survey.end_date ?? null,
        linkedFlagId: survey.linked_flag_id ?? survey.linked_flag?.id ?? null,
        archived: !!survey.archived,
    }
}

export function fromLinkedSurvey(survey: LinkedSurveyDTOApi): RelatedSurvey {
    return {
        id: survey.id,
        name: survey.name,
        createdAt: survey.created_at,
        startDate: survey.start_date ?? null,
        endDate: survey.end_date ?? null,
        linkedFlagId: survey.linked_flag_id ?? null,
        archived: survey.archived,
    }
}

export function fromLinkedInsight(insight: LinkedInsightDTOApi): RelatedInsight {
    return {
        id: insight.id,
        shortId: insight.short_id,
        name: insight.name,
        createdAt: insight.created_at ?? '',
        lastModifiedAt: insight.last_modified_at ?? null,
        deleted: insight.deleted,
    }
}

export function flagKeysPattern(keys: string[]): string {
    const escaped = keys.map((key) => key.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'))
    return `\\$feature/(?:${escaped.join('|')})(?:[^A-Za-z0-9_\\-]|$)`
}

export interface RankInput {
    tokens: string[]
    flags: { id: number; key: string }[]
    linkedSurveyIds: Set<string>
    linkedInsightIds: Set<number>
    flagSurveys: RelatedSurvey[]
    flagInsights: RelatedInsight[]
    nameSurveys: RelatedSurvey[]
    nameInsights: RelatedInsight[]
}

export function rankRelatedSuggestions(input: RankInput): RelatedSuggestion[] {
    const wanted = new Set(input.tokens)
    const overlap = (label: string): number => nameTokens(label).filter((token) => wanted.has(token)).length
    const flagKeyById = new Map(input.flags.map((flag) => [flag.id, flag.key]))
    const items = new Map<string, RelatedSuggestion>()
    for (const survey of input.flagSurveys) {
        if (!input.linkedSurveyIds.has(survey.id) && !survey.archived) {
            items.set(`survey:${survey.id}`, {
                key: `survey:${survey.id}`,
                kind: 'survey',
                id: survey.id,
                label: survey.name,
                reason: `Shown to people who get ${flagKeyById.get(survey.linkedFlagId ?? -1) ?? 'a flag in this release'}`,
                detected: true,
            })
        }
    }
    for (const insight of input.flagInsights) {
        if (!input.linkedInsightIds.has(insight.id)) {
            items.set(`insight:${insight.id}`, {
                key: `insight:${insight.id}`,
                kind: 'insight',
                id: String(insight.id),
                label: insight.name,
                reason: 'Breaks down or filters by a flag in this release',
                detected: true,
            })
        }
    }
    const named = [
        ...input.nameSurveys.map((survey) => ({
            key: `survey:${survey.id}`,
            kind: 'survey' as const,
            id: survey.id,
            label: survey.name,
            linked: input.linkedSurveyIds.has(survey.id) || survey.archived,
        })),
        ...input.nameInsights.map((insight) => ({
            key: `insight:${insight.id}`,
            kind: 'insight' as const,
            id: String(insight.id),
            label: insight.name,
            linked: input.linkedInsightIds.has(insight.id),
        })),
    ]
        .filter((item) => !item.linked && !items.has(item.key) && overlap(item.label) > 0)
        .sort((a, b) => overlap(b.label) - overlap(a.label))
        .slice(0, SUGGESTION_LIMIT)
    for (const item of named) {
        items.set(item.key, {
            key: item.key,
            kind: item.kind,
            id: item.id,
            label: item.label,
            reason: 'Name matches this release',
            detected: false,
        })
    }
    return [...items.values()]
}
