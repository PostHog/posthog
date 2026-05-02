import { Banner, Box, DataTable, Spinner, type DataTableColumn, type DataTableItem } from '@stripe/ui-extension-sdk/ui'
import { useEffect, useState } from 'react'

import { DEFAULT_TIMEFRAME, getTimeframe } from '../constants'
import { logger } from '../logger'
import type { PostHogClient } from '../posthog/client'
import ExternalLink from './components/ExternalLink'
import TimeframeSelector from './components/TimeframeSelector'

interface Props {
    client: PostHogClient | null
    projectId: string | null
}

const EventsTab = ({ client, projectId }: Props): JSX.Element => {
    const [events, setEvents] = useState<{ event: string; count: number }[] | null>(null)
    const [error, setError] = useState<string | null>(null)
    const [timeframeValue, setTimeframeValue] = useState<string>(DEFAULT_TIMEFRAME.value)
    const timeframe = getTimeframe(timeframeValue)

    useEffect(() => {
        if (!client || !projectId) {
            return
        }
        let cancelled = false
        client
            .fetchTopEvents(projectId, timeframe.days, 25)
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
    }, [client, projectId, timeframe.days])

    const timeframeHeader = (
        <Box css={{ stack: 'x', alignX: 'start', paddingBottom: 'medium' }}>
            <TimeframeSelector value={timeframeValue} onChange={setTimeframeValue} />
        </Box>
    )

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
        return (
            <>
                {timeframeHeader}
                <Banner type="critical" title="Couldn't load events" description={error} />
            </>
        )
    }
    if (!events) {
        return (
            <>
                {timeframeHeader}
                <Box css={{ stack: 'x', alignX: 'center', padding: 'xlarge' }}>
                    <Spinner />
                </Box>
            </>
        )
    }
    if (events.length === 0) {
        return (
            <>
                {timeframeHeader}
                <Banner
                    type="default"
                    title="No events yet"
                    description="Start sending events to PostHog to see them here."
                />
            </>
        )
    }

    const posthogBase = `${client.baseUrl}/project/${projectId}`

    const linkMap: Record<string, string> = {}
    const items: DataTableItem[] = events.map((e) => {
        const url = `${posthogBase}/activity/explore-events?q=${buildEventsQuery(e.event, timeframe.value)}`
        linkMap[url] = e.event
        return {
            id: `event:${e.event}`,
            event: url,
            count: e.count.toLocaleString(),
        }
    })

    const columns: DataTableColumn[] = [
        { key: 'event', label: 'Event', cell: { type: 'link', linkMap } },
        { key: 'count', label: `Count (${timeframe.label.toLowerCase()})` },
    ]

    return (
        <>
            {timeframeHeader}
            <Box css={{ width: 'fill', stack: 'y', rowGap: 'medium' }}>
                <DataTable columns={columns} items={items} />
                <Box css={{ paddingX: 'medium' }}>
                    <ExternalLink href={`${posthogBase}/activity`}>View in PostHog</ExternalLink>
                </Box>
            </Box>
        </>
    )
}

export default EventsTab

function buildEventsQuery(eventName: string, dateFrom: string): string {
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
            after: dateFrom,
            event: eventName,
        },
        propertiesViaUrl: true,
        showSavedQueries: true,
        showPersistentColumnConfigurator: true,
    }
    return encodeURIComponent(JSON.stringify(query))
}
