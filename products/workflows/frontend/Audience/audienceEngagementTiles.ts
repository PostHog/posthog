import { EventsNode, FunnelsQuery, InsightVizNode, NodeKind, TrendsQuery } from '~/queries/schema/schema-general'
import {
    BaseMathType,
    ChartDisplayType,
    DashboardLayoutSize,
    DashboardTemplateEditorType,
    DashboardTemplateStoredInsightTile,
    FunnelConversionWindowTimeUnit,
    FunnelVizType,
    HogQLMathType,
    TileLayout,
} from '~/types'

const LAST_30_DAYS_IN_DAYS = 30
const LAST_30_DAYS = { date_from: `-${LAST_30_DAYS_IN_DAYS}d` }

function engagementSeries(event: string, name: string): EventsNode {
    return { kind: NodeKind.EventsNode, event, name, math: BaseMathType.TotalCount }
}

const SENT = engagementSeries('$workflows_email_sent', 'Sent')
const DELIVERED = engagementSeries('$workflows_email_delivered', 'Delivered')
const OPENED = engagementSeries('$workflows_email_opened', 'Opened')
const CLICKED = engagementSeries('$workflows_email_link_clicked', 'Clicked')
// One preferences submit records an event per topic, so count the addresses that unsubscribed.
const UNSUBSCRIBED: EventsNode = {
    ...engagementSeries('$workflows_email_unsubscribed', 'Unsubscribed'),
    math: HogQLMathType.HogQL,
    math_hogql: 'count(DISTINCT properties.$email)',
}
const BOUNCED = engagementSeries('$workflows_email_bounced', 'Bounced')
// The provider reports a spam complaint as a block, so `$workflows_email_blocked` is the spam report.
const MARKED_AS_SPAM = engagementSeries('$workflows_email_blocked', 'Marked as spam')

const SENT_PER_DAY: InsightVizNode<TrendsQuery> = {
    kind: NodeKind.InsightVizNode,
    source: {
        kind: NodeKind.TrendsQuery,
        interval: 'day',
        dateRange: LAST_30_DAYS,
        series: [SENT, DELIVERED, OPENED, CLICKED],
        trendsFilter: { display: ChartDisplayType.ActionsLineGraph, showLegend: true },
    },
}

const UNSUBSCRIBES_BOUNCES_AND_SPAM_PER_WEEK: InsightVizNode<TrendsQuery> = {
    kind: NodeKind.InsightVizNode,
    source: {
        kind: NodeKind.TrendsQuery,
        interval: 'week',
        dateRange: LAST_30_DAYS,
        series: [UNSUBSCRIBED, BOUNCED, MARKED_AS_SPAM],
        trendsFilter: { display: ChartDisplayType.ActionsBar, showLegend: true },
    },
}

const SENT_TO_CLICKED_FUNNEL: InsightVizNode<FunnelsQuery> = {
    kind: NodeKind.InsightVizNode,
    source: {
        kind: NodeKind.FunnelsQuery,
        dateRange: LAST_30_DAYS,
        series: [SENT, DELIVERED, OPENED, CLICKED],
        funnelsFilter: {
            funnelVizType: FunnelVizType.Steps,
            // A recipient is an address, not a person, so each step counts the addresses that reached it.
            funnelAggregateByHogQL: 'properties.$email_to',
            funnelWindowInterval: LAST_30_DAYS_IN_DAYS,
            funnelWindowIntervalUnit: FunnelConversionWindowTimeUnit.Day,
        },
    },
}

// pinned: sent as the `tile` property of `audience insight opened`
export type AudienceEngagementTileKey = 'sent-per-day' | 'unsubscribes-bounces-and-spam' | 'funnel'

export interface AudienceEngagementTile {
    key: AudienceEngagementTileKey
    name: string
    description: string
    emptyStateHeading: string
    query: InsightVizNode
    fullWidth: boolean
}

export const AUDIENCE_ENGAGEMENT_TILES: AudienceEngagementTile[] = [
    {
        key: 'sent-per-day',
        name: 'Sent, delivered, opened and clicked',
        description: 'Emails per day from every workflow and broadcast.',
        emptyStateHeading: 'No emails sent in the last 30 days',
        query: SENT_PER_DAY,
        fullWidth: false,
    },
    {
        key: 'unsubscribes-bounces-and-spam',
        name: 'Unsubscribed, bounced and marked as spam',
        description:
            'Per week. The first and last bars cover part of a week. A rise here is the earliest sign of a sender reputation problem.',
        emptyStateHeading: 'Nothing unsubscribed, bounced or marked as spam in the last 30 days',
        query: UNSUBSCRIBES_BOUNCES_AND_SPAM_PER_WEEK,
        fullWidth: false,
    },
    {
        key: 'funnel',
        name: 'Sent to clicked',
        description: 'How many recipients reach each step, counted by the address the email went to.',
        emptyStateHeading: 'No emails sent in the last 30 days',
        query: SENT_TO_CLICKED_FUNNEL,
        fullWidth: true,
    },
]

export type AudienceEngagementDashboardTemplate = Required<
    Pick<DashboardTemplateEditorType, 'template_name' | 'dashboard_description' | 'dashboard_filters' | 'tags'>
> & { tiles: DashboardTemplateStoredInsightTile[] }

const TILE_HEIGHT = 5
const TILE_MIN_SIZE = { h: TILE_HEIGHT, minH: TILE_HEIGHT, minW: 3 }

function tileLayouts(tile: AudienceEngagementTile, index: number): Record<DashboardLayoutSize, TileLayout> {
    return {
        sm: tile.fullWidth
            ? { x: 0, y: TILE_HEIGHT, w: 12, ...TILE_MIN_SIZE }
            : { x: index * 6, y: 0, w: 6, ...TILE_MIN_SIZE },
        xs: { x: 0, y: index * TILE_HEIGHT, w: 1, ...TILE_MIN_SIZE },
    }
}

export function audienceEngagementDashboardTemplate(): AudienceEngagementDashboardTemplate {
    return {
        template_name: 'Email engagement',
        dashboard_description: 'How recipients engage with email from workflows and broadcasts.',
        dashboard_filters: LAST_30_DAYS,
        tags: ['email'],
        tiles: AUDIENCE_ENGAGEMENT_TILES.map((tile, index) => ({
            type: 'INSIGHT',
            name: tile.name,
            description: tile.description,
            query: tile.query,
            layouts: tileLayouts(tile, index),
        })),
    }
}
