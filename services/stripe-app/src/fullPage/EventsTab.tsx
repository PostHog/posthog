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
import type { PostHogClient } from '../posthog/client'

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

    const items: DataTableItem[] = events.map((e) => ({
        id: `event:${e.event}`,
        event: e.event,
        count: e.count.toLocaleString(),
    }))

    const posthogBase = `${client.baseUrl}/project/${projectId}`

    return (
        <Box css={{ width: 'fill', stack: 'y', rowGap: 'medium' }}>
            <DataTable columns={columns} items={items} />
            <Box css={{ paddingX: 'medium' }}>
                <Link href={`${posthogBase}/activity`} target="_blank" type="secondary">
                    <Box css={{ stack: 'x', columnGap: 'xsmall', alignY: 'center' }}>
                        <Img src={POSTHOG_ICON_SRC} alt="PostHog" width="16" height="16" />
                        <Inline>See more events in PostHog</Inline>
                    </Box>
                </Link>
            </Box>
        </Box>
    )
}

export default EventsTab
