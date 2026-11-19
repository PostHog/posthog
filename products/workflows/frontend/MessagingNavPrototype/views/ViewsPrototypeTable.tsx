// PROTOTYPE, never merged: PostHog/michaelr-context#421. One table for every view: the view's columns and sort decide
// what it shows, so a default view and a saved view render the same way.
import { LemonTable, LemonTableColumn, LemonTag, Link } from '@posthog/lemon-ui'

import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'

import { MESSAGING_SECTION_ICONS } from '~/layout/today/messagingNavPrototype/messagingNavPrototypeNav'

import { TYPE_LABELS } from './viewsPrototypeData'
import {
    COLUMN_LABELS,
    ColumnKey,
    DEFAULT_VIEW_FOR_TYPE,
    ItemWithTags,
    ViewQuery,
    ViewSort,
    allTags,
    setItemTags,
    useViewsState,
} from './viewsPrototypeStore'

const STATUS_TAG: Record<string, 'default' | 'highlight' | 'success' | 'muted'> = {
    Draft: 'default',
    Scheduled: 'highlight',
    Sent: 'success',
    Live: 'success',
    Archived: 'muted',
}

const SORTABLE: ColumnKey[] = ['name', 'type', 'status', 'when', 'recipients', 'sent7d', 'createdBy', 'updated', 'slug']

function render(
    key: ColumnKey,
    item: ItemWithTags,
    tagsAvailable: string[],
    onTagClick?: (tag: string) => void
): JSX.Element | string | null {
    switch (key) {
        case 'name':
            return <Link className="font-semibold">{item.name}</Link>
        case 'type':
            return (
                <span className="flex items-center gap-1 text-secondary">
                    {MESSAGING_SECTION_ICONS[DEFAULT_VIEW_FOR_TYPE[item.type]]}
                    {TYPE_LABELS[item.type]}
                </span>
            )
        case 'status':
            return <LemonTag type={STATUS_TAG[item.status]}>{item.status}</LemonTag>
        case 'tags':
            return (
                <ObjectTags
                    tags={item.tags}
                    tagsAvailable={tagsAvailable}
                    onChange={(tags) => setItemTags(item.id, tags)}
                    onTagClick={onTagClick}
                    saving={false}
                    compact
                />
            )
        case 'when':
            return item.when ?? '–'
        case 'recipients':
            return item.recipients === null || item.recipients === undefined ? '–' : item.recipients.toLocaleString()
        case 'slug':
            return item.slug ? <code className="text-xs">{item.slug}</code> : '–'
        case 'sent7d':
            return item.sent7d === undefined ? '–' : item.sent7d.toLocaleString()
        case 'trigger':
            return item.trigger ?? '–'
        case 'channels':
            return (
                <div className="flex flex-wrap gap-1">
                    {(item.channels ?? []).map((c) => (
                        <LemonTag key={c} type="muted">
                            {c}
                        </LemonTag>
                    ))}
                </div>
            )
        case 'createdBy':
            return item.createdBy
        case 'updated':
            return item.updated
    }
}

export function ViewsPrototypeTable({
    items,
    query,
    onSort,
    onTagClick,
    emptyState,
}: {
    items: ItemWithTags[]
    query: ViewQuery
    onSort: (sort: ViewSort) => void
    onTagClick?: (tag: string) => void
    emptyState?: string
}): JSX.Element {
    const state = useViewsState()
    const tagsAvailable = allTags(state)
    const columns: LemonTableColumn<ItemWithTags, any>[] = query.columns.map((key) => ({
        key,
        title: COLUMN_LABELS[key],
        align: key === 'recipients' || key === 'sent7d' ? 'right' : undefined,
        sorter: SORTABLE.includes(key) ? () => 0 : undefined,
        render: (_: unknown, item: ItemWithTags) => render(key, item, tagsAvailable, onTagClick),
    }))
    return (
        <LemonTable
            dataSource={items}
            columns={columns}
            rowKey="id"
            useURLForSorting={false}
            // The view owns its sort, so the table only reports header clicks and shows rows in the order given.
            sorting={{ columnKey: query.sort.columnKey, order: query.sort.order }}
            onSort={(sorting) =>
                sorting && onSort({ columnKey: sorting.columnKey as ColumnKey, order: sorting.order === 1 ? 1 : -1 })
            }
            noSortingCancellation
            emptyState={emptyState ?? 'Nothing matches these filters'}
        />
    )
}
