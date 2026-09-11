import { useActions, useValues } from 'kea'

import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonTable } from 'lib/lemon-ui/LemonTable'
import { PaginationControl, usePagination } from 'lib/lemon-ui/PaginationControl'
import { formatPercentage } from 'lib/utils/numbers'

import { HogQLFilters, MCPModelBreakdownItem } from '~/queries/schema/schema-general'

import { formatNumber } from './formatters'
import { MODEL_PAGE_SIZE, modelBreakdownLogic } from './modelBreakdownLogic'

export function ModelBreakdownTable({
    filters,
    totalCalls,
}: {
    filters: HogQLFilters
    totalCalls: number
}): JSX.Element {
    const logic = modelBreakdownLogic({ filters })
    const { modelPage, modelPageLoading, loadFailed, requestedOffset } = useValues(logic)
    const { loadModels } = useActions(logic)
    const pagination = usePagination(modelPage?.results ?? [], {
        controlled: true,
        useUrl: false,
        hideOnSinglePage: false,
        onForward:
            modelPage?.hasMore && !modelPageLoading ? () => loadModels(modelPage.offset + MODEL_PAGE_SIZE) : undefined,
        onBackward:
            modelPage && modelPage.offset > 0 && !modelPageLoading
                ? () => loadModels(Math.max(0, modelPage.offset - MODEL_PAGE_SIZE))
                : undefined,
    })

    if (loadFailed) {
        return (
            <LemonBanner type="error" action={{ children: 'Retry', onClick: () => loadModels(requestedOffset) }}>
                Couldn't load models. Try again.
            </LemonBanner>
        )
    }

    return (
        <div className="flex flex-col gap-2">
            <div className="h-96">
                <LemonTable<MCPModelBreakdownItem>
                    key={modelPage?.offset ?? 0}
                    dataSource={modelPage?.results ?? []}
                    rowKey="model"
                    size="small"
                    embedded
                    tableLayout="fixed"
                    allowContentScroll
                    uppercaseHeader={false}
                    loading={modelPageLoading}
                    loadingSkeletonRows={3}
                    disableTableWhileLoading
                    nouns={['model', 'models']}
                    emptyState="No reported models match these filters."
                    columns={[
                        {
                            title: 'Model',
                            dataIndex: 'model',
                            render: (_, row) => (
                                <span className="break-all" translate="no">
                                    {row.model}
                                </span>
                            ),
                        },
                        {
                            title: 'Calls',
                            width: 75,
                            align: 'right',
                            render: (_, row) => (
                                <span className="tabular-nums" title={String(row.total_calls)}>
                                    {formatNumber(row.total_calls)}
                                </span>
                            ),
                        },
                        {
                            title: '% of all calls',
                            width: 100,
                            align: 'right',
                            render: (_, row) => (
                                <span className="tabular-nums">
                                    {formatPercentage(totalCalls > 0 ? (row.total_calls / totalCalls) * 100 : 0, {
                                        compact: true,
                                    })}
                                </span>
                            ),
                        },
                    ]}
                />
            </div>
            <PaginationControl {...pagination} nouns={['model', 'models']} />
        </div>
    )
}
