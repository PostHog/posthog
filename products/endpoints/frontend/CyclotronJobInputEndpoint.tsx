import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { LemonButton, LemonDivider, LemonSelect } from '@posthog/lemon-ui'

import api from 'lib/api'
import type { CustomInputRendererProps } from 'lib/components/CyclotronJob/customInputRenderers'

import { HogQLQueryEditor } from '~/queries/nodes/HogQLQuery/HogQLQueryEditor'
import { NodeKind } from '~/queries/schema/schema-general'

import { endpointsLogic } from './endpointsLogic'

export default function CyclotronJobInputEndpoint({ value, onChange }: CustomInputRendererProps): JSX.Element {
    const { allEndpoints, allEndpointsLoading } = useValues(endpointsLogic({ tabId: 'workflow-query' }))
    const { loadEndpoints } = useActions(endpointsLogic({ tabId: 'workflow-query' }))
    const [query, setQuery] = useState(
        'SELECT event, count() AS count FROM events GROUP BY event ORDER BY count DESC LIMIT 10'
    )
    const [isSaving, setIsSaving] = useState(false)

    const endpointOptions = allEndpoints.map((endpoint) => ({
        value: endpoint.name,
        label: endpoint.name,
    }))

    const handleSaveAsEndpoint = async (): Promise<void> => {
        setIsSaving(true)
        try {
            const newEndpoint = await api.endpoint.create({
                name: `workflow_query_${Date.now()}`,
                query: { kind: NodeKind.HogQLQuery, query },
            })
            onChange(newEndpoint.name)
            loadEndpoints()
        } finally {
            setIsSaving(false)
        }
    }

    return (
        <div className="space-y-2">
            <LemonSelect
                fullWidth
                value={value || undefined}
                onChange={(val) => onChange(val)}
                options={endpointOptions}
                placeholder="Select an endpoint..."
                loading={allEndpointsLoading}
                allowClear
            />

            <LemonDivider label="or compose a new query" />

            <HogQLQueryEditor
                query={{ kind: NodeKind.HogQLQuery, query }}
                onChange={(newQuery) => setQuery(newQuery)}
                embedded
                editorFooter={(hasErrors, error) =>
                    hasErrors && error ? <div className="text-danger text-sm p-1">{error}</div> : <></>
                }
            />

            <LemonButton
                type="secondary"
                onClick={handleSaveAsEndpoint}
                loading={isSaving}
                disabledReason={!query ? 'Write a query first' : undefined}
                fullWidth
                center
            >
                Save as new endpoint
            </LemonButton>
        </div>
    )
}
