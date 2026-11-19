// PROTOTYPE, never merged: PostHog/michaelr-context#421. In-memory state for saved views, tags and search.
// A plain store, not a kea logic: nothing here outlives the prototype, and nothing is persisted but the variant.
import { router } from 'kea-router'
import { useSyncExternalStore } from 'react'

import { ME, MESSAGE_ITEMS, MessageItem, MessageStatus, MessageType } from './viewsPrototypeData'

export const VIEWS_VARIANTS = ['A', 'B', 'C', 'D'] as const
export type ViewsVariant = (typeof VIEWS_VARIANTS)[number]

export type ColumnKey =
    | 'name'
    | 'type'
    | 'status'
    | 'tags'
    | 'when'
    | 'recipients'
    | 'slug'
    | 'sent7d'
    | 'trigger'
    | 'channels'
    | 'createdBy'
    | 'updated'

export const COLUMN_LABELS: Record<ColumnKey, string> = {
    name: 'Name',
    type: 'Type',
    status: 'Status',
    tags: 'Tags',
    when: 'Send time',
    recipients: 'Recipients',
    slug: 'ID',
    sent7d: 'Sent, last 7 days',
    trigger: 'Trigger',
    channels: 'Channels',
    createdBy: 'Created by',
    updated: 'Last updated',
}

export interface ViewSort {
    columnKey: ColumnKey
    order: 1 | -1
}

/** One view is one saved filter, sort and column set. Default views and saved views share it. */
export interface ViewQuery {
    types: MessageType[]
    search: string
    /** Empty means every status but Archived, like the lists today. */
    statuses: MessageStatus[]
    tags: string[]
    createdBy: string | null
    sort: ViewSort
    columns: ColumnKey[]
}

export type DefaultViewKey = 'broadcasts' | 'transactional' | 'workflows' | 'all'

export interface SavedView {
    id: string
    name: string
    visibility: 'private' | 'shared'
    owner: string
    query: ViewQuery
}

export const ALL_TYPES: MessageType[] = ['broadcast', 'transactional', 'workflow']

export const DEFAULT_QUERIES: Record<DefaultViewKey, ViewQuery> = {
    broadcasts: {
        types: ['broadcast'],
        search: '',
        statuses: [],
        tags: [],
        createdBy: null,
        sort: { columnKey: 'when', order: -1 },
        columns: ['name', 'status', 'tags', 'when', 'recipients'],
    },
    transactional: {
        types: ['transactional'],
        search: '',
        statuses: [],
        tags: [],
        createdBy: null,
        sort: { columnKey: 'sent7d', order: -1 },
        columns: ['name', 'slug', 'status', 'tags', 'sent7d'],
    },
    workflows: {
        types: ['workflow'],
        search: '',
        statuses: [],
        tags: [],
        createdBy: null,
        sort: { columnKey: 'updated', order: -1 },
        columns: ['name', 'trigger', 'channels', 'tags', 'status'],
    },
    all: {
        types: ALL_TYPES,
        search: '',
        statuses: [],
        tags: [],
        createdBy: null,
        sort: { columnKey: 'updated', order: -1 },
        columns: ['name', 'type', 'status', 'tags', 'updated'],
    },
}

export const DEFAULT_VIEW_FOR_TYPE: Record<MessageType, Exclude<DefaultViewKey, 'all'>> = {
    broadcast: 'broadcasts',
    transactional: 'transactional',
    workflow: 'workflows',
}

const SEEDED_VIEWS: SavedView[] = [
    {
        id: 'onboarding',
        name: 'Onboarding messages',
        visibility: 'shared',
        owner: 'Sam Example',
        query: { ...DEFAULT_QUERIES.all, tags: ['onboarding'] },
    },
    {
        id: 'my-drafts',
        name: 'My draft broadcasts',
        visibility: 'private',
        owner: ME,
        query: { ...DEFAULT_QUERIES.broadcasts, statuses: ['Draft'], createdBy: ME },
    },
    {
        id: 'billing',
        name: 'Billing emails',
        visibility: 'shared',
        owner: 'Kim Example',
        query: { ...DEFAULT_QUERIES.transactional, tags: ['billing'], columns: ['name', 'slug', 'tags', 'sent7d'] },
    },
]

interface ViewsState {
    variant: ViewsVariant
    savedViews: SavedView[]
    /** Unsaved changes per view, keyed by `default:<key>` or `view:<id>`. */
    drafts: Record<string, ViewQuery>
    /** Variant B: which saved view each default list shows, or null for the default. */
    selectedView: Partial<Record<DefaultViewKey, string | null>>
    itemTags: Record<string, string[]>
}

const VARIANT_STORAGE_KEY = 'prototype-421-variant'

function initialVariant(): ViewsVariant {
    const stored = typeof window !== 'undefined' ? window.localStorage.getItem(VARIANT_STORAGE_KEY) : null
    return isViewsVariant(stored) ? stored : 'A'
}

let state: ViewsState = {
    variant: initialVariant(),
    savedViews: SEEDED_VIEWS,
    drafts: {},
    selectedView: {},
    itemTags: Object.fromEntries(MESSAGE_ITEMS.map((item) => [item.id, item.tags])),
}

const listeners = new Set<() => void>()

function setState(next: Partial<ViewsState>): void {
    state = { ...state, ...next }
    listeners.forEach((listener) => listener())
}

export function useViewsState(): ViewsState {
    return useSyncExternalStore(
        (listener) => {
            listeners.add(listener)
            return () => listeners.delete(listener)
        },
        () => state
    )
}

export function isViewsVariant(value: unknown): value is ViewsVariant {
    return typeof value === 'string' && (VIEWS_VARIANTS as readonly string[]).includes(value)
}

export function setViewsVariant(variant: ViewsVariant, updateUrl = true): void {
    window.localStorage.setItem(VARIANT_STORAGE_KEY, variant)
    setState({ variant })
    if (updateUrl) {
        router.actions.replace(
            router.values.location.pathname,
            { ...router.values.searchParams, views: variant },
            router.values.hashParams
        )
    }
}

export function defaultKey(key: DefaultViewKey): string {
    return `default:${key}`
}

export function savedKey(id: string): string {
    return `view:${id}`
}

export function savedViewForKey(key: string): SavedView | null {
    return key.startsWith('view:') ? (state.savedViews.find((v) => v.id === key.slice(5)) ?? null) : null
}

export function baseQuery(key: string): ViewQuery {
    if (key.startsWith('view:')) {
        return savedViewForKey(key)?.query ?? DEFAULT_QUERIES.all
    }
    return DEFAULT_QUERIES[key.slice(8) as DefaultViewKey] ?? DEFAULT_QUERIES.all
}

export function queryFor(s: ViewsState, key: string): ViewQuery {
    return s.drafts[key] ?? baseQuery(key)
}

function sameQuery(a: ViewQuery, b: ViewQuery): boolean {
    return JSON.stringify(a) === JSON.stringify(b)
}

export function isDirty(s: ViewsState, key: string): boolean {
    const draft = s.drafts[key]
    return !!draft && !sameQuery(draft, baseQuery(key))
}

/** What the view changes against its base, so the save prompt can say what it keeps. */
export function changedParts(s: ViewsState, key: string): string[] {
    const draft = queryFor(s, key)
    const base = baseQuery(key)
    const parts: string[] = []
    if (JSON.stringify(draft.types) !== JSON.stringify(base.types)) {
        parts.push('types')
    }
    if (
        draft.search !== base.search ||
        JSON.stringify(draft.statuses) !== JSON.stringify(base.statuses) ||
        JSON.stringify(draft.tags) !== JSON.stringify(base.tags) ||
        draft.createdBy !== base.createdBy
    ) {
        parts.push('filters')
    }
    if (JSON.stringify(draft.sort) !== JSON.stringify(base.sort)) {
        parts.push('sort')
    }
    if (JSON.stringify(draft.columns) !== JSON.stringify(base.columns)) {
        parts.push('columns')
    }
    return parts
}

export function setDraft(key: string, change: Partial<ViewQuery>): void {
    setState({ drafts: { ...state.drafts, [key]: { ...queryFor(state, key), ...change } } })
}

export function resetDraft(key: string): void {
    const drafts = { ...state.drafts }
    delete drafts[key]
    setState({ drafts })
}

export function saveViewAs(key: string, name: string, visibility: SavedView['visibility']): SavedView {
    const view: SavedView = {
        id: `${name.toLowerCase().replace(/[^a-z0-9]+/g, '-')}-${Date.now().toString(36)}`,
        name,
        visibility,
        owner: ME,
        query: queryFor(state, key),
    }
    const drafts = { ...state.drafts }
    delete drafts[key]
    setState({ savedViews: [...state.savedViews, view], drafts })
    return view
}

export function updateSavedView(id: string): void {
    const key = savedKey(id)
    const query = queryFor(state, key)
    const drafts = { ...state.drafts }
    delete drafts[key]
    setState({ savedViews: state.savedViews.map((v) => (v.id === id ? { ...v, query } : v)), drafts })
}

export function renameSavedView(id: string, name: string, visibility: SavedView['visibility']): void {
    setState({ savedViews: state.savedViews.map((v) => (v.id === id ? { ...v, name, visibility } : v)) })
}

export function deleteSavedView(id: string): void {
    setState({ savedViews: state.savedViews.filter((v) => v.id !== id) })
}

export function selectViewInList(list: DefaultViewKey, id: string | null): void {
    setState({ selectedView: { ...state.selectedView, [list]: id } })
}

export function setItemTags(itemId: string, tags: string[]): void {
    setState({ itemTags: { ...state.itemTags, [itemId]: tags } })
}

export function allTags(s: ViewsState): string[] {
    return Array.from(new Set(Object.values(s.itemTags).flat())).sort()
}

export interface ItemWithTags extends MessageItem {
    tags: string[]
}

function matchesSearch(item: ItemWithTags, search: string): boolean {
    const needle = search.trim().toLowerCase()
    if (!needle) {
        return true
    }
    return [item.name, item.slug, item.trigger, ...item.tags, ...(item.channels ?? [])]
        .filter(Boolean)
        .some((value) => value!.toLowerCase().includes(needle))
}

export function itemsFor(s: ViewsState, query: ViewQuery, ignoreTypes = false): ItemWithTags[] {
    return MESSAGE_ITEMS.map((item) => ({ ...item, tags: s.itemTags[item.id] ?? item.tags }))
        .filter((item) => ignoreTypes || query.types.includes(item.type))
        .filter((item) => (query.statuses.length ? query.statuses.includes(item.status) : item.status !== 'Archived'))
        .filter((item) => query.tags.every((tag) => item.tags.includes(tag)))
        .filter((item) => !query.createdBy || item.createdBy === query.createdBy)
        .filter((item) => matchesSearch(item, query.search))
}

const SORT_VALUE: Partial<Record<ColumnKey, (item: ItemWithTags) => string | number>> = {
    name: (item) => item.name.toLowerCase(),
    type: (item) => item.type,
    status: (item) => item.status,
    when: (item) => item.whenRank ?? 0,
    recipients: (item) => item.recipients ?? -1,
    sent7d: (item) => item.sent7d ?? 0,
    createdBy: (item) => item.createdBy,
    updated: (item) => item.updatedRank,
    trigger: (item) => item.trigger ?? '',
    slug: (item) => item.slug ?? '',
}

export function sortItems(items: ItemWithTags[], sort: ViewSort): ItemWithTags[] {
    const value = SORT_VALUE[sort.columnKey]
    if (!value) {
        return items
    }
    return [...items].sort((a, b) => {
        const left = value(a)
        const right = value(b)
        return (left < right ? -1 : left > right ? 1 : 0) * sort.order
    })
}

/** A one-line summary of a query, for the prototype's state readout and the save prompt. */
export function describeQuery(query: ViewQuery): string {
    const parts = [
        query.types.length === ALL_TYPES.length ? 'all types' : query.types.join(', '),
        query.search ? `search "${query.search}"` : null,
        query.statuses.length ? `status ${query.statuses.join(' or ')}` : 'not archived',
        query.tags.length ? `tags ${query.tags.join(' and ')}` : null,
        query.createdBy ? `created by ${query.createdBy}` : null,
        `sorted by ${COLUMN_LABELS[query.sort.columnKey].toLowerCase()} ${query.sort.order === 1 ? '↑' : '↓'}`,
        `${query.columns.length} columns`,
    ]
    return parts.filter(Boolean).join(' · ')
}
