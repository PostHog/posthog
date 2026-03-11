import { useActions, useValues } from 'kea'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { LemonTable } from 'lib/lemon-ui/LemonTable'
import { LemonTextArea } from 'lib/lemon-ui/LemonTextArea'
import { Link } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { HogQLQuery, InsightQueryNode } from '~/queries/schema/schema-general'

import { endpointLogic } from './endpointLogic'
import { endpointsLogic } from './endpointsLogic'

export interface EndpointFromInsightModalProps {
    tabId: string
    insightQuery: HogQLQuery | InsightQueryNode
    insightShortId?: string
}

export function EndpointFromInsightModal({
    tabId,
    insightQuery,
    insightShortId,
}: EndpointFromInsightModalProps): JSX.Element {
    const { createEndpoint, setEndpointName, setEndpointDescription, closeCreateFromInsightModal } = useActions(
        endpointLogic({ tabId })
    )
    const { endpointName, endpointDescription, createFromInsightModalOpen, duplicateEndpoint } = useValues(
        endpointLogic({ tabId })
    )
    const { endpoints } = useValues(endpointsLogic({ tabId }))

    const endpointsFromThisInsight = insightShortId
        ? endpoints.filter((endpoint) => endpoint.derived_from_insight === insightShortId)
        : []

    const handleSubmit = (): void => {
        if (!endpointName?.trim()) {
            return
        }
        createEndpoint({
            name: endpointName.trim(),
            description: endpointDescription?.trim() || undefined,
            query: insightQuery,
            derived_from_insight: insightShortId,
        })
    }

    const handleClose = (): void => {
        setEndpointName('')
        setEndpointDescription('')
        closeCreateFromInsightModal()
    }

    return (
        <LemonModal isOpen={createFromInsightModalOpen} onClose={handleClose} width={600}>
            <LemonModal.Header>
                <h3>{duplicateEndpoint ? 'Duplicate insight-based endpoint' : 'Create endpoint from insight'}</h3>
            </LemonModal.Header>

            <LemonModal.Content>
                <div className="space-y-4">
                    {duplicateEndpoint && (
                        <div className="text-sm text-secondary">
                            Duplicating <strong>{duplicateEndpoint.name}</strong>
                        </div>
                    )}
                    {endpointsFromThisInsight.length > 0 && (
                        <div>
                            <div className="text-muted mb-2">Endpoints already created from this insight:</div>
                            <LemonTable
                                dataSource={endpointsFromThisInsight}
                                columns={[
                                    {
                                        title: 'Name',
                                        key: 'name',
                                        dataIndex: 'name',
                                        render: (_, record) => (
                                            <Link to={urls.endpoint(record.name)}>{record.name}</Link>
                                        ),
                                    },
                                    {
                                        title: 'Description',
                                        key: 'description',
                                        dataIndex: 'description',
                                        render: (_, record) =>
                                            record.description || <span className="text-muted">—</span>,
                                    },
                                ]}
                                size="small"
                                embedded
                            />
                        </div>
                    )}

                    <LemonField.Pure label="Name">
                        <LemonInput
                            value={endpointName || ''}
                            onChange={setEndpointName}
                            placeholder="Enter endpoint name"
                            autoFocus
                        />
                    </LemonField.Pure>

                    <LemonField.Pure label="Description">
                        <LemonTextArea
                            value={endpointDescription || ''}
                            onChange={setEndpointDescription}
                            placeholder="Enter endpoint description (optional)"
                            rows={3}
                        />
                    </LemonField.Pure>
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
                    disabledReason={!endpointName?.trim() ? 'Endpoint name is required' : undefined}
                >
                    Create endpoint
                </LemonButton>
            </LemonModal.Footer>
        </LemonModal>
    )
}
