import { useActions, useValues } from 'kea'

import { IconSearch } from '@posthog/icons'
import { LemonBanner, LemonInput, LemonTag } from '@posthog/lemon-ui'

import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { LemonTable, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { Link } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import type { ReusableWidgetSummaryApi } from 'products/notebooks/frontend/generated/api.schemas'

import { reusableWidgetCatalogLogic } from './reusableWidgetCatalogLogic'

export function ReusableWidgetCatalog(): JSX.Element {
    const { pagination, reusableWidgets, reusableWidgetsError, reusableWidgetsResponseLoading, search } =
        useValues(reusableWidgetCatalogLogic)
    const { loadReusableWidgets, setSearch } = useActions(reusableWidgetCatalogLogic)

    useOnMountEffect(loadReusableWidgets)

    const columns: LemonTableColumns<ReusableWidgetSummaryApi> = [
        {
            title: 'Widget',
            dataIndex: 'name',
            width: '100%',
            render: function Render(_, widget) {
                return (
                    <div className="flex flex-col gap-1 py-1">
                        <Link className="font-semibold" to={urls.reusableWidget(widget.id)}>
                            {widget.name}
                        </Link>
                        {widget.description ? <span className="text-secondary">{widget.description}</span> : null}
                        {widget.tags.length ? (
                            <div className="flex flex-wrap gap-1">
                                {widget.tags.map((tag) => (
                                    <LemonTag key={tag} size="small">
                                        {tag}
                                    </LemonTag>
                                ))}
                            </div>
                        ) : null}
                    </div>
                )
            },
        },
        {
            title: 'Versions',
            dataIndex: 'version_count',
        },
        {
            title: 'Used in',
            dataIndex: 'instance_count',
            render: (count) => `${count} placement${count === 1 ? '' : 's'}`,
        },
        {
            title: 'Updated',
            dataIndex: 'updated_at',
            render: (_, widget) => new Date(widget.updated_at).toLocaleDateString(),
        },
    ]

    return (
        <div className="flex flex-col gap-4">
            <div className="max-w-xl">
                <LemonInput
                    type="search"
                    value={search}
                    prefix={<IconSearch />}
                    placeholder="Search reusable widgets"
                    onChange={setSearch}
                    data-attr="reusable-widget-search"
                />
            </div>
            {reusableWidgetsError ? (
                <LemonBanner type="error" action={{ children: 'Retry', onClick: loadReusableWidgets }}>
                    We couldn't load reusable widgets.
                </LemonBanner>
            ) : null}
            <LemonTable
                dataSource={reusableWidgets}
                columns={columns}
                rowKey="id"
                loading={reusableWidgetsResponseLoading}
                pagination={pagination}
                emptyState="No reusable widgets yet. Convert a generated notebook widget to add it here."
                nouns={['reusable widget', 'reusable widgets']}
            />
        </div>
    )
}
