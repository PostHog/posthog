import { dayjs } from 'lib/dayjs'
import { SessionTimelineItem } from './base'
import { EventsQuery, NodeKind } from '~/queries/schema/schema-general'
import api from 'lib/api'

export type TimelineItemLoaderOptions = {
    initialOffset: number
    query: (start: number, end: number) => Promise<SessionTimelineItem[]>
}

export class TimelineItemLoader {
    boundaries: [number, number]
    items: Record<string, SessionTimelineItem>

    constructor(
        timestamp: string,
        private options: TimelineItemLoaderOptions
    ) {
        const timestampMs = dayjs(timestamp).valueOf()
        this.boundaries = [timestampMs - options.initialOffset, timestampMs + options.initialOffset]
        this.items = {}
    }

    addItems(items: SessionTimelineItem[]): void {
        this.items = items.reduce((acc, item) => {
            acc[item.id] = item
            return acc
        }, this.items)
    }

    getItems(): SessionTimelineItem[] {
        return Object.values(this.items).sort((a, b) => (dayjs(a.timestamp).isBefore(b.timestamp) ? -1 : 1))
    }

    setItems(items: SessionTimelineItem[]): void {
        this.items = {}
        this.addItems(items)
    }

    async load(): Promise<SessionTimelineItem[]> {
        const [start, end] = this.boundaries
        const newItems = await this.options.query(start, end)
        this.setItems(newItems)
        return this.getItems()
    }

    async loadBefore(): Promise<SessionTimelineItem[]> {
        const [start, end] = this.boundaries
        const queryBoundaries = [start - this.options.initialOffset, start]
        const newItems = await this.options.query(queryBoundaries[0], queryBoundaries[1])
        this.boundaries = [queryBoundaries[0], end]
        this.addItems(newItems)
        return this.getItems()
    }

    async loadAfter(): Promise<SessionTimelineItem[]> {
        const [start, end] = this.boundaries
        const queryBoundaries = [end, end + this.options.initialOffset]
        const newItems = await this.options.query(queryBoundaries[0], queryBoundaries[1])
        this.boundaries = [start, queryBoundaries[1]]
        this.addItems(newItems)
        return this.getItems()
    }
}

export class EventsItemLoader extends TimelineItemLoader {
    constructor(timestamp: string, sessionId: string) {
        super(timestamp, {
            initialOffset: 60 * 1000, // 1 minute
            query: async (start: number, end: number): Promise<SessionTimelineItem[]> => {
                const startDayJs = dayjs(start)
                const endDayJs = dayjs(end)
                const query: EventsQuery = {
                    kind: NodeKind.EventsQuery,
                    select: ['uuid', 'event', 'timestamp', 'properties'],
                    where: [`equals($session_id, '${sessionId}')`],
                    event: null,
                    before: endDayJs.toISOString(),
                    after: startDayJs.toISOString(),
                    orderBy: ['timestamp'],
                    limit: 10000,
                }
                const response = await api.query(query)
                const results = response.results
                return results.map((result: any) => ({
                    id: result[0],
                    type: 'event',
                    timestamp: result[2],
                    payload: {
                        event: result[1],
                        properties: JSON.parse(result[3]),
                    },
                }))
            },
        })
    }
}
