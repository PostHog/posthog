import { useActions, useValues } from 'kea'

import { IconSearch } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonInput, LemonTable, LemonTag } from '@posthog/lemon-ui'
import type { LemonTableColumns } from '@posthog/lemon-ui'

import { humanFriendlyDetailedTime } from 'lib/utils/datetime'

import type { WidgetCatalogApi } from 'products/notebooks/frontend/generated/api.schemas'

import { generatedWidgetsLogic } from './generatedWidgetsLogic'

function ownerName(widget: WidgetCatalogApi): string {
    if (!widget.created_by) {
        return 'Former team member'
    }
    const name = `${widget.created_by.first_name ?? ''} ${widget.created_by.last_name ?? ''}`.trim()
    return name || widget.created_by.email
}

const columns: LemonTableColumns<WidgetCatalogApi> = [
    {
        title: 'Widget',
        key: 'name',
        render: (_, widget) => (
            <div className="min-w-0">
                <div className="truncate font-semibold">{widget.name || 'Untitled widget'}</div>
                {widget.description ? <div className="truncate text-xs text-muted">{widget.description}</div> : null}
            </div>
        ),
    },
    {
        title: 'Visibility',
        key: 'visibility',
        render: (_, widget) => <LemonTag type="muted">{widget.visibility === 'team' ? 'Team' : 'Private'}</LemonTag>,
    },
    {
        title: 'Owner',
        key: 'owner',
        render: (_, widget) => ownerName(widget),
    },
    {
        title: 'Versions',
        key: 'version_count',
        align: 'right',
        render: (_, widget) => widget.version_count,
    },
    {
        title: 'Used in',
        key: 'usage_count',
        align: 'right',
        render: (_, widget) => `${widget.usage_count} notebook${widget.usage_count === 1 ? '' : 's'}`,
    },
    {
        title: 'Updated',
        key: 'updated_at',
        render: (_, widget) => humanFriendlyDetailedTime(widget.updated_at),
    },
]

export function GeneratedWidgetsTable(): JSX.Element {
    const { count, error, loading, nextOffset, search, widgets } = useValues(generatedWidgetsLogic)
    const { loadMore, loadWidgets, setSearch } = useActions(generatedWidgetsLogic)

    return (
        <div className="flex flex-col gap-3">
            <div className="flex items-center justify-between gap-3">
                <LemonInput
                    type="search"
                    value={search}
                    onChange={setSearch}
                    prefix={<IconSearch />}
                    placeholder="Search widgets"
                    className="max-w-md"
                    fullWidth
                />
                <span className="whitespace-nowrap text-sm text-muted">
                    {count} widget{count === 1 ? '' : 's'}
                </span>
            </div>
            {error ? (
                <LemonBanner type="error" action={{ children: 'Try again', onClick: () => loadWidgets(true) }}>
                    {error}
                </LemonBanner>
            ) : null}
            <LemonTable
                columns={columns}
                dataSource={widgets}
                loading={loading && widgets.length === 0}
                emptyState={
                    search
                        ? 'No widgets match this search.'
                        : 'Generated widgets will appear here after their first successful version.'
                }
            />
            {nextOffset !== null ? (
                <div className="flex justify-center">
                    <LemonButton onClick={loadMore} loading={loading}>
                        Load more
                    </LemonButton>
                </div>
            ) : null}
        </div>
    )
}
