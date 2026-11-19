// PROTOTYPE, never merged: PostHog/michaelr-context#421. Variant A: the sidebar's search finds every message type and
// lists the hits per type, each group linking to its default view with the same search.
import { useValues } from 'kea'
import { router } from 'kea-router'

import { LemonInput, Link } from '@posthog/lemon-ui'

import {
    MESSAGING_SECTION_ICONS,
    MESSAGING_SECTION_LABELS,
    messagingSectionUrl,
} from '~/layout/today/messagingNavPrototype/messagingNavPrototypeNav'

import {
    ALL_TYPES,
    DEFAULT_QUERIES,
    DEFAULT_VIEW_FOR_TYPE,
    ViewQuery,
    defaultKey,
    itemsFor,
    setDraft,
    sortItems,
    useViewsState,
} from './viewsPrototypeStore'
import { ViewsPrototypeTable } from './ViewsPrototypeTable'

export const MESSAGING_SEARCH_PATH = '/messaging/search'

export function MessagingSearchResults(): JSX.Element {
    const { searchParams } = useValues(router)
    const state = useViewsState()
    const q = String(searchParams.q ?? '')
    const groups = ALL_TYPES.map((type) => {
        const list = DEFAULT_VIEW_FOR_TYPE[type]
        const query: ViewQuery = {
            ...DEFAULT_QUERIES[list],
            search: q,
            statuses: ['Draft', 'Scheduled', 'Sent', 'Live', 'Archived'],
            columns: ['name', 'status', 'tags', 'updated'],
            sort: { columnKey: 'updated', order: -1 },
        }
        return { type, list, query, items: sortItems(itemsFor(state, query), query.sort) }
    })
    const total = groups.reduce((sum, g) => sum + g.items.length, 0)

    return (
        <div className="flex flex-col gap-4">
            <LemonInput
                type="search"
                autoFocus
                placeholder="Search broadcasts, transactional emails and messaging workflows"
                value={q}
                onChange={(value) => router.actions.replace(MESSAGING_SEARCH_PATH, { ...searchParams, q: value })}
            />
            {!q.trim() ? (
                <div className="text-secondary">Type a name, an email ID, a trigger or a tag.</div>
            ) : (
                <div className="text-xs text-secondary">
                    {total} {total === 1 ? 'result' : 'results'} for "{q}", archived included
                </div>
            )}
            {q.trim() &&
                groups
                    .filter((g) => g.items.length)
                    .map((g) => (
                        <div key={g.type} className="flex flex-col gap-2">
                            <div className="flex items-center justify-between">
                                <h3 className="m-0 flex items-center gap-2 text-base font-semibold">
                                    {MESSAGING_SECTION_ICONS[g.list]}
                                    {MESSAGING_SECTION_LABELS[g.list]}
                                    <span className="text-secondary font-normal">{g.items.length}</span>
                                </h3>
                                <Link
                                    onClick={() => {
                                        setDraft(defaultKey(g.list), { search: q })
                                        router.actions.push(messagingSectionUrl(g.list))
                                    }}
                                >
                                    Open in {MESSAGING_SECTION_LABELS[g.list]}
                                </Link>
                            </div>
                            <ViewsPrototypeTable items={g.items} query={g.query} onSort={() => {}} />
                        </div>
                    ))}
        </div>
    )
}
