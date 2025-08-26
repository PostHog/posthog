import { useActions, useValues } from 'kea'

import { SceneExport } from 'scenes/sceneTypes'

import { LemonInput } from '~/lib/lemon-ui/LemonInput'
import { LemonTable, LemonTableColumn, LemonTableColumns } from '~/lib/lemon-ui/LemonTable'
import { createdAtColumn, createdByColumn, updatedAtColumn } from '~/lib/lemon-ui/LemonTable/columnUtils'
import { Dataset } from '~/types'

import { DATASETS_PER_PAGE, llmAnalyticsDatasetsLogic } from './llmAnalyticsDatasetsLogic'

export const scene: SceneExport = {
    component: LLMAnalyticsDatasetsScene,
    logic: llmAnalyticsDatasetsLogic,
}

export function LLMAnalyticsDatasetsScene(): JSX.Element {
    const { setFilters } = useActions(llmAnalyticsDatasetsLogic)
    const { datasets, datasetsLoading, sorting, pagination, filters } = useValues(llmAnalyticsDatasetsLogic)

    const columns: LemonTableColumns<Dataset> = [
        {
            title: 'Name',
            dataIndex: 'name',
            key: 'name',
            sorter: true,
            render: function renderName(name) {
                return <span className="font-medium">{name}</span>
            },
        },
        {
            title: 'Description',
            dataIndex: 'description',
            key: 'description',
            render: function renderDescription(description) {
                return <span className="text-muted">{description || <i>No description</i>}</span>
            },
        },
        createdByColumn<Dataset>() as LemonTableColumn<Dataset, keyof Dataset | undefined>,
        createdAtColumn<Dataset>() as LemonTableColumn<Dataset, keyof Dataset | undefined>,
        updatedAtColumn<Dataset>() as LemonTableColumn<Dataset, keyof Dataset | undefined>,
    ]

    return (
        <div className="space-y-4">
            <div className="flex justify-between items-center">
                <h1 className="text-2xl font-semibold">Datasets</h1>
            </div>

            <div className="flex justify-between items-center gap-4">
                <LemonInput
                    type="search"
                    placeholder="Search datasets..."
                    value={filters.search}
                    onChange={(value) => setFilters({ search: value })}
                    className="max-w-md"
                />
                <div className="text-muted-alt">
                    {datasets.count} dataset{datasets.count === 1 ? '' : 's'}
                </div>
            </div>

            <LemonTable
                loading={datasetsLoading}
                columns={columns}
                dataSource={datasets.results}
                pagination={pagination}
                noSortingCancellation
                sorting={sorting}
                onSort={(newSorting) =>
                    setFilters({
                        order_by: newSorting
                            ? `${newSorting.order === -1 ? '-' : ''}${newSorting.columnKey}`
                            : undefined,
                    })
                }
                rowKey="id"
                loadingSkeletonRows={DATASETS_PER_PAGE}
                nouns={['dataset', 'datasets']}
            />
        </div>
    )
}
