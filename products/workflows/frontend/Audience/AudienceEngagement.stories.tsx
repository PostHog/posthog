import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import type { Meta, StoryObj } from '@storybook/react'
import clsx from 'clsx'
import { useValues } from 'kea'
import { router } from 'kea-router'
import { useEffect } from 'react'

import { FEATURE_FLAGS } from 'lib/constants'
import { Dayjs, dayjs } from 'lib/dayjs'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import type { MockResolverInfo } from '~/mocks/utils'
import { EventsNode } from '~/queries/schema/schema-general'

import { engagementEventsLogic } from '../engagementEventsLogic'
import { AudienceScene } from './AudienceScene'

const STORY_DATE = '2026-10-01T09:00:00Z'

const DAILY_SENDS = [
    420, 380, 0, 0, 510, 460, 445, 470, 395, 0, 0, 530, 480, 455, 490, 410, 0, 0, 560, 500, 470, 505, 430, 0, 0, 575,
    520, 490, 515, 440,
]
const SHARE_OF_SENT: Record<string, number> = {
    $workflows_email_sent: 1,
    $workflows_email_delivered: 0.97,
    $workflows_email_opened: 0.41,
    $workflows_email_link_clicked: 0.08,
}
const WEEKLY_COUNTS: Record<string, number[]> = {
    $workflows_email_unsubscribed: [14, 11, 17, 9, 12],
    $workflows_email_bounced: [22, 18, 25, 16, 19],
    $workflows_email_blocked: [2, 1, 3, 0, 1],
}

const APP_METRICS_TOTALS = [
    [12840, 'email_sent'],
    [12455, 'email_delivered'],
    [5264, 'email_opened'],
    [1027, 'email_link_clicked'],
    [100, 'email_bounced'],
    [7, 'email_blocked'],
]

function bucketDates(count: number, unit: 'day' | 'week'): Dayjs[] {
    return Array.from({ length: count }, (_, index) =>
        dayjs(STORY_DATE)
            .startOf(unit)
            .subtract(count - 1 - index, unit)
    )
}

function trendSeries(series: EventsNode, index: number, data: number[], unit: 'day' | 'week'): Record<string, unknown> {
    const dates = bucketDates(data.length, unit)
    return {
        action: { id: series.event, type: 'events', order: index, name: series.event, custom_name: series.name },
        label: series.name,
        count: data.reduce((sum, value) => sum + value, 0),
        data,
        labels: dates.map((date) => date.format('D-MMM-YYYY')),
        days: dates.map((date) => date.format('YYYY-MM-DD')),
    }
}

function trendsResult(series: EventsNode[], interval: 'day' | 'week'): Record<string, unknown>[] {
    return series.map((node, index) =>
        interval === 'day'
            ? trendSeries(
                  node,
                  index,
                  DAILY_SENDS.map((sent) => Math.round(sent * SHARE_OF_SENT[node.event ?? ''])),
                  'day'
              )
            : trendSeries(node, index, WEEKLY_COUNTS[node.event ?? ''], 'week')
    )
}

function funnelResult(series: EventsNode[]): Record<string, unknown>[] {
    const recipients = 4200
    return series.map((node, index) => ({
        action_id: node.event,
        name: node.event,
        custom_name: node.name,
        order: index,
        type: 'events',
        count: Math.round(recipients * SHARE_OF_SENT[node.event ?? '']),
        people: [],
        average_conversion_time: index === 0 ? null : 3600 * index,
        median_conversion_time: index === 0 ? null : 1800 * index,
    }))
}

async function queryResponse({ request }: MockResolverInfo): Promise<Record<string, unknown>> {
    const { query } = (await request.json()) as { query: Record<string, any> }
    switch (query.kind) {
        case 'TrendsQuery':
            return { results: trendsResult(query.series, query.interval) }
        case 'FunnelsQuery':
            return { results: funnelResult(query.series) }
        case 'HogQLQuery':
            return { results: APP_METRICS_TOTALS }
        default:
            return { results: [] }
    }
}

const meta: Meta<typeof AudienceScene> = {
    title: 'Scenes-App/Workflows/Audience/Engagement',
    component: AudienceScene,
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: STORY_DATE,
        featureFlags: [FEATURE_FLAGS.WORKFLOWS_AUDIENCE],
    },
    decorators: [
        mswDecorator({
            post: {
                '/api/environments/:team_id/query/:kind/': queryResponse,
            },
        }),
    ],
}
export default meta

type Story = StoryObj<typeof AudienceScene>

type SceneWidth = 'full' | 'narrow'

const SCENE_WIDTH_CLASSES: Record<SceneWidth, string> = {
    full: 'w-full',
    // 520px is the scene width left by a 1280px window with the nav sidebar and the side panel open.
    narrow: 'w-[520px]',
}

function engagementStory(engagementEventsCaptured: boolean, sceneWidth: SceneWidth): Story {
    return {
        render: function Render() {
            const { engagementEventsCaptured: captured } = useValues(engagementEventsLogic)
            useEffect(() => {
                router.actions.push(urls.audience('engagement'))
            }, [])
            // Storybook decorators restore the default team after the story mounts, so keep reapplying it.
            useEffect(() => {
                if (captured !== engagementEventsCaptured) {
                    teamLogic.actions.loadCurrentTeamSuccess({
                        ...MOCK_DEFAULT_TEAM,
                        workflows_config: { capture_workflows_engagement_events: engagementEventsCaptured },
                    })
                }
            }, [captured])
            return (
                <div className={clsx('@container/main-content', SCENE_WIDTH_CLASSES[sceneWidth])}>
                    <AudienceScene />
                </div>
            )
        },
    }
}

export const EngagementEventsOn: Story = engagementStory(true, 'full')
export const EngagementEventsOnNarrow: Story = engagementStory(true, 'narrow')
export const EngagementEventsOff: Story = engagementStory(false, 'full')
export const EngagementEventsOffNarrow: Story = engagementStory(false, 'narrow')
