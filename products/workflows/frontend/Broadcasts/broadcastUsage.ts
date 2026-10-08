import { objectsEqual } from 'lib/utils/objects'
import { hashCodeForString } from 'lib/utils/strings'

// pinned: URL search param the composer handoff adds to the draft URL, so the wizard knows where the draft came from
export const COMPOSER_DRAFT_PARAM = 'from'
export const COMPOSER_DRAFT_VALUE = 'ai_composer'

const COMPOSER_DRAFTS_STORAGE_KEY = 'broadcasts-ai-composer-drafts'
// pinned: session storage key
const ENTRY_SOURCES_STORAGE_KEY = 'broadcasts-entry-sources'

export type BroadcastPath = 'composer' | 'manual'

export type BroadcastField = 'name' | 'audience' | 'goal' | 'sender' | 'subject' | 'body'

export type BroadcastFieldSnapshot = Record<BroadcastField, unknown>

/** What the agent last saved for a composer draft, and how many of its edits reached the wizard. */
export interface ComposerDraftState {
    agentDraft: BroadcastFieldSnapshot
    agentEdits: number
}

const BROADCAST_FIELDS: BroadcastField[] = ['name', 'audience', 'goal', 'sender', 'subject', 'body']

function readComposerDrafts(): Record<string, ComposerDraftState> {
    try {
        const stored = JSON.parse(sessionStorage.getItem(COMPOSER_DRAFTS_STORAGE_KEY) || '{}')
        return stored && typeof stored === 'object' && !Array.isArray(stored) ? stored : {}
    } catch {
        return {}
    }
}

/**
 * Kept for the tab in session storage, so a reload still reports the composer path and still compares the
 * launch with what the agent drafted rather than with a copy that already holds the person's saved edits.
 */
export function saveComposerDraft(broadcastId: string, state: ComposerDraftState): void {
    try {
        sessionStorage.setItem(
            COMPOSER_DRAFTS_STORAGE_KEY,
            JSON.stringify({ ...readComposerDrafts(), [broadcastId]: state })
        )
    } catch {
        // Storage can be blocked. The draft then reports the manual path, which only undercounts the composer.
    }
}

export function loadComposerDraft(broadcastId: string | null | undefined): ComposerDraftState | null {
    return broadcastId ? (readComposerDrafts()[broadcastId] ?? null) : null
}

export function broadcastPath(broadcastId: string | null | undefined): BroadcastPath {
    return loadComposerDraft(broadcastId) ? 'composer' : 'manual'
}

/**
 * The fields a person can change in the wizard, read from a saved broadcast or from the payload the
 * wizard would save, so both sides of a comparison come out in the same shape. The body is hashed to
 * keep the stored copy small.
 */
export function snapshotBroadcast(flow: {
    name?: string | null
    conversion?: { events?: unknown[] | null; filters?: unknown[] | null; window?: unknown } | null
    actions?: unknown
}): BroadcastFieldSnapshot {
    const actions = (Array.isArray(flow.actions) ? flow.actions : []) as Record<string, any>[]
    const trigger = actions.find((action) => action.type === 'trigger')
    const email = actions.find((action) => action.type === 'function_email')?.config?.inputs?.email?.value
    const conversion = flow.conversion
    const hasGoal = !!conversion && ((conversion.events?.length ?? 0) > 0 || (conversion.filters?.length ?? 0) > 0)
    return {
        name: flow.name ?? '',
        audience: trigger?.config?.filters?.properties ?? [],
        goal: hasGoal
            ? { events: conversion.events ?? [], filters: conversion.filters ?? [], window: conversion.window }
            : null,
        sender: email?.from?.integrationId ?? null,
        subject: email?.subject ?? '',
        body: hashCodeForString(email?.html ?? ''),
    }
}

/**
 * Moves the agent's draft forward by an edit saved elsewhere. Only the fields that edit changed are taken,
 * because the saved copy also carries the person's own saved edits, which must still count as theirs.
 */
export function advanceAgentDraft(
    agentDraft: BroadcastFieldSnapshot,
    latest: BroadcastFieldSnapshot,
    base: BroadcastFieldSnapshot | null
): BroadcastFieldSnapshot {
    const next = { ...agentDraft }
    for (const field of BROADCAST_FIELDS) {
        if (!base || !objectsEqual(latest[field], base[field])) {
            next[field] = latest[field]
        }
    }
    return next
}

export function editedFields(agentDraft: BroadcastFieldSnapshot, current: BroadcastFieldSnapshot): BroadcastField[] {
    return BROADCAST_FIELDS.filter((field) => !objectsEqual(agentDraft[field], current[field]))
}

function readEntrySources(): Record<string, string> {
    try {
        const stored = JSON.parse(sessionStorage.getItem(ENTRY_SOURCES_STORAGE_KEY) || '{}')
        return stored && typeof stored === 'object' && !Array.isArray(stored) ? stored : {}
    } catch {
        return {}
    }
}

/** Kept for the tab, because saving the draft remounts the wizard under the draft's own URL. */
export function saveEntrySource(broadcastId: string, source: string): void {
    try {
        sessionStorage.setItem(
            ENTRY_SOURCES_STORAGE_KEY,
            JSON.stringify({ ...readEntrySources(), [broadcastId]: source })
        )
    } catch {
        // Storage can be blocked. The launch then reports no entry source.
    }
}

export function loadEntrySource(broadcastId: string | null | undefined): string | null {
    return broadcastId ? (readEntrySources()[broadcastId] ?? null) : null
}
