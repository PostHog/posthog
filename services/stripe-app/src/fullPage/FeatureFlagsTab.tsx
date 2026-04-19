import {
    Banner,
    Box,
    DataTable,
    Img,
    Inline,
    Link,
    Spinner,
    type DataTableColumn,
    type DataTableItem,
} from '@stripe/ui-extension-sdk/ui'
import { useEffect, useState } from 'react'

import { POSTHOG_ICON_SRC } from '../constants'
import { logger } from '../logger'
import { PostHogClient } from '../posthog/client'
import type { PostHogFeatureFlag, PostHogFlagGroup, PostHogFlagVariant } from '../posthog/types'
import { flagStatusOf, formatProperty } from './utils'

interface Props {
    client: PostHogClient | null
    projectId: string | null
}

const columns: DataTableColumn[] = [
    { key: 'key', label: 'Key', cell: { type: 'id' } },
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

const FeatureFlagsTab = ({ client, projectId }: Props): JSX.Element => {
    const [flags, setFlags] = useState<PostHogFeatureFlag[] | null>(null)
    const [error, setError] = useState<string | null>(null)

    useEffect(() => {
        if (!client || !projectId) {
            setFlags([])
            return
        }
        let cancelled = false
        client
            .fetchFeatureFlags(projectId)
            .then((data: PostHogFeatureFlag[]) => {
                if (!cancelled) {
                    setFlags(data)
                }
            })
            .catch((e: unknown) => {
                logger.error('FeatureFlagsTab failed:', e)
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
                description="A PostHog project_id isn't stored yet — reconnect to load feature flags."
            />
        )
    }
    if (error) {
        return <Banner type="critical" title="Couldn't load feature flags" description={error} />
    }
    if (!flags) {
        return (
            <Box css={{ stack: 'x', alignX: 'center', padding: 'xlarge' }}>
                <Spinner />
            </Box>
        )
    }
    if (flags.length === 0) {
        return (
            <Banner type="default" title="No feature flags yet" description="Create one in PostHog to see it here." />
        )
    }

    const posthogBase = `${client.baseUrl}/project/${projectId}`

    const idToFlagId = new Map<string, number>()
    const items: DataTableItem[] = flags.map((f: PostHogFeatureFlag) => {
        const id = `flag:${f.id}`
        idToFlagId.set(id, f.id)
        return {
            id,
            key: f.key,
            name: f.name || f.key,
            status: flagStatusOf(f),
            conditions: formatGroups(f.filters?.groups ?? []),
            variants: formatVariants(f.filters?.multivariate?.variants ?? []),
            createdAt: f.created_at,
        }
    })

    const onRowClick = (item: DataTableItem): void => {
        const flagId = idToFlagId.get(item.id)
        if (flagId) {
            window.open(`${posthogBase}/feature_flags/${flagId}`, '_blank')
        }
    }

    return (
        <Box css={{ width: 'fill', stack: 'y', rowGap: 'medium' }}>
            <DataTable columns={columns} items={items} onRowClick={onRowClick} />
            <Box css={{ paddingX: 'medium' }}>
                <Link href={`${posthogBase}/feature_flags`} target="_blank" type="secondary">
                    <Box css={{ stack: 'x', columnGap: 'xsmall', alignY: 'center' }}>
                        <Img src={POSTHOG_ICON_SRC} alt="PostHog" width="16" height="16" />
                        <Inline>See more feature flags in PostHog</Inline>
                    </Box>
                </Link>
            </Box>
        </Box>
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
