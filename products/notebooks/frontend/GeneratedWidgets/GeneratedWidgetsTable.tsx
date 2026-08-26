import { useActions, useValues } from 'kea'

import { IconSearch } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonInput, LemonTable, LemonTag } from '@posthog/lemon-ui'
import type { LemonTableColumns } from '@posthog/lemon-ui'

import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { humanFriendlyDetailedTime } from 'lib/utils/datetime'
import { urls } from 'scenes/urls'

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
        width: '40%',
        render: (_, widget) => {
            const label = widget.title || widget.prompt_preview || 'Untitled widget'
            return (
                <div className="min-w-0">
                    <LemonTableLink
                        to={widget.notebook_short_id ? urls.notebook(widget.notebook_short_id) : undefined}
                        truncateTitle
                        title={
                            <Tooltip title={label}>
                                <span className="min-w-0 truncate">{label}</span>
                            </Tooltip>
                        }
                    />
                </div>
            )
        },
    },
    {
        title: 'Visibility',
        key: 'visibility',
        width: 96,
        render: (_, widget) => <LemonTag type="muted">{widget.visibility === 'team' ? 'Team' : 'Private'}</LemonTag>,
    },
    {
        title: 'Owner',
        key: 'owner',
        width: 160,
        render: (_, widget) => ownerName(widget),
    },
    {
        title: 'Versions',
        key: 'version_count',
        width: 80,
        align: 'right',
        render: (_, widget) => widget.version_count,
    },
    {
        title: 'Used in',
        key: 'usage_count',
        width: 112,
        align: 'right',
        render: (_, widget) => `${widget.usage_count} notebook${widget.usage_count === 1 ? '' : 's'}`,
    },
    {
        title: 'Updated',
        key: 'updated_at',
        width: 160,
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
                rowKey="id"
                tableLayout="fixed"
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
