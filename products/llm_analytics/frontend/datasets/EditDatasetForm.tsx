import { useActions, useValues } from 'kea'

import { LemonInput, LemonTextArea } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import { JSONEditor } from '../components/JSONEditor'
import { llmAnalyticsDatasetLogic } from './llmAnalyticsDatasetLogic'

export function EditDatasetForm(): JSX.Element {
    const { datasetForm } = useValues(llmAnalyticsDatasetLogic)
    const { setDatasetFormValue } = useActions(llmAnalyticsDatasetLogic)

    return (
        <div className="max-w-160">
            <div className="flex flex-col gap-4 flex-2">
                <LemonField name="name" label="Name" htmlFor="dataset-name">
                    <LemonInput
                        data-attr="dataset-name"
                        value={datasetForm.name}
                        onChange={(value) => setDatasetFormValue('name', value)}
                        placeholder="Enter dataset name"
                        data-testid="edit-dataset-name-input"
                    />
                </LemonField>

                <LemonField name="description" label="Description" showOptional>
                    <LemonTextArea
                        className="ph-ignore-input"
                        placeholder="Describe what this dataset contains"
                        value={datasetForm.description}
                        onChange={(value) => setDatasetFormValue('description', value)}
                        data-testid="edit-dataset-description-input"
                    />
                </LemonField>

                <LemonField
                    name="metadata"
                    label="Metadata"
                    htmlFor="dataset-metadata"
                    showOptional
                    help="Additional key-value pairs to store with the dataset"
                >
                    <JSONEditor
                        value={datasetForm.metadata ?? undefined}
                        onChange={(code) => {
                            setDatasetFormValue('metadata', code)
                        }}
                    />
                </LemonField>
            </div>
        </div>
    )
}
