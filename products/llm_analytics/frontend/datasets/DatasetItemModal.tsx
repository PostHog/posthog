import { Form } from 'kea-forms'
import React from 'react'

import { LemonButton, LemonModal } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonModalContent, LemonModalFooter, LemonModalHeader } from 'lib/lemon-ui/LemonModal/LemonModal'

import { JSONEditor } from '../components/JSONEditor'
import { DatasetItemModalLogicProps, datasetItemModalLogic } from './datasetItemModalLogic'

export interface DatasetItemModalProps extends DatasetItemModalLogicProps {
    isOpen: boolean
    onClose: () => void
}

export const DatasetItemModal = React.memo(function DatasetItemModal({
    isOpen,
    onClose,
    datasetItem,
    traceMetadata,
}: DatasetItemModalProps): JSX.Element {
    const logicProps: DatasetItemModalLogicProps = {
        datasetItem,
        traceMetadata,
    }

    return (
        <LemonModal isOpen={isOpen} onClose={onClose} maxWidth="40rem" simple className="w-full">
            <Form logic={datasetItemModalLogic} props={logicProps} formKey="datasetItemForm">
                <LemonModalHeader>
                    <h3>{datasetItem ? 'Edit dataset item' : 'New dataset item'}</h3>
                </LemonModalHeader>

                <LemonModalContent className="gap-4 flex flex-col">
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
                    <LemonButton type="primary" htmlType="submit">
                        Save
                    </LemonButton>
                </LemonModalFooter>
            </Form>
        </LemonModal>
    )
})
