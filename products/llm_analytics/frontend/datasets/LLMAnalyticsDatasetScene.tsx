import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { combineUrl, router } from 'kea-router'

import { IconTrash } from '@posthog/icons'
import { LemonButton, LemonDivider, LemonTab, LemonTabs, Link, ProfilePicture } from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { PageHeader } from 'lib/components/PageHeader'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { createdAtColumn, updatedAtColumn } from 'lib/lemon-ui/LemonTable/columnUtils'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { ScenePanel, ScenePanelActions, ScenePanelDivider, ScenePanelMetaInfo } from '~/layout/scenes/SceneLayout'
import { SceneTextInput } from '~/lib/components/Scenes/SceneTextInput'
import { SceneTextarea } from '~/lib/components/Scenes/SceneTextarea'
import { LemonTable, LemonTableColumn, LemonTableColumns } from '~/lib/lemon-ui/LemonTable'
import { DatasetItem } from '~/types'

import { EditDatasetForm } from './EditDatasetForm'
import { RefreshButton } from './RefreshButton'
import { DatasetLogicProps, DatasetTab, llmAnalyticsDatasetLogic } from './llmAnalyticsDatasetLogic'

const RESOURCE_TYPE = 'dataset'

export const scene: SceneExport<DatasetLogicProps> = {
    component: LLMAnalyticsDatasetScene,
    logic: llmAnalyticsDatasetLogic,
    paramsToProps: ({ params: { id } }) => ({
        datasetId: id && id !== 'new' ? id : 'new',
    }),
}

export function LLMAnalyticsDatasetScene(): JSX.Element {
    const { datasetLoading, isDatasetFormSubmitting, isEditingDataset, datasetMissing, isNewDataset, datasetForm } =
        useValues(llmAnalyticsDatasetLogic)
    const { submitDatasetForm, loadDataset, editDataset, deleteDataset, setDatasetFormValue } =
        useActions(llmAnalyticsDatasetLogic)

    const displayEditForm = isNewDataset || isEditingDataset

    if (datasetMissing) {
        return <NotFound object="dataset" />
    }

    if (datasetLoading) {
        return (
            <div className="flex flex-col gap-2">
                <LemonSkeleton active className="h-4 w-2/5" />
                <LemonSkeleton active className="h-4 w-full" />
                <LemonSkeleton active className="h-4 w-full" />
                <LemonSkeleton active className="h-4 w-3/5" />
            </div>
        )
    }

    return (
        <Form id="dataset-form" formKey="datasetForm" logic={llmAnalyticsDatasetLogic}>
            <PageHeader
                buttons={
                    !datasetLoading ? (
                        displayEditForm ? (
                            <>
                                <LemonButton
                                    type="secondary"
                                    data-attr="cancel-dataset"
                                    onClick={() => {
                                        if (isEditingDataset) {
                                            editDataset(false)
                                            loadDataset()
                                        } else {
                                            router.actions.push(urls.llmAnalyticsDatasets())
                                        }
                                    }}
                                    disabledReason={isDatasetFormSubmitting ? 'Saving…' : undefined}
                                >
                                    Cancel
                                </LemonButton>
                                <LemonButton
                                    type="primary"
                                    data-attr="save-dataset"
                                    onClick={submitDatasetForm}
                                    loading={isDatasetFormSubmitting}
                                >
                                    {isNewDataset ? 'Create dataset' : 'Save'}
                                </LemonButton>
                            </>
                        ) : (
                            <>
                                <LemonButton
                                    type="secondary"
                                    onClick={() => editDataset(true)}
                                    loading={false}
                                    data-attr="edit-dataset"
                                >
                                    Edit
                                </LemonButton>
                            </>
                        )
                    ) : undefined
                }
            />

            <ScenePanel>
                <ScenePanelMetaInfo>
                    <SceneTextInput
                        name="name"
                        defaultValue={datasetForm.name}
                        onSave={(value) => {
                            setDatasetFormValue('name', value)
                            submitDatasetForm()
                        }}
                        dataAttrKey={RESOURCE_TYPE}
                        isLoading={datasetLoading}
                    />
                    <SceneTextarea
                        name="description"
                        defaultValue={datasetForm.description}
                        onSave={(value) => {
                            setDatasetFormValue('description', value)
                            submitDatasetForm()
                        }}
                        dataAttrKey={RESOURCE_TYPE}
                        optional
                        isLoading={datasetLoading}
                    />
                </ScenePanelMetaInfo>

                <ScenePanelDivider />

                <ScenePanelActions>
                    <ScenePanelDivider />
                    <ButtonPrimitive
                        onClick={() => {
                            LemonDialog.open({
                                title: 'Permanently delete dataset?',
                                description: 'This action cannot be undone.',
                                primaryButton: {
                                    children: 'Delete',
                                    type: 'primary',
                                    status: 'danger',
                                    'data-attr': 'confirm-delete-dataset',
                                    onClick: deleteDataset,
                                },
                                secondaryButton: {
                                    children: 'Close',
                                    type: 'secondary',
                                },
                            })
                        }}
                        variant="danger"
                        menuItem
                        data-attr={`${RESOURCE_TYPE}-delete`}
                    >
                        <IconTrash />
                        Delete
                    </ButtonPrimitive>
                </ScenePanelActions>
            </ScenePanel>

            {displayEditForm ? <EditDatasetForm /> : <DatasetTabs />}
        </Form>
    )
}

function DatasetTabs(): JSX.Element {
    const { activeTab, dataset } = useValues(llmAnalyticsDatasetLogic)
    const { searchParams } = useValues(router)

    const tabs: LemonTab<DatasetTab>[] = [
        {
            key: DatasetTab.Items,
            label: 'Items',
            content: <DatasetItems />,
            link: combineUrl(urls.llmAnalyticsDataset(dataset.id), { ...searchParams, tab: DatasetTab.Items }).url,
        },
        {
            key: DatasetTab.Metadata,
            label: 'Metadata',
            content: <DatasetMetadata />,
            link: combineUrl(urls.llmAnalyticsDataset(dataset.id), { ...searchParams, tab: DatasetTab.Metadata }).url,
        },
    ]

    return (
        <>
            <div className="mb-4">
                <p>{dataset.description || <span className="italic">Description (optional)</span>}</p>
            </div>

            <LemonTabs activeKey={activeTab} data-attr="dataset-tabs" tabs={tabs} />
        </>
    )
}

function DatasetItems(): JSX.Element {
    const { datasetItems, datasetItemsLoading, pagination, datasetItemsCountLabel } =
        useValues(llmAnalyticsDatasetLogic)
    const { deleteDatasetItem, loadDatasetItems } = useActions(llmAnalyticsDatasetLogic)

    const columns: LemonTableColumns<DatasetItem> = [
        {
            title: 'ID',
            dataIndex: 'id',
            key: 'id',
            width: '15%',
            render: function renderID(id) {
                return <span className="font-mono text-xs">{id}</span>
            },
        },
        {
            title: 'Trace',
            dataIndex: 'ref_trace_id',
            key: 'ref_trace_id',
            width: '15%',
            render: function renderRefTraceId(_, item) {
                if (!item.ref_trace_id || !item.ref_span_id || !item.ref_trace_timestamp) {
                    return <span>–</span>
                }

                return (
                    <Link
                        to={urls.llmAnalyticsTrace(item.ref_trace_id, {
                            event: item.ref_span_id,
                            timestamp: item.ref_trace_timestamp,
                        })}
                    >
                        {item.ref_trace_id}
                    </Link>
                )
            },
        },
        {
            title: 'Input',
            dataIndex: 'input',
            key: 'input',
            width: '30%',
            render: function renderInput(input) {
                if (!input) {
                    return <span>–</span>
                }
                return (
                    <pre className="bg-bg-light px-2 py-1 rounded text-xs max-h-20 overflow-auto whitespace-pre-wrap">
                        {JSON.stringify(input, null, 2)}
                    </pre>
                )
            },
        },
        {
            title: 'Output',
            dataIndex: 'output',
            key: 'output',
            width: '30%',
            render: function renderOutput(output) {
                if (!output) {
                    return <span>–</span>
                }
                return (
                    <pre className="bg-bg-light px-2 py-1 rounded text-xs max-h-20 overflow-auto whitespace-pre-wrap">
                        {JSON.stringify(output, null, 2)}
                    </pre>
                )
            },
        },
        {
            title: 'Metadata',
            dataIndex: 'metadata',
            key: 'metadata',
            width: '25%',
            render: function renderMetadata(metadata) {
                if (!metadata) {
                    return <span>–</span>
                }
                return (
                    <pre className="bg-bg-light px-2 py-1 rounded text-xs max-h-20 overflow-auto whitespace-pre-wrap">
                        {JSON.stringify(metadata, null, 2)}
                    </pre>
                )
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
        createdAtColumn<DatasetItem>() as LemonTableColumn<DatasetItem, keyof DatasetItem | undefined>,
        updatedAtColumn<DatasetItem>() as LemonTableColumn<DatasetItem, keyof DatasetItem | undefined>,
        {
            width: 0,
            render: function renderMore(_, item) {
                return (
                    <More
                        overlay={
                            <>
                                <LemonButton
                                    to={urls.llmAnalyticsDataset(item.id)}
                                    data-attr={`dataset-item-${item.id}-dropdown-edit`}
                                    fullWidth
                                >
                                    Edit
                                </LemonButton>

                                <LemonButton
                                    status="danger"
                                    onClick={() => deleteDatasetItem(item.id)}
                                    data-attr={`dataset-item-${item.id}-dropdown-delete`}
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
        <>
            <div className="flex justify-between items-center">
                <RefreshButton
                    onClick={() => {
                        loadDatasetItems(true)
                    }}
                    isRefreshing={datasetItemsLoading}
                />
                <span className="text-muted-alt">{datasetItemsCountLabel}</span>
            </div>

            <LemonDivider className="my-4" />

            <LemonTable
                loading={datasetItemsLoading}
                columns={columns}
                dataSource={datasetItems?.results || []}
                rowKey="id"
                pagination={pagination}
                nouns={['dataset item', 'dataset items']}
                emptyState="No items in this dataset yet."
            />
        </>
    )
}

function DatasetMetadata(): JSX.Element {
    const { dataset } = useValues(llmAnalyticsDatasetLogic)

    if (!dataset || !('metadata' in dataset)) {
        return (
            <>
                <h3 className="text-lg font-semibold mb-2">Metadata</h3>
                <p className="text-muted">No metadata available.</p>
            </>
        )
    }

    return (
        <>
            <h3 className="text-lg font-semibold mb-2">Metadata</h3>
            {dataset.metadata ? (
                <pre className="bg-bg-light p-4 rounded border text-sm overflow-auto">
                    {JSON.stringify(dataset.metadata, null, 2)}
                </pre>
            ) : (
                <p className="text-muted">No metadata available.</p>
            )}
        </>
    )
}
