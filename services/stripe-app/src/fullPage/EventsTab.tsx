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
import type { PostHogClient } from '../posthog/client'
import ExternalLink from './components/ExternalLink'

const columns: DataTableColumn[] = [
    { key: 'event', label: 'Event' },
    { key: 'count', label: 'Count (8w)' },
]

interface Props {
    client: PostHogClient | null
    projectId: string | null
}

const EventsTab = ({ client, projectId }: Props): JSX.Element => {
    const [events, setEvents] = useState<{ event: string; count: number }[] | null>(null)
    const [error, setError] = useState<string | null>(null)

    useEffect(() => {
        if (!client || !projectId) {
            return
        }
        let cancelled = false
        client
            .fetchTopEvents(projectId, 25)
            .then((data) => {
                if (!cancelled) {
                    setEvents(data)
                }
            })
            .catch((e: unknown) => {
                logger.error('EventsTab failed:', e)
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
                description="A PostHog project_id isn't stored yet — reconnect to load events."
            />
        )
    }
    if (error) {
        return <Banner type="critical" title="Couldn't load events" description={error} />
    }
    if (!events) {
        return (
            <Box css={{ stack: 'x', alignX: 'center', padding: 'xlarge' }}>
                <Spinner />
            </Box>
        )
    }
    if (events.length === 0) {
        return (
            <Banner
                type="default"
                title="No events yet"
                description="Start sending events to PostHog to see them here."
            />
        )
    }

    const eventNameById = new Map<string, string>()
    const items: DataTableItem[] = events.map((e) => {
        const id = `event:${e.event}`
        eventNameById.set(id, e.event)
        return {
            id,
            event: e.event,
            count: e.count.toLocaleString(),
        }
    })

    const posthogBase = `${client.baseUrl}/project/${projectId}`

    const rowActions: DataTableRowAction[] = [
        {
            id: 'open-in-posthog',
            label: 'Open in activity',
            onPress: (item: DataTableItem) => {
                const eventName = eventNameById.get(item.id)
                if (eventName) {
                    window.open(`${posthogBase}/activity/explore-events?q=${buildEventsQuery(eventName)}`, '_blank')
                }
            },
        },
    ]

    return (
        <Box css={{ width: 'fill', stack: 'y', rowGap: 'medium' }}>
            <DataTable columns={columns} items={items} rowActions={rowActions} />
            <Box css={{ paddingX: 'medium' }}>
                <ExternalLink href={`${posthogBase}/activity`}>View in PostHog</ExternalLink>
            </Box>
        </Box>
    )
}

export default EventsTab

function buildEventsQuery(eventName: string): string {
    const query = {
        kind: 'DataTableNode',
        full: true,
        source: {
            kind: 'EventsQuery',
            select: [
                '*',
                'event',
                'person_display_name -- Person',
                'coalesce(properties.$current_url, properties.$screen_name) -- Url / Screen',
                'properties.$lib',
                'timestamp',
            ],
            orderBy: ['timestamp DESC'],
            after: '-30d',
            event: eventName,
        },
        propertiesViaUrl: true,
        showSavedQueries: true,
        showPersistentColumnConfigurator: true,
    }
    return encodeURIComponent(JSON.stringify(query))
}
