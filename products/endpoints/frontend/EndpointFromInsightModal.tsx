import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { LemonTable } from 'lib/lemon-ui/LemonTable'
import { LemonTextArea } from 'lib/lemon-ui/LemonTextArea'
import { Link } from 'lib/lemon-ui/Link'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { EndpointQueryNode, HogQLQuery } from '~/queries/schema/schema-general'

import { validateEndpointName } from './common'
import { endpointLogic } from './endpointLogic'
import { endpointsLogic } from './endpointsLogic'

export interface EndpointFromInsightModalProps {
    insightQuery: HogQLQuery | EndpointQueryNode
    insightShortId?: string
}

export function EndpointFromInsightModal({ insightQuery, insightShortId }: EndpointFromInsightModalProps): JSX.Element {
    const {
        createEndpoint,
        setEndpointDisplayName,
        setEndpointSlug,
        setEndpointDescription,
        closeCreateFromInsightModal,
    } = useActions(endpointLogic)
    const { endpointName, endpointDisplayName, endpointDescription, createFromInsightModalOpen, duplicateEndpoint } =
        useValues(endpointLogic)
    const { endpoints } = useValues(endpointsLogic)
    const { currentTeamId } = useValues(teamLogic)

    const endpointsFromThisInsight = insightShortId
        ? endpoints.filter((endpoint) => endpoint.derived_from_insight === insightShortId)
        : []

    const slug = endpointName?.trim() || ''
    const slugValidationError = useMemo(() => (slug ? validateEndpointName(slug) : 'Slug is required'), [slug])
    const displayNameMissing = !endpointDisplayName?.trim()

    const handleSubmit = (): void => {
        if (displayNameMissing || slugValidationError) {
            return
        }
        createEndpoint({
            display_name: endpointDisplayName!.trim(),
            name: slug,
            description: endpointDescription?.trim() || undefined,
            query: insightQuery,
            derived_from_insight: insightShortId,
        })
    }

    const handleClose = (): void => {
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
                            value={endpointDisplayName || ''}
                            onChange={setEndpointDisplayName}
                            placeholder="My endpoint"
                            autoFocus
                        />
                    </LemonField.Pure>

                    <LemonField.Pure
                        label="Slug"
                        error={slug ? validateEndpointName(slug) : undefined}
                        info={
                            <>
                                This is the slug we'll use, and it's what your endpoint URL is built from. You can
                                override it here.
                                <div className="font-mono text-xs mt-1 break-all">
                                    {`/api/projects/${currentTeamId ?? ':team_id'}/endpoints/${slug || '<slug>'}/run`}
                                </div>
                            </>
                        }
                    >
                        <LemonInput value={endpointName || ''} onChange={setEndpointSlug} placeholder="my-endpoint" />
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
                    disabledReason={
                        displayNameMissing ? 'Name is required' : slugValidationError ? slugValidationError : undefined
                    }
                >
                    Create endpoint
                </LemonButton>
            </LemonModal.Footer>
        </LemonModal>
    )
}
