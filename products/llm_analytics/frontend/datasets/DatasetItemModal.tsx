import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import React from 'react'

import { LemonButton, LemonModal } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonModalContent, LemonModalFooter, LemonModalHeader } from 'lib/lemon-ui/LemonModal/LemonModal'

import { DatasetItem } from '~/types'

import { JSONEditor } from '../components/JSONEditor'
import { DatasetItemModalLogicProps, TraceMetadata, datasetItemModalLogic } from './datasetItemModalLogic'

export interface DatasetItemModalProps {
    isOpen: boolean
    onClose: (action?: 'create' | 'update') => void
    datasetId: string
    datasetItem?: DatasetItem | null
    traceMetadata?: TraceMetadata
}

export const DatasetItemModal = React.memo(function DatasetItemModal({
    isOpen,
    onClose,
    datasetItem,
    traceMetadata,
    datasetId,
}: DatasetItemModalProps): JSX.Element {
    const logicProps: DatasetItemModalLogicProps = {
        datasetId,
        datasetItem,
        traceMetadata,
        closeModal: onClose,
        isModalOpen: isOpen,
    }
    const { isDatasetItemFormSubmitting } = useValues(datasetItemModalLogic(logicProps))
    const { submitDatasetItemForm, setShouldCloseModal } = useActions(datasetItemModalLogic(logicProps))

    return (
        <LemonModal isOpen={isOpen} onClose={() => onClose()} maxWidth="40rem" simple className="w-full">
            <Form
                logic={datasetItemModalLogic}
                props={logicProps}
                formKey="datasetItemForm"
                enableFormOnSubmit
                className="flex flex-col overflow-y-hidden"
            >
                <LemonModalHeader>
                    <h3>{datasetItem ? 'Edit dataset item' : 'New dataset item'}</h3>
                </LemonModalHeader>

                <LemonModalContent className="flex flex-col gap-4">
                    <LemonField name="input" label="Input">
                        <JSONEditor />
                    </LemonField>
                    <LemonField name="output" label="Output">
                        <JSONEditor />
                    </LemonField>
                    <LemonField name="metadata" label="Metadata">
                        <JSONEditor />
                    </LemonField>
                </LemonModalContent>

                <LemonModalFooter>
                    {!datasetItem && (
                        <LemonButton
                            type="secondary"
                            loading={isDatasetItemFormSubmitting}
                            htmlType="submit"
                            onClick={(e) => {
                                e.preventDefault()
                                setShouldCloseModal(false)
                                submitDatasetItemForm()
                            }}
                        >
                            Save and add another
                        </LemonButton>
                    )}
                    <LemonButton type="primary" htmlType="submit" loading={isDatasetItemFormSubmitting}>
                        Save
                    </LemonButton>
                </LemonModalFooter>
            </Form>
        </LemonModal>
    )
})
