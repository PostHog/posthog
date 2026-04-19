import {
    Banner,
    Box,
    DataTable,
    Spinner,
    type DataTableColumn,
    type DataTableItem,
    type DataTableRowAction,
} from '@stripe/ui-extension-sdk/ui'
import { useEffect, useState } from 'react'

import { logger } from '../logger'
import { PostHogClient } from '../posthog/client'
import type { PostHogExperiment } from '../posthog/types'
import ExternalLink from './components/ExternalLink'
import { experimentStatusOf } from './utils'

interface Props {
    client: PostHogClient | null
    projectId: string | null
}

const columns: DataTableColumn[] = [
    { key: 'name', label: 'Name' },
    {
        key: 'status',
        label: 'Status',
        cell: {
            type: 'status',
            statusMap: { running: 'info', complete: 'positive', draft: 'neutral' },
        },
    },
    { key: 'featureFlagKey', label: 'Feature flag', cell: { type: 'id' } },
    { key: 'startDate', label: 'Started', cell: { type: 'date' } },
]

const ExperimentsTab = ({ client, projectId }: Props): JSX.Element => {
    const [experiments, setExperiments] = useState<PostHogExperiment[] | null>(null)
    const [error, setError] = useState<string | null>(null)

    useEffect(() => {
        if (!client || !projectId) {
            setExperiments([])
            return
        }
        let cancelled = false
        client
            .fetchExperiments(projectId)
            .then((data: PostHogExperiment[]) => {
                if (!cancelled) {
                    setExperiments(data)
                }
            })
            .catch((e: unknown) => {
                logger.error('ExperimentsTab failed:', e)
                if (!cancelled) {
                    setError(String(e))
                }
            })
        return () => {
            cancelled = true
        }
    }, [client, projectId])

    if (!client || !projectId) {
        return (
            <Banner
                type="caution"
                title="Project not linked"
                description="A PostHog project_id isn't stored yet — reconnect to load experiments."
            />
        )
    }
    if (error) {
        return <Banner type="critical" title="Couldn't load experiments" description={error} />
    }
    if (!experiments) {
        return (
            <Box css={{ stack: 'x', alignX: 'center', padding: 'xlarge' }}>
                <Spinner />
            </Box>
        )
    }
    if (experiments.length === 0) {
        return <Banner type="default" title="No experiments yet" description="Create one in PostHog to see it here." />
    }

    const posthogBase = `${client.baseUrl}/project/${projectId}`

    const idToExperimentId = new Map<string, number>()
    const items: DataTableItem[] = experiments.map((e: PostHogExperiment) => {
        const id = `experiment:${e.id}`
        idToExperimentId.set(id, e.id)
        return {
            id,
            name: e.name,
            status: experimentStatusOf(e),
            featureFlagKey: e.feature_flag_key,
            startDate: e.start_date ?? e.created_at,
        }
    })

    const rowActions: DataTableRowAction[] = [
        {
            id: 'open-in-posthog',
            label: 'Open in PostHog',
            onPress: (item: DataTableItem) => {
                const experimentId = idToExperimentId.get(item.id)
                if (experimentId) {
                    window.open(`${posthogBase}/experiments/${experimentId}`, '_blank')
                }
            },
        },
    ]

    return (
        <Box css={{ width: 'fill', stack: 'y', rowGap: 'medium' }}>
            <DataTable columns={columns} items={items} rowActions={rowActions} />
            <Box css={{ paddingX: 'medium' }}>
                <ExternalLink href={`${posthogBase}/experiments`}>View in PostHog</ExternalLink>
            </Box>
        </Box>
    )
}

export default ExperimentsTab
