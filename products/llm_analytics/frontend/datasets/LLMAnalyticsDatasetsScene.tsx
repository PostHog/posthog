import { useActions, useValues } from 'kea'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { Link } from 'lib/lemon-ui/Link'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
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
    const { setFilters, deleteDataset } = useActions(llmAnalyticsDatasetsLogic)
    const { datasets, datasetsLoading, sorting, pagination, filters, datasetCountLabel } =
        useValues(llmAnalyticsDatasetsLogic)

    const columns: LemonTableColumns<Dataset> = [
        {
            title: 'Name',
            dataIndex: 'name',
            key: 'name',
            width: '20%',
            render: function renderName(_, dataset) {
                return (
                    <Link to={urls.llmAnalyticsDataset(dataset.id)} data-testid="dataset-link">
                        {dataset.name}
                    </Link>
                )
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
            render: function renderCreatedBy(_, item) {
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
        {
            width: 0,
            render: function renderMore(_, dataset) {
                return (
                    <More
                        overlay={
                            <>
                                <LemonButton
                                    to={urls.llmAnalyticsDataset(dataset.id)}
                                    data-attr={`dataset-item-${dataset.id}-dropdown-view`}
                                    fullWidth
                                >
                                    View
                                </LemonButton>

                                <LemonButton
                                    status="danger"
                                    onClick={() => deleteDataset(dataset.id)}
                                    data-attr={`dataset-item-${dataset.id}-dropdown-delete`}
                                    fullWidth
                                >
                                    Delete
                                </LemonButton>
                            </>
                        }
                    />
                )
            },
        },
    ]

    return (
        <SceneContent>
            <SceneTitleSection
                name="Datasets"
                resourceType={{ type: 'llm_analytics' }}
                actions={
                    <LemonButton
                        type="primary"
                        to={urls.llmAnalyticsDataset('new')}
                        data-testid="create-dataset-button"
                        data-attr="create-dataset-button"
                        size="small"
                    >
                        New dataset
                    </LemonButton>
                }
            />
            <div className="flex gap-x-4 gap-y-2 items-center flex-wrap py-4 -mt-4 mb-4 border-b justify-between">
                <LemonInput
                    type="search"
                    placeholder="Search datasets..."
                    value={filters.search}
                    data-attr="datasets-search-input"
                    onChange={(value) => setFilters({ search: value })}
                    className="max-w-md"
                    data-testid="search-datasets-input"
                />
                <div className="text-muted-alt">{datasetCountLabel}</div>
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
        </SceneContent>
    )
}
