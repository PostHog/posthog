import { useActions, useValues } from 'kea'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { LemonSelect } from 'lib/lemon-ui/LemonSelect'
import { LemonTextArea } from 'lib/lemon-ui/LemonTextArea'

import { HogQLQuery, InsightQueryNode } from '~/queries/schema/schema-general'

import { endpointLogic } from './endpointLogic'
import { endpointsLogic } from './endpointsLogic'

export interface EndpointModalProps {
    isOpen: boolean
    closeModal: () => void
    tabId: string
    insightQuery: HogQLQuery | InsightQueryNode
}

export function EndpointModal({ isOpen, closeModal, tabId, insightQuery }: EndpointModalProps): JSX.Element {
    const {
        createEndpoint,
        updateEndpoint,
        setEndpointName,
        setEndpointDescription,
        setIsUpdateMode,
        setSelectedEndpointName,
    } = useActions(endpointLogic({ tabId }))
    const { endpointName, endpointDescription, isUpdateMode, selectedEndpointName } = useValues(
        endpointLogic({ tabId })
    )
    const { endpoints } = useValues(endpointsLogic({ tabId }))

    const handleSubmit = (): void => {
        if (isUpdateMode) {
            if (!selectedEndpointName) {
                return
            }
            updateEndpoint(selectedEndpointName, {
                description: endpointDescription?.trim() || undefined,
                query: insightQuery,
            })
        } else {
            if (!endpointName?.trim()) {
                return
            }
            createEndpoint({
                name: endpointName.trim(),
                description: endpointDescription?.trim() || undefined,
                query: insightQuery,
            })
        }

        closeModal()
    }

    const handleClose = (): void => {
        setEndpointName('')
        setEndpointDescription('')
        setIsUpdateMode(false)
        setSelectedEndpointName(null)
        closeModal()
    }

    return (
        <LemonModal isOpen={isOpen} onClose={handleClose} width={600}>
            <LemonModal.Header>
                <h3>{isUpdateMode ? 'Update endpoint' : 'Create endpoint'}</h3>
            </LemonModal.Header>

            <LemonModal.Content>
                <div className="space-y-4">
                    <div>
                        <LemonField.Pure label="Mode">
                            <LemonSelect
                                value={isUpdateMode ? 'update' : 'create'}
                                onChange={(value) => {
                                    setIsUpdateMode(value === 'update')
                                    if (value === 'update') {
                                        setEndpointName('')
                                    } else {
                                        setSelectedEndpointName(null)
                                    }
                                }}
                                options={[
                                    { value: 'create', label: 'Create new endpoint' },
                                    { value: 'update', label: 'Update existing endpoint' },
                                ]}
                            />
                        </LemonField.Pure>
                    </div>

                    {isUpdateMode ? (
                        <div>
                            <LemonField.Pure label="Select endpoint">
                                <LemonSelect
                                    value={selectedEndpointName}
                                    onChange={(value) => setSelectedEndpointName(value)}
                                    options={endpoints.map((endpoint) => ({
                                        value: endpoint.name,
                                        label: endpoint.name,
                                    }))}
                                    placeholder="Select an endpoint to update"
                                />
                            </LemonField.Pure>
                        </div>
                    ) : (
                        <div>
                            <LemonField.Pure label="Name">
                                <LemonInput
                                    value={endpointName || ''}
                                    onChange={setEndpointName}
                                    placeholder="Enter endpoint name"
                                    autoFocus
                                />
                            </LemonField.Pure>
                        </div>
                    )}

                    <div>
                        <LemonField.Pure label="Description">
                            <LemonTextArea
                                value={endpointDescription || ''}
                                onChange={setEndpointDescription}
                                placeholder="Enter endpoint description (optional)"
                                rows={3}
                            />
                        </LemonField.Pure>
                    </div>
                </div>
            </LemonModal.Content>

            <LemonModal.Footer>
                <div className="flex-1" />
                <LemonButton type="secondary" onClick={handleClose}>
                    Cancel
                </LemonButton>
                <LemonButton
                    type="primary"
                    onClick={handleSubmit}
                    disabledReason={
                        isUpdateMode
                            ? !selectedEndpointName
                                ? 'Select an endpoint to update'
                                : undefined
                            : !endpointName
                              ? 'Endpoint name is required'
                              : undefined
                    }
                >
                    {isUpdateMode ? 'Update endpoint' : 'Create endpoint'}
                </LemonButton>
            </LemonModal.Footer>
        </LemonModal>
    )
}
