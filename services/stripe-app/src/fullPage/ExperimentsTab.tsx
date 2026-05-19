import {
    Banner,
    Box,
    DataTable,
    Inline,
    Spinner,
    TextField,
    type DataTableColumn,
    type DataTableItem,
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

const ExperimentsTab = ({ client, projectId }: Props): JSX.Element => {
    const [experiments, setExperiments] = useState<PostHogExperiment[]>([])
    const [loading, setLoading] = useState<boolean>(true)
    const [error, setError] = useState<string | null>(null)
    const [filter, setFilter] = useState<string>('')

    useEffect(() => {
        if (!client || !projectId) {
            setExperiments([])
            setLoading(false)
            return
        }
        let cancelled = false
        setExperiments([])
        setLoading(true)
        setError(null)
        client
            .fetchAllExperiments(projectId, (page) => {
                if (!cancelled) {
                    setExperiments((prev) => [...prev, ...page])
                }
            })
            .then(() => {
                if (!cancelled) {
                    setLoading(false)
                }
            })
            .catch((e: unknown) => {
                logger.error('ExperimentsTab failed:', e)
                if (!cancelled) {
                    setError(String(e))
                    setLoading(false)
                }
            })
        return () => {
            cancelled = true
        }
    }, [client, projectId])

    const filterHeader = (
        <Box css={{ stack: 'x', alignX: 'start', paddingBottom: 'medium' }}>
            <TextField
                label="Search"
                type="search"
                size="small"
                placeholder="Filter by name or feature flag"
                value={filter}
                onChange={(e: React.ChangeEvent<HTMLInputElement>) => setFilter(e.target.value)}
            />
        </Box>
    )

    if (!client || !projectId) {
        return (
            <Banner
                type="caution"
                title="Project not linked"
                description="A PostHog project_id isn't stored yet — reconnect to load experiments."
            />
        )
    }
    if (error && experiments.length === 0) {
        return <Banner type="critical" title="Couldn't load experiments" description={error} />
    }
    if (loading && experiments.length === 0) {
        return (
            <Box css={{ stack: 'x', alignX: 'center', padding: 'xlarge' }}>
                <Spinner />
            </Box>
        )
    }
    if (!loading && experiments.length === 0) {
        return <Banner type="default" title="No experiments yet" description="Create one in PostHog to see it here." />
    }

    const posthogBase = `${client.baseUrl}/project/${projectId}`
    const needle = filter.trim().toLowerCase()
    const visibleExperiments = needle
        ? experiments.filter(
              (e: PostHogExperiment) =>
                  e.name.toLowerCase().includes(needle) || (e.feature_flag_key ?? '').toLowerCase().includes(needle)
          )
        : experiments

    const linkMap: Record<string, string> = {}
    const items: DataTableItem[] = visibleExperiments.map((e: PostHogExperiment) => {
        const url = `${posthogBase}/experiments/${e.id}`
        linkMap[url] = e.name
        return {
            id: `experiment:${e.id}`,
            name: url,
            status: experimentStatusOf(e),
            featureFlagKey: e.feature_flag_key,
            startDate: e.start_date ?? e.created_at,
        }
    })

    const columns: DataTableColumn[] = [
        { key: 'name', label: 'Name', cell: { type: 'link', linkMap } },
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

    return (
        <>
            {filterHeader}
            <Box css={{ width: 'fill', stack: 'y', rowGap: 'medium' }}>
                <DataTable columns={columns} items={items} emptyMessage="No matching experiments" />
                {loading && (
                    <Box
                        css={{
                            stack: 'x',
                            alignX: 'center',
                            alignY: 'center',
                            columnGap: 'xsmall',
                            paddingX: 'medium',
                        }}
                    >
                        <Spinner />
                        <Inline css={{ font: 'caption', color: 'secondary' }}>Loading more experiments…</Inline>
                    </Box>
                )}
                <Box css={{ paddingX: 'medium' }}>
                    <ExternalLink href={`${posthogBase}/experiments`}>View in PostHog</ExternalLink>
                </Box>
            </Box>
        </>
    )
}

export default ExperimentsTab
