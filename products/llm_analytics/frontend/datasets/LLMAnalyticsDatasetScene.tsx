import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { combineUrl, router } from 'kea-router'
import { useEffect } from 'react'

import { IconPlusSmall, IconTrash } from '@posthog/icons'
import { LemonButton, LemonDivider, LemonTab, LemonTabs, Link, ProfilePicture } from '@posthog/lemon-ui'

import { HighlightedJSONViewer } from 'lib/components/HighlightedJSONViewer'
import { NotFound } from 'lib/components/NotFound'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { createdAtColumn, updatedAtColumn } from 'lib/lemon-ui/LemonTable/columnUtils'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import {
    ScenePanel,
    ScenePanelActionsSection,
    ScenePanelDivider,
    ScenePanelInfoSection,
} from '~/layout/scenes/SceneLayout'
import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { SceneTextInput } from '~/lib/components/Scenes/SceneTextInput'
import { SceneTextarea } from '~/lib/components/Scenes/SceneTextarea'
import { LemonTable, LemonTableColumn, LemonTableColumns } from '~/lib/lemon-ui/LemonTable'
import { Dataset, DatasetItem } from '~/types'

import { truncateValue } from '../utils'
import { DatasetItemModal } from './DatasetItemModal'
import { EditDatasetForm } from './EditDatasetForm'
import { JSONColumn } from './JSONColumn'
import { RefreshButton } from './RefreshButton'
import { DatasetLogicProps, DatasetTab, isDataset, llmAnalyticsDatasetLogic } from './llmAnalyticsDatasetLogic'

const RESOURCE_TYPE = 'dataset'

export const scene: SceneExport<DatasetLogicProps> = {
    component: LLMAnalyticsDatasetScene,
    logic: llmAnalyticsDatasetLogic,
    paramsToProps: ({ params: { id } }) => ({
        datasetId: id && id !== 'new' ? id : 'new',
    }),
}

export function LLMAnalyticsDatasetScene(): JSX.Element {
    const {
        shouldDisplaySkeleton,
        datasetLoading,
        isDatasetFormSubmitting,
        isEditingDataset,
        isDatasetMissing,
        isNewDataset,
        datasetForm,
        dataset,
        isDeletingDataset,
    } = useValues(llmAnalyticsDatasetLogic)
    const {
        submitDatasetForm,
        loadDataset,
        editDataset,
        deleteDataset,
        setDatasetFormValue,
        triggerDatasetItemModal,
        onUnmount,
    } = useActions(llmAnalyticsDatasetLogic)

    const displayEditForm = isNewDataset || isEditingDataset

    // TRICKY: Scene logic is not unmounted. Workaround.
    useEffect(() => {
        return () => onUnmount()
    }, [onUnmount])

    if (isDatasetMissing) {
        return <NotFound object="dataset" />
    }

    if (shouldDisplaySkeleton) {
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
            <SceneContent>
                <SceneTitleSection
                    name={datasetForm.name}
                    resourceType={{ type: 'llm_analytics' }}
                    isLoading={datasetLoading}
                    actions={
                        <>
                            {!shouldDisplaySkeleton ? (
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
                                            size="small"
                                        >
                                            Cancel
                                        </LemonButton>
                                        <LemonButton
                                            type="primary"
                                            data-attr="save-dataset"
                                            onClick={submitDatasetForm}
                                            loading={isDatasetFormSubmitting}
                                            size="small"
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
                                            size="small"
                                        >
                                            Edit
                                        </LemonButton>
                                        <LemonButton
                                            type="primary"
                                            onClick={() => triggerDatasetItemModal(true)}
                                            data-attr="add-dataset-item"
                                            icon={<IconPlusSmall />}
                                            size="small"
                                        >
                                            Add item
                                        </LemonButton>
                                    </>
                                )
                            ) : undefined}
                        </>
                    }
                />

                {isDataset(dataset) && (
                    <ScenePanel>
                        <ScenePanelInfoSection>
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
                        </ScenePanelInfoSection>
                        <ScenePanelDivider />
                        <ScenePanelActionsSection>
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
                                disabledReasons={{
                                    'Dataset is loading': datasetLoading,
                                    'Dataset is being deleted': isDeletingDataset,
                                }}
                            >
                                <IconTrash />
                                Delete
                            </ButtonPrimitive>
                        </ScenePanelActionsSection>
                    </ScenePanel>
                )}

                {displayEditForm ? <EditDatasetForm /> : isDataset(dataset) ? <DatasetTabs dataset={dataset} /> : null}
            </SceneContent>
        </Form>
    )
}

function DatasetTabs({ dataset }: { dataset: Dataset }): JSX.Element {
    const { activeTab, isDatasetItemModalOpen, selectedDatasetItem } = useValues(llmAnalyticsDatasetLogic)
    const { closeModalAndRefetchDatasetItems } = useActions(llmAnalyticsDatasetLogic)
    const { searchParams } = useValues(router)

    const tabs: LemonTab<DatasetTab>[] = [
        {
            key: DatasetTab.Items,
            label: 'Items',
            content: <DatasetItems dataset={dataset} />,
            link: combineUrl(urls.llmAnalyticsDataset(dataset.id), { ...searchParams, tab: DatasetTab.Items }).url,
        },
        {
            key: DatasetTab.Metadata,
            label: 'Metadata',
            content: <DatasetMetadata dataset={dataset} />,
            link: combineUrl(urls.llmAnalyticsDataset(dataset.id), { ...searchParams, tab: DatasetTab.Metadata }).url,
        },
    ]

    return (
        <>
            <div>
                <p className="m-0">{dataset.description || <span className="italic">Description (optional)</span>}</p>
            </div>

            <LemonTabs activeKey={activeTab} data-attr="dataset-tabs" tabs={tabs} />

            <DatasetItemModal
                isOpen={isDatasetItemModalOpen}
                onClose={closeModalAndRefetchDatasetItems}
                partialDatasetItem={selectedDatasetItem}
                datasetId={dataset.id}
                displayBulkCreationButton
            />
        </>
    )
}

function DatasetItems({ dataset }: { dataset: Dataset }): JSX.Element {
    const { datasetItems, datasetItemsLoading, pagination } = useValues(llmAnalyticsDatasetLogic)
    const { deleteDatasetItem, loadDatasetItems } = useActions(llmAnalyticsDatasetLogic)
    const { searchParams } = useValues(router)

    const columns: LemonTableColumns<DatasetItem> = [
        {
            title: 'ID',
            dataIndex: 'id',
            key: 'id',
            width: '10%',
            render: function renderID(_, item) {
                return (
                    <Link to={urls.llmAnalyticsDataset(dataset.id, { ...searchParams, item: item.id })}>
                        {truncateValue(item.id)}
                    </Link>
                )
            },
        },
        {
            title: 'Trace',
            dataIndex: 'ref_trace_id',
            key: 'ref_trace_id',
            width: '10%',
            render: function renderRefTraceId(_, item) {
                if (!item.ref_trace_id || !item.ref_source_id || !item.ref_timestamp) {
                    return <span>—</span>
                }

                return (
                    <Link
                        to={urls.llmAnalyticsTrace(item.ref_trace_id, {
                            event: item.ref_source_id,
                            timestamp: item.ref_timestamp,
                        })}
                    >
                        {truncateValue(item.ref_trace_id)}
                    </Link>
                )
            },
        },
        {
            title: 'Input',
            dataIndex: 'input',
            key: 'input',
            width: '30%',
            render: function renderInput(_, item) {
                return <JSONColumn>{item.input}</JSONColumn>
            },
        },
        {
            title: 'Output',
            dataIndex: 'output',
            key: 'output',
            width: '30%',
            render: function renderOutput(_, item) {
                return <JSONColumn>{item.output}</JSONColumn>
            },
        },
        {
            title: 'Metadata',
            dataIndex: 'metadata',
            key: 'metadata',
            width: '25%',
            render: function renderMetadata(_, item) {
                return <JSONColumn>{item.metadata}</JSONColumn>
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
                                    to={urls.llmAnalyticsDataset(dataset.id, { ...searchParams, item: item.id })}
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

function DatasetMetadata({ dataset }: { dataset: Dataset }): JSX.Element {
    return (
        <div className="flex flex-col gap-4 max-w-160">
            <div className="flex flex-col gap-2">
                <h3 className="text-sm font-semibold m-0">Metadata</h3>
                {dataset.metadata ? (
                    <div className="bg-bg-light p-4 rounded border overflow-x-auto">
                        <HighlightedJSONViewer src={dataset.metadata} />
                    </div>
                ) : (
                    <p className="text-muted m-0">No metadata available.</p>
                )}
            </div>
        </div>
    )
}
