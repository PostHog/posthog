import { useActions, useValues } from 'kea'

import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { SceneExport } from 'scenes/sceneTypes'

import { LemonInput } from '~/lib/lemon-ui/LemonInput'
import { LemonTable, LemonTableColumn, LemonTableColumns } from '~/lib/lemon-ui/LemonTable'
import { createdAtColumn, updatedAtColumn } from '~/lib/lemon-ui/LemonTable/columnUtils'
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
            width: '20%',
            render: function renderName(name) {
                return <span className="font-medium">{name}</span>
            },
        },
        {
            title: 'Description',
            dataIndex: 'description',
            key: 'description',
            width: '50%',
            render: function renderDescription(description) {
                return <span className="text-muted">{description || <i>–</i>}</span>
            },
        },
        {
            title: 'Created by',
            dataIndex: 'created_by',
            render: function renderCreatedBy(_: any, item) {
                const { created_by } = item
                return (
                    <div className="flex flex-row items-center flex-nowrap">
                        {created_by && <ProfilePicture user={created_by} size="md" showName />}
                    </div>
                )
            },
        },
        createdAtColumn<Dataset>() as LemonTableColumn<Dataset, keyof Dataset | undefined>,
        updatedAtColumn<Dataset>() as LemonTableColumn<Dataset, keyof Dataset | undefined>,
    ]

    const { currentPage, pageSize, entryCount } = pagination

    const start = (currentPage - 1) * pageSize + 1
    const end = Math.min(currentPage * pageSize, entryCount)

    return (
        <div className="space-y-4">
            <div className="flex gap-x-4 gap-y-2 items-center flex-wrap py-4 -mt-4 mb-4 border-b justify-between">
                <LemonInput
                    type="search"
                    placeholder="Search datasets..."
                    value={filters.search}
                    onChange={(value) => setFilters({ search: value })}
                    className="max-w-md"
                />
                <div className="text-muted-alt">
                    {entryCount === 0
                        ? '0 datasets'
                        : `${start}-${end} of ${entryCount} dataset${entryCount === 1 ? '' : 's'}`}
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
