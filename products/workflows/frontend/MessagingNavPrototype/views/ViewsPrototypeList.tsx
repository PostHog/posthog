// PROTOTYPE, never merged: PostHog/michaelr-context#421. A default view or a saved view, with the toolbar of the
// variant: A quick filter chips, B the app's dropdowns and view menu, C one search bar with tokens, D today's toolbar.
import { useValues } from 'kea'
import { router } from 'kea-router'
import { useEffect, useState } from 'react'

import { IconCheck, IconGlobe, IconPin, IconUser } from '@posthog/icons'
import { LemonButton, LemonInput, LemonMenu, LemonSelect, LemonTag, Link } from '@posthog/lemon-ui'

import { LemonDialog } from 'lib/lemon-ui/LemonDialog'

import {
    MESSAGING_SECTION_LABELS,
    messagingSectionUrl,
} from '~/layout/today/messagingNavPrototype/messagingNavPrototypeNav'

import { ColumnsButton } from './ColumnsButton'
import { FacetSearchBar } from './FacetSearchBar'
import { QuickFilterChips } from './QuickFilterChips'
import { SaveViewModal } from './SaveViewModal'
import { ViewMenu } from './ViewMenu'
import { ME, MessageStatus, MessageType, PEOPLE, STATUSES_BY_TYPE, TYPE_PLURALS } from './viewsPrototypeData'
import {
    ALL_TYPES,
    DEFAULT_QUERIES,
    DEFAULT_VIEW_FOR_TYPE,
    DefaultViewKey,
    SavedView,
    ViewQuery,
    allTags,
    changedParts,
    defaultKey,
    deleteSavedView,
    describeQuery,
    isDirty,
    itemsFor,
    queryFor,
    renameSavedView,
    resetDraft,
    saveViewAs,
    savedKey,
    selectViewInList,
    setDraft,
    sortItems,
    updateSavedView,
    useViewsState,
} from './viewsPrototypeStore'
import { ViewsPrototypeTable } from './ViewsPrototypeTable'

export function savedViewUrl(id: string): string {
    return `/messaging/view-${id}`
}

const SEARCH_PLACEHOLDER: Record<DefaultViewKey, string> = {
    broadcasts: 'Search broadcasts',
    transactional: 'Search transactional emails',
    workflows: 'Search messaging workflows',
    all: 'Search every message',
}

function sameTypes(a: MessageType[], b: MessageType[]): boolean {
    return a.length === b.length && a.every((t) => b.includes(t))
}

/** Variant B: when a search finds nothing here but something in another list, say where. */
function AlsoMatches({ query }: { query: ViewQuery }): JSX.Element | null {
    const state = useViewsState()
    if (!query.search.trim()) {
        return null
    }
    const others = ALL_TYPES.filter((type) => !query.types.includes(type))
        .map((type) => ({
            type,
            count: itemsFor(state, { ...DEFAULT_QUERIES.all, types: [type], search: query.search }).length,
        }))
        .filter((o) => o.count > 0)
    if (!others.length) {
        return null
    }
    return (
        <div className="text-xs text-secondary">
            Also matches "{query.search}":{' '}
            {others.map((o, i) => (
                <span key={o.type}>
                    {i > 0 && ' · '}
                    <Link
                        onClick={() => {
                            const list = DEFAULT_VIEW_FOR_TYPE[o.type]
                            selectViewInList(list, null)
                            setDraft(defaultKey(list), { search: query.search })
                            router.actions.push(messagingSectionUrl(list as 'broadcasts'))
                        }}
                    >
                        {o.count} {o.count === 1 ? TYPE_PLURALS[o.type].replace(/s$/, '') : TYPE_PLURALS[o.type]}
                    </Link>
                </span>
            ))}
        </div>
    )
}

function TagsMenu({ query, onChange }: { query: ViewQuery; onChange: (tags: string[]) => void }): JSX.Element {
    const state = useViewsState()
    return (
        <LemonMenu
            closeOnClickInside={false}
            items={allTags(state).map((tag) => ({
                label: tag,
                icon: query.tags.includes(tag) ? <IconCheck /> : <span className="size-4" />,
                onClick: () =>
                    onChange(query.tags.includes(tag) ? query.tags.filter((t) => t !== tag) : [...query.tags, tag]),
            }))}
        >
            <LemonButton size="small" type="secondary">
                {query.tags.length ? `Tags: ${query.tags.join(', ')}` : 'Any tags'}
            </LemonButton>
        </LemonMenu>
    )
}

/** Today's list toolbar, unchanged: search, then the Status, Created by and Tags filters. */
function TodayToolbar({
    list,
    query,
    statuses,
    onChange,
}: {
    list: DefaultViewKey | null
    query: ViewQuery
    statuses: MessageStatus[]
    onChange: (change: Partial<ViewQuery>) => void
}): JSX.Element {
    return (
        <div className="flex flex-wrap items-center justify-between gap-2">
            <LemonInput
                type="search"
                size="small"
                className="max-w-80 flex-1"
                placeholder={list ? SEARCH_PLACEHOLDER[list] : 'Search this view'}
                value={query.search}
                onChange={(search) => onChange({ search })}
                data-attr="messaging-prototype-list-search"
            />
            <div className="flex flex-wrap items-center gap-2">
                <b>Status</b>
                <LemonSelect
                    size="small"
                    dropdownMatchSelectWidth={false}
                    value={query.statuses[0] ?? 'all'}
                    onChange={(value) => onChange({ statuses: value === 'all' ? [] : [value as MessageStatus] })}
                    options={[{ value: 'all', label: 'All' }, ...statuses.map((s) => ({ value: s, label: s }))]}
                    data-attr="messaging-prototype-status-filter"
                />
                <b className="ml-1">Created by</b>
                <LemonSelect
                    size="small"
                    dropdownMatchSelectWidth={false}
                    value={query.createdBy ?? 'anyone'}
                    onChange={(value) => onChange({ createdBy: value === 'anyone' ? null : value })}
                    options={[
                        { value: 'anyone', label: 'Anyone' },
                        ...PEOPLE.map((p) => ({ value: p, label: p === ME ? `${p} (you)` : p })),
                    ]}
                />
                <b className="ml-1">Tags</b>
                <TagsMenu query={query} onChange={(tags) => onChange({ tags })} />
            </div>
        </div>
    )
}

function StateReadout({
    query,
    changes,
    showLink,
}: {
    query: ViewQuery
    changes: string[]
    showLink?: boolean
}): JSX.Element {
    const { location } = useValues(router)
    return (
        <div className="rounded border border-dashed px-2 py-1 font-mono text-[11px] text-secondary">
            Prototype state: {describeQuery(query)}
            {showLink
                ? ` · link: ${location.pathname}${location.search}`
                : changes.length
                  ? ` · unsaved: ${changes.join(', ')}`
                  : ' · no unsaved changes'}
        </div>
    )
}

function confirmDelete(view: SavedView, after: () => void): void {
    LemonDialog.open({
        title: 'Delete view',
        description: `Delete the view "${view.name}"? The messages in it stay.`,
        primaryButton: {
            children: 'Delete',
            status: 'danger',
            onClick: () => {
                deleteSavedView(view.id)
                after()
            },
        },
        secondaryButton: { children: 'Cancel' },
    })
}

export function ViewsPrototypeList({
    list,
    viewId,
}: {
    /** The default view this route shows, or null on a saved view's own route. */
    list: DefaultViewKey | null
    viewId?: string | null
}): JSX.Element {
    const state = useViewsState()
    const [modal, setModal] = useState<'save' | 'edit' | null>(null)
    const [editing, setEditing] = useState<SavedView | null>(null)
    const variant = state.variant

    const selectedInList = variant === 'B' && list ? (state.selectedView[list] ?? null) : null
    const savedId = viewId ?? selectedInList
    const savedView = savedId ? (state.savedViews.find((v) => v.id === savedId) ?? null) : null
    const key = savedView ? savedKey(savedView.id) : defaultKey(list ?? 'all')
    const query = queryFor(state, key)
    const dirty = isDirty(state, key)
    const changes = changedParts(state, key)
    const items = sortItems(itemsFor(state, query), query.sort)
    const change = (c: Partial<ViewQuery>): void => {
        if (c.types && c.types.length > 1 && !query.columns.includes('type')) {
            c = { ...c, columns: ['name', 'type', ...query.columns.filter((col) => col !== 'name')] }
        }
        setDraft(key, c)
    }
    const clearFilters = (): void => change({ search: '', statuses: [], tags: [], createdBy: null })
    const addTagFilter = (tag: string): void =>
        change({ tags: query.tags.includes(tag) ? query.tags : [...query.tags, tag] })

    const save = (name: string, visibility: SavedView['visibility']): void => {
        if (modal === 'edit' && editing) {
            renameSavedView(editing.id, name, visibility)
        } else {
            const view = saveViewAs(key, name, visibility)
            if (variant === 'B' && list) {
                selectViewInList(list, view.id)
            } else {
                router.actions.push(savedViewUrl(view.id))
            }
        }
        setModal(null)
        setEditing(null)
    }

    const leaveAfterDelete = (view: SavedView): void => {
        const home = view.query.types.length === 1 ? DEFAULT_VIEW_FOR_TYPE[view.query.types[0]] : 'broadcasts'
        if (variant === 'B' && list) {
            selectViewInList(list, null)
        } else {
            router.actions.push(messagingSectionUrl(home as 'broadcasts'))
        }
    }

    const saveButtons = savedView
        ? dirty && (
              <>
                  <LemonButton size="small" type="primary" onClick={() => updateSavedView(savedView.id)}>
                      Update view
                  </LemonButton>
                  {variant !== 'B' && (
                      <LemonButton size="small" type="secondary" onClick={() => setModal('save')}>
                          Save as new
                      </LemonButton>
                  )}
                  <LemonButton size="small" type="tertiary" onClick={() => resetDraft(key)}>
                      Discard changes
                  </LemonButton>
              </>
          )
        : dirty &&
          variant !== 'B' &&
          variant !== 'D' && (
              <>
                  <LemonButton
                      size="small"
                      type="primary"
                      icon={variant === 'C' ? <IconPin /> : undefined}
                      onClick={() => setModal('save')}
                      data-attr="messaging-prototype-save-view"
                  >
                      {variant === 'C' ? 'Pin as view' : 'Save as view'}
                  </LemonButton>
                  <LemonButton size="small" type="tertiary" onClick={() => resetDraft(key)}>
                      Reset
                  </LemonButton>
              </>
          )

    // Variant D keeps today's filters in the URL, with the same `search` and `status` names the `workflows-list` tool
    // takes.
    const urlSearch = String(router.values.searchParams.search ?? '')
    const urlStatus = String(router.values.searchParams.status ?? '')
    const urlCreatedBy = String(router.values.searchParams.created_by ?? '')
    const urlTags = String(router.values.searchParams.tags ?? '')
    useEffect(() => {
        if (variant === 'D' && !savedView && (urlSearch || urlStatus || urlCreatedBy || urlTags)) {
            setDraft(key, {
                search: urlSearch,
                statuses: urlStatus ? (urlStatus.split(',') as MessageStatus[]) : [],
                createdBy: urlCreatedBy || null,
                tags: urlTags ? urlTags.split(',') : [],
            })
        }
        // Only on arrival, so typing is not overwritten by the URL it writes.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [key, variant])
    useEffect(() => {
        if (variant !== 'D' || savedView) {
            return
        }
        const {
            search: _search,
            status: _status,
            created_by: _createdBy,
            tags: _tags,
            ...rest
        } = router.values.searchParams
        router.actions.replace(router.values.location.pathname, {
            ...rest,
            ...(query.search ? { search: query.search } : {}),
            ...(query.statuses.length ? { status: query.statuses.join(',') } : {}),
            ...(query.createdBy ? { created_by: query.createdBy } : {}),
            ...(query.tags.length ? { tags: query.tags.join(',') } : {}),
        })
    }, [variant, savedView, query.search, query.statuses, query.createdBy, query.tags])

    const statuses = Array.from(new Set(query.types.flatMap((t) => STATUSES_BY_TYPE[t]))) as MessageStatus[]
    const views = state.savedViews.filter((v) => list && sameTypes(v.query.types, DEFAULT_QUERIES[list].types))

    return (
        <div className="flex flex-col gap-3">
            {savedView && variant !== 'B' && (
                <div className="flex flex-wrap items-center gap-2 text-xs text-secondary">
                    <LemonTag type="muted">Saved view</LemonTag>
                    {savedView.visibility === 'private' ? <IconUser /> : <IconGlobe />}
                    <span>
                        {savedView.visibility === 'private'
                            ? 'Only you see this view'
                            : `Shared with the team by ${savedView.owner === ME ? 'you' : savedView.owner}`}
                    </span>
                    <LemonButton
                        size="xsmall"
                        type="tertiary"
                        onClick={() => {
                            setEditing(savedView)
                            setModal('edit')
                        }}
                    >
                        Edit
                    </LemonButton>
                    <LemonButton
                        size="xsmall"
                        type="tertiary"
                        status="danger"
                        onClick={() => confirmDelete(savedView, () => leaveAfterDelete(savedView))}
                    >
                        Delete
                    </LemonButton>
                </div>
            )}
            {!savedView && list && variant !== 'B' && (
                <div className="flex items-center gap-2 text-xs text-secondary">
                    <LemonTag type="muted">Default view</LemonTag>
                    <span>
                        {variant === 'C'
                            ? 'A default view is a search that starts with a type. Change it, then pin it as your own view.'
                            : variant === 'D'
                              ? 'The list as it is today, tags included. The link now keeps the search and filters, so you can bookmark or share it.'
                              : 'Filter, sort or pick columns, then save it as your own view.'}
                    </span>
                </div>
            )}

            {variant === 'A' && (
                <>
                    <div className="flex flex-wrap items-center justify-between gap-2">
                        <LemonInput
                            type="search"
                            size="small"
                            className="max-w-80 flex-1"
                            placeholder={list ? SEARCH_PLACEHOLDER[list] : 'Search this view'}
                            value={query.search}
                            onChange={(search) => change({ search })}
                            data-attr="messaging-prototype-list-search"
                        />
                        <div className="flex flex-wrap items-center gap-2">
                            {saveButtons}
                            <ColumnsButton query={query} onChange={(columns) => change({ columns })} />
                        </div>
                    </div>
                    <QuickFilterChips query={query} onChange={change} onClear={clearFilters} />
                </>
            )}

            {variant === 'D' && <TodayToolbar list={list} query={query} statuses={statuses} onChange={change} />}

            {variant === 'B' && list && (
                <>
                    <div className="flex flex-wrap items-center justify-between gap-2">
                        <div className="flex flex-wrap items-center gap-2">
                            <ViewMenu
                                views={views}
                                current={savedView}
                                defaultLabel={`All ${MESSAGING_SECTION_LABELS[list as 'broadcasts'].toLowerCase()}`}
                                onSelect={(id) => selectViewInList(list, id)}
                                onCreate={() => setModal('save')}
                                onEdit={(view) => {
                                    setEditing(view)
                                    setModal('edit')
                                }}
                                onDelete={(view) => confirmDelete(view, () => leaveAfterDelete(view))}
                            />
                            {saveButtons}
                        </div>
                        <ColumnsButton query={query} onChange={(columns) => change({ columns })} />
                    </div>
                    <TodayToolbar list={list} query={query} statuses={statuses} onChange={change} />
                    <AlsoMatches query={query} />
                </>
            )}

            {variant === 'C' && (
                <>
                    <div className="flex items-start gap-2">
                        <FacetSearchBar query={query} onChange={change} />
                        <ColumnsButton query={query} onChange={(columns) => change({ columns })} iconOnly />
                    </div>
                    <div className="flex flex-wrap items-center justify-between gap-2">
                        <div className="flex flex-wrap items-center gap-2 text-xs text-secondary">
                            <span>Quick filters:</span>
                            {statuses
                                .filter((s) => s !== 'Archived')
                                .map((s) => (
                                    <Link key={s} onClick={() => change({ statuses: [s] })}>
                                        {s}
                                    </Link>
                                ))}
                            <Link onClick={() => change({ createdBy: ME })}>Created by me</Link>
                            {query.types.length < ALL_TYPES.length && (
                                <Link onClick={() => change({ types: ALL_TYPES })}>Every type</Link>
                            )}
                        </div>
                        <div className="flex flex-wrap items-center gap-2">{saveButtons}</div>
                    </div>
                </>
            )}

            <ViewsPrototypeTable
                items={items}
                query={query}
                onSort={(sort) => change({ sort })}
                onTagClick={addTagFilter}
            />
            <StateReadout query={query} changes={changes} showLink={variant === 'D'} />

            <SaveViewModal
                isOpen={modal !== null}
                query={query}
                editing={modal === 'edit' ? editing : null}
                title={modal === 'save' && variant === 'C' ? 'Pin this search as a view' : undefined}
                onClose={() => {
                    setModal(null)
                    setEditing(null)
                }}
                onSave={save}
            />
        </div>
    )
}
