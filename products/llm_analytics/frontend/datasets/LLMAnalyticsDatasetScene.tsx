import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconTrash } from '@posthog/icons'
import { LemonButton, LemonInput, LemonTextArea } from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { PageHeader } from 'lib/components/PageHeader'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { JSONEditorInput } from 'scenes/feature-flags/JSONEditorInput'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { ScenePanel, ScenePanelActions, ScenePanelDivider, ScenePanelMetaInfo } from '~/layout/scenes/SceneLayout'
import { SceneTextInput } from '~/lib/components/Scenes/SceneTextInput'
import { SceneTextarea } from '~/lib/components/Scenes/SceneTextarea'

import { DatasetLogicProps, llmAnalyticsDatasetLogic } from './llmAnalyticsDatasetLogic'

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
        dataset,
        datasetLoading,
        isDatasetFormSubmitting,
        isEditingDataset,
        datasetMissing,
        isNewDataset,
        datasetForm,
    } = useValues(llmAnalyticsDatasetLogic)
    const { submitDatasetForm, loadDataset, editDataset, deleteDataset, setDatasetFormValue } =
        useActions(llmAnalyticsDatasetLogic)

    const canShowSaveButtons = isNewDataset || isEditingDataset

    if (datasetMissing) {
        return <NotFound object="dataset" />
    }

    if (datasetLoading) {
        return <LemonSkeleton active />
    }

    return (
        <div>
            <PageHeader
                buttons={
                    !datasetLoading ? (
                        canShowSaveButtons ? (
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
                        }}
                        dataAttrKey={RESOURCE_TYPE}
                    />
                    <SceneTextarea
                        name="description"
                        defaultValue={datasetForm.description}
                        onSave={(value) => {
                            setDatasetFormValue('description', value)
                        }}
                        dataAttrKey={RESOURCE_TYPE}
                        optional
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

            <div className={clsx(isEditingDataset || isNewDataset ? 'max-w-160' : null)}>
                <div className="flex flex-col gap-4 flex-2 min-w-[15rem]">
                    {isNewDataset && (
                        <div className="mb-4">
                            <label className="block text-sm font-medium mb-2">Name</label>
                            <LemonInput
                                data-attr="dataset-name"
                                value={datasetForm.name}
                                onChange={(value) => setDatasetFormValue('name', value)}
                                placeholder="Enter dataset name"
                            />
                        </div>
                    )}

                    <div className="flex flex-wrap gap-4 items-start">
                        <div className="flex-1 min-w-[20rem]">
                            {isEditingDataset || isNewDataset ? (
                                <div className="mb-4">
                                    <label className="block text-sm font-medium mb-2">Description (optional)</label>
                                    <LemonTextArea
                                        className="ph-ignore-input"
                                        placeholder="Describe what this dataset contains"
                                        value={datasetForm.description}
                                        onChange={(value) => setDatasetFormValue('description', value)}
                                    />
                                </div>
                            ) : (
                                <div className="mb-2">
                                    <b>Description</b>
                                    <div>
                                        {dataset?.description ? (
                                            dataset.description
                                        ) : (
                                            <span className="text-secondary">No description</span>
                                        )}
                                    </div>
                                </div>
                            )}
                        </div>
                    </div>

                    <div className="flex flex-col gap-4">
                        <div>
                            <b>Metadata</b>
                            {isEditingDataset || isNewDataset ? (
                                <div className="mt-2">
                                    <JSONEditorInput
                                        value={datasetForm.metadata}
                                        onChange={(code) => {
                                            setDatasetFormValue('metadata', code)
                                        }}
                                        placeholder="Enter JSON metadata"
                                    />
                                </div>
                            ) : (
                                <div className="mt-2">
                                    <JSONEditorInput
                                        value={JSON.stringify(dataset?.metadata || {}, null, 2)}
                                        readOnly={true}
                                    />
                                </div>
                            )}
                        </div>
                    </div>
                </div>
            </div>
        </div>
    )
}
