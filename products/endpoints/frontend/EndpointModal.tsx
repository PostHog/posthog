import { useActions, useValues } from 'kea'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { LemonTextArea } from 'lib/lemon-ui/LemonTextArea'

import { HogQLQuery, InsightQueryNode } from '~/queries/schema/schema-general'

import { endpointLogic } from './endpointLogic'

export interface EndpointModalProps {
    isOpen: boolean
    closeModal: () => void
    tabId: string
    insightQuery: HogQLQuery | InsightQueryNode
}

export function EndpointModal({ isOpen, closeModal, tabId, insightQuery }: EndpointModalProps): JSX.Element {
    const { createEndpoint, setEndpointName, setEndpointDescription } = useActions(endpointLogic({ tabId }))
    const { endpointName, endpointDescription } = useValues(endpointLogic({ tabId }))

    const handleSubmit = (): void => {
        if (!endpointName?.trim()) {
            return
        }

        createEndpoint({
            name: endpointName.trim(),
            description: endpointDescription?.trim() || undefined,
            query: insightQuery,
        })

        closeModal()
    }

    const handleClose = (): void => {
        setEndpointName('')
        setEndpointDescription('')
        closeModal()
    }

    return (
        <LemonModal isOpen={isOpen} onClose={handleClose} width={600}>
            <LemonModal.Header>
                <h3>Create endpoint</h3>
            </LemonModal.Header>

            <LemonModal.Content>
                <div className="space-y-4">
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

                    <div>
                        <LemonField.Pure label="Query">
                            <div className="rounded p-1 bg-muted">
                                <CodeSnippet language={Language.JSON} wrap>
                                    {JSON.stringify(insightQuery, null, 2)}
                                </CodeSnippet>
                            </div>
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
                    disabledReason={!endpointName ? 'Endpoint name is required' : undefined}
                >
                    Create endpoint
                </LemonButton>
            </LemonModal.Footer>
        </LemonModal>
    )
}
