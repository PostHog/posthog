import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { combineUrl, router } from 'kea-router'

import { IconTrash } from '@posthog/icons'
import { LemonButton, LemonTab, LemonTabs } from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { PageHeader } from 'lib/components/PageHeader'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { ScenePanel, ScenePanelActions, ScenePanelDivider, ScenePanelMetaInfo } from '~/layout/scenes/SceneLayout'
import { SceneTextInput } from '~/lib/components/Scenes/SceneTextInput'
import { SceneTextarea } from '~/lib/components/Scenes/SceneTextarea'

import { EditDatasetForm } from './EditDatasetForm'
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
    return (
        <>
            <h3 className="text-lg font-semibold mb-2">Dataset Items</h3>
            <p className="text-muted">Items will be displayed here.</p>
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
