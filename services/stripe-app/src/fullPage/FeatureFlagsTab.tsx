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
import type { PostHogFeatureFlag, PostHogFlagGroup, PostHogFlagVariant } from '../posthog/types'
import ExternalLink from './components/ExternalLink'
import { flagStatusOf, formatProperty } from './utils'

interface Props {
    client: PostHogClient | null
    projectId: string | null
}

const FeatureFlagsTab = ({ client, projectId }: Props): JSX.Element => {
    const [flags, setFlags] = useState<PostHogFeatureFlag[]>([])
    const [loading, setLoading] = useState<boolean>(true)
    const [error, setError] = useState<string | null>(null)
    const [filter, setFilter] = useState<string>('')

    useEffect(() => {
        if (!client || !projectId) {
            setFlags([])
            setLoading(false)
            return
        }
        let cancelled = false
        setFlags([])
        setLoading(true)
        setError(null)
        client
            .fetchAllFeatureFlags(projectId, (page) => {
                if (!cancelled) {
                    setFlags((prev) => [...prev, ...page])
                }
            })
            .then(() => {
                if (!cancelled) {
                    setLoading(false)
                }
            })
            .catch((e: unknown) => {
                logger.error('FeatureFlagsTab failed:', e)
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
                placeholder="Filter by key or name"
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
                description="A PostHog project_id isn't stored yet — reconnect to load feature flags."
            />
        )
    }
    if (error && flags.length === 0) {
        return <Banner type="critical" title="Couldn't load feature flags" description={error} />
    }
    if (loading && flags.length === 0) {
        return (
            <Box css={{ stack: 'x', alignX: 'center', padding: 'xlarge' }}>
                <Spinner />
            </Box>
        )
    }
    if (!loading && flags.length === 0) {
        return (
            <Banner type="default" title="No feature flags yet" description="Create one in PostHog to see it here." />
        )
    }

    const posthogBase = `${client.baseUrl}/project/${projectId}`
    const needle = filter.trim().toLowerCase()
    const visibleFlags = needle
        ? flags.filter(
              (f: PostHogFeatureFlag) =>
                  f.key.toLowerCase().includes(needle) || (f.name ?? '').toLowerCase().includes(needle)
          )
        : flags

    const linkMap: Record<string, string> = {}
    const items: DataTableItem[] = visibleFlags.map((f: PostHogFeatureFlag) => {
        const url = `${posthogBase}/feature_flags/${f.id}`
        linkMap[url] = f.key
        return {
            id: `flag:${f.id}`,
            key: url,
            name: f.name || f.key,
            status: flagStatusOf(f),
            conditions: formatGroups(f.filters?.groups ?? []),
            variants: formatVariants(f.filters?.multivariate?.variants ?? []),
            createdAt: f.created_at,
        }
    })

    const columns: DataTableColumn[] = [
        { key: 'key', label: 'Key', cell: { type: 'link', linkMap } },
        { key: 'name', label: 'Name' },
        {
            key: 'status',
            label: 'Status',
            cell: {
                type: 'status',
                statusMap: { enabled: 'positive', beta: 'info', disabled: 'neutral' },
            },
        },
        { key: 'conditions', label: 'Release conditions' },
        { key: 'variants', label: 'Variants' },
        { key: 'createdAt', label: 'Created', cell: { type: 'date' } },
    ]

    return (
        <>
            {filterHeader}
            <Box css={{ width: 'fill', stack: 'y', rowGap: 'medium' }}>
                <DataTable columns={columns} items={items} emptyMessage="No matching feature flags" />
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
                        <Inline css={{ font: 'caption', color: 'secondary' }}>Loading more feature flags…</Inline>
                    </Box>
                )}
                <Box css={{ paddingX: 'medium' }}>
                    <ExternalLink href={`${posthogBase}/feature_flags`}>View in PostHog</ExternalLink>
                </Box>
            </Box>
        </>
    )
}

export default FeatureFlagsTab

function formatGroups(groups: PostHogFlagGroup[]): string {
    if (groups.length === 0) {
        return '—'
    }
    return groups
        .map((g: PostHogFlagGroup, i: number) => {
            const rollout = g.rollout_percentage ?? 100
            const props = g.properties ?? []
            const variantSuffix = g.variant ? ` → ${g.variant}` : ''
            const header = `Set ${i + 1}: ${rollout}%${variantSuffix}`
            if (props.length === 0) {
                return `${header} · Everyone`
            }
            return [header, ...props.map((p) => `  • ${formatProperty(p)}`)].join('\n')
        })
        .join('\n')
}

function formatVariants(variants: PostHogFlagVariant[]): string {
    if (variants.length === 0) {
        return '—'
    }
    return variants.map((v: PostHogFlagVariant) => `${v.key} · ${v.rollout_percentage}%`).join('\n')
}
