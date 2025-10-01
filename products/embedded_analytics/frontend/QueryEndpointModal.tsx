import { useActions, useValues } from 'kea'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { LemonTextArea } from 'lib/lemon-ui/LemonTextArea'

import { HogQLQuery, InsightQueryNode } from '~/queries/schema/schema-general'

import { queryEndpointLogic } from './queryEndpointLogic'

export interface QueryEndpointModalProps {
    isOpen: boolean
    closeModal: () => void
    tabId: string
    insightQuery: HogQLQuery | InsightQueryNode
}

export function QueryEndpointModal({ isOpen, closeModal, tabId, insightQuery }: QueryEndpointModalProps): JSX.Element {
    const { createQueryEndpoint, setQueryEndpointName, setQueryEndpointDescription } = useActions(
        queryEndpointLogic({ tabId })
    )
    const { queryEndpointName, queryEndpointDescription } = useValues(queryEndpointLogic({ tabId }))

    const handleSubmit = (): void => {
        if (!queryEndpointName?.trim()) {
            return
        }

        createQueryEndpoint({
            name: queryEndpointName.trim(),
            description: queryEndpointDescription?.trim() || undefined,
            query: insightQuery,
        })

        closeModal()
    }

    const handleClose = (): void => {
        setQueryEndpointName('')
        setQueryEndpointDescription('')
        closeModal()
    }

    return (
        <LemonModal isOpen={isOpen} onClose={handleClose} width={600}>
            <LemonModal.Header>
                <h3>Create query endpoint</h3>
            </LemonModal.Header>

            <LemonModal.Content>
                <div className="space-y-4">
                    <div>
                        <LemonField.Pure label="Name">
                            <LemonInput
                                value={queryEndpointName || ''}
                                onChange={setQueryEndpointName}
                                placeholder="Enter query endpoint name"
                                autoFocus
                            />
                        </LemonField.Pure>
                    </div>

                    <div>
                        <LemonField.Pure label="Description">
                            <LemonTextArea
                                value={queryEndpointDescription || ''}
                                onChange={setQueryEndpointDescription}
                                placeholder="Enter query endpoint description (optional)"
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
                    disabledReason={!queryEndpointName ? 'Query endpoint name is required' : undefined}
                >
                    Create query endpoint
                </LemonButton>
            </LemonModal.Footer>
        </LemonModal>
    )
}
