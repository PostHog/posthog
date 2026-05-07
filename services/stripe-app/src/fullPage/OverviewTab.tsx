import {
    Banner,
    Box,
    Divider,
    Inline,
    Link,
    OverviewPage,
    OverviewPageModule,
    Spinner,
} from '@stripe/ui-extension-sdk/ui'
import { BarChart, LineChart } from '@stripe/ui-extension-sdk/ui/next'
import { useEffect, useState } from 'react'

import { DEFAULT_TIMEFRAME, getTimeframe } from '../constants'
import { logger } from '../logger'
import { PostHogClient } from '../posthog/client'
import type { FunnelStepResult, PostHogFeatureFlag, WebOverviewItem } from '../posthog/types'
import ExternalLink from './components/ExternalLink'
import MetricRow from './components/MetricRow'
import PromoBanner, {
    PromoBannerLink,
    PromoBannerPrimaryLink,
    PromoBannerText,
    PromoBannerTitle,
} from './components/PromoBanner'
import TimeframeSelector from './components/TimeframeSelector'
import WebOverviewCards from './components/WebOverviewCards'
import { flagBadgeType, flagStatusOf, type FlagStatus } from './utils'

interface Props {
    client: PostHogClient | null
    projectId: string | null
}

interface JourneyFunnel {
    id: string
    name: string
    steps: FunnelStepResult[]
}

interface TrendPoint {
    date: string
    count: number
}

interface TopEvent {
    event: string
    count: number
}

interface State {
    eventTrends: TrendPoint[] | null
    topEvents: TopEvent[] | null
    featureFlags: PostHogFeatureFlag[] | null
    journeys: JourneyFunnel[] | null
    journeysLoading: boolean
    webOverview: WebOverviewItem[] | null
    webOverviewLoading: boolean
    loading: boolean
    error: string | null
}

const INITIAL_STATE: State = {
    eventTrends: null,
    topEvents: null,
    featureFlags: null,
    journeys: null,
    journeysLoading: true,
    webOverview: null,
    webOverviewLoading: true,
    loading: true,
    error: null,
}

async function loadJourneyFunnels(client: PostHogClient, projectId: string): Promise<JourneyFunnel[]> {
    const journeys = await client.fetchCustomerJourneys(projectId)
    if (journeys.length === 0) {
        return []
    }

    const results = await Promise.all(
        journeys.slice(0, 3).map(async (journey): Promise<JourneyFunnel | null> => {
            try {
                const insight = await client.fetchInsight(projectId, journey.insight)
                const steps = insight.result
                if (!steps || steps.length === 0) {
                    return null
                }
                return { id: journey.id, name: journey.name, steps }
            } catch (e: unknown) {
                logger.warn(`Failed to load funnel for journey "${journey.name}":`, e)
                return null
            }
        })
    )
    return results.filter((r): r is JourneyFunnel => r !== null && r.steps.length > 0)
}

const OverviewTab = ({ client, projectId }: Props): JSX.Element => {
    const [state, setState] = useState<State>(INITIAL_STATE)
    const [timeframeValue, setTimeframeValue] = useState<string>(DEFAULT_TIMEFRAME.value)
    const timeframe = getTimeframe(timeframeValue)
    const {
        eventTrends,
        topEvents,
        featureFlags,
        journeys,
        journeysLoading,
        webOverview,
        webOverviewLoading,
        loading,
        error,
    } = state

    useEffect(() => {
        let cancelled = false

        const run = async (): Promise<void> => {
            if (!client || !projectId) {
                setState({ ...INITIAL_STATE, loading: false, journeysLoading: false, webOverviewLoading: false })
                return
            }

            try {
                const [eventTrends, topEvents, featureFlags, journeys, webOverview] = await Promise.all([
                    client.fetchEventTrends(projectId, timeframe.days).catch((e: unknown) => {
                        logger.warn('Event trends query failed:', e)
                        return null
                    }),
                    client.fetchTopEvents(projectId, timeframe.days).catch((e: unknown) => {
                        logger.warn('Top events query failed:', e)
                        return null
                    }),
                    client.fetchFeatureFlags(projectId).catch((e: unknown) => {
                        logger.warn('Feature flags API failed:', e)
                        return null
                    }),
                    loadJourneyFunnels(client, projectId).catch((e: unknown) => {
                        logger.warn('Customer journeys API failed:', e)
                        return null
                    }),
                    client.fetchWebOverview(projectId, timeframe.value).catch((e: unknown) => {
                        logger.warn('Web overview API failed:', e)
                        return null
                    }),
                ])

                if (cancelled) {
                    return
                }
                setState({
                    eventTrends,
                    topEvents,
                    featureFlags,
                    journeys,
                    journeysLoading: false,
                    webOverview,
                    webOverviewLoading: false,
                    loading: false,
                    error: null,
                })
            } catch (e) {
                logger.error('OverviewTab failed to load:', e)
                if (!cancelled) {
                    setState({ ...INITIAL_STATE, loading: false, error: String(e) })
                }
            }
        }

        void run()
        return () => {
            cancelled = true
        }
    }, [client, projectId, timeframe.days, timeframe.value])

    if (error) {
        return <Banner type="critical" title="Couldn't load overview" description={error} />
    }

    if (loading) {
        return (
            <Box css={{ stack: 'x', alignX: 'center', padding: 'xlarge' }}>
                <Spinner />
            </Box>
        )
    }

    const posthogBase = client ? `${client.baseUrl}/project/${projectId}` : null

    const trendData = (eventTrends ?? []).map((p: TrendPoint) => ({
        x: new Date(p.date),
        y: p.count,
        name: 'Events',
    }))

    interface FlagRow {
        key: string
        status: FlagStatus
    }

    const activeFlags: FlagRow[] = featureFlags
        ? featureFlags.slice(0, 5).map((f: PostHogFeatureFlag) => ({
              key: f.key,
              status: flagStatusOf(f),
          }))
        : []

    const APP_ID = 'com.posthog.stripe'

    const seeInPostHog = (path: string): JSX.Element | null =>
        posthogBase ? (
            <Box css={{ paddingTop: 'small' }}>
                <ExternalLink href={`${posthogBase}${path}`}>View in PostHog</ExternalLink>
            </Box>
        ) : null

    const seeAllInTab = (tabId: string, label: string): JSX.Element => (
        <Box css={{ paddingTop: 'small' }}>
            <Link href={{ name: 'fullPage', params: { appId: APP_ID, tabId } }} type="secondary">
                <Inline>{label}</Inline>
            </Link>
        </Box>
    )

    const eventTrendsHeader = (
        <OverviewPageModule
            title="Event trends"
            subtitle={`Events tracked over the ${timeframe.label.toLowerCase()}`}
        />
    )

    const eventTrendsChart = (
        <Box css={{ height: 200 }}>
            <LineChart data={trendData} />
        </Box>
    )

    const eventTrendsFooter = seeInPostHog('/activity')

    const journeyFunnels =
        journeys && journeys.length > 0
            ? journeys.map((funnel: JourneyFunnel) => {
                  const firstCount = funnel.steps[0]?.count ?? 0
                  const lastCount = funnel.steps[funnel.steps.length - 1]?.count ?? 0
                  const conversionPct = firstCount > 0 ? ((lastCount / firstCount) * 100).toFixed(1) : '0'
                  const chartData = funnel.steps.map((s: FunnelStepResult) => ({
                      x: s.custom_name || s.name,
                      y: s.count,
                      name: funnel.name,
                  }))
                  return { funnel, conversionPct, chartData }
              })
            : null

    const journeyElements: JSX.Element[] = journeysLoading
        ? [
              <OverviewPageModule key="loading" title="Customer journeys">
                  <Box css={{ stack: 'x', alignX: 'center', padding: 'medium' }}>
                      <Spinner />
                  </Box>
              </OverviewPageModule>,
          ]
        : !journeyFunnels
          ? [
                <OverviewPageModule key="empty" title="Customer journeys">
                    <PromoBanner hero>
                        <PromoBannerTitle>Track your customers' path to conversion</PromoBannerTitle>
                        <PromoBannerText>
                            Define the key steps your users take — from sign-up to purchase — and see where they drop
                            off. View conversion rates across all users here, or drill into each journey for an
                            individual customer inside PostHog.
                        </PromoBannerText>
                        {posthogBase && (
                            <PromoBannerPrimaryLink href={`${posthogBase}/customer_analytics/journeys`}>
                                Set up your first journey
                            </PromoBannerPrimaryLink>
                        )}
                    </PromoBanner>
                </OverviewPageModule>,
            ]
          : [
                <OverviewPageModule
                    key="journeys-header"
                    title="Customer journeys"
                    subtitle="Define the key steps your users take — from sign-up to purchase — and see where they drop off. View each journey for an individual customer inside PostHog."
                />,
                ...journeyFunnels.flatMap(({ funnel, conversionPct, chartData }) => [
                    <OverviewPageModule key={funnel.name} title={funnel.name}>
                        <Inline css={{ font: 'caption', color: 'secondary' }}>
                            {conversionPct}% overall conversion
                        </Inline>
                    </OverviewPageModule>,
                    <Box key={`chart-${funnel.name}`} css={{ height: 200 }}>
                        <BarChart data={chartData} />
                    </Box>,
                    ...(posthogBase
                        ? [
                              <Box key={`link-${funnel.name}`} css={{ paddingTop: 'xsmall' }}>
                                  <ExternalLink href={`${posthogBase}/customer_analytics/journeys/${funnel.id}/edit`}>
                                      View in PostHog
                                  </ExternalLink>
                              </Box>,
                          ]
                        : []),
                ]),
                ...(posthogBase && journeyFunnels.length <= 2
                    ? [
                          <OverviewPageModule key="journeys-cta" title="">
                              <PromoBanner>
                                  <PromoBannerText>
                                      Add more journeys to track different conversion paths — onboarding, upgrade,
                                      checkout, and more.
                                  </PromoBannerText>
                                  <PromoBannerLink href={`${posthogBase}/customer_analytics/journeys`}>
                                      Create more journeys
                                  </PromoBannerLink>
                              </PromoBanner>
                          </OverviewPageModule>,
                      ]
                    : []),
            ]

    const topEventsModule = (
        <OverviewPageModule title="Top events">
            <Box css={{ stack: 'y' }}>
                {!topEvents || topEvents.length === 0 ? (
                    <Inline css={{ color: 'secondary', padding: 'small' }}>No events recorded yet.</Inline>
                ) : (
                    topEvents.map((e: TopEvent, i: number) => (
                        <Box key={e.event}>
                            {i > 0 && <Divider />}
                            <MetricRow label={e.event} value={formatCompact(e.count)} />
                        </Box>
                    ))
                )}
            </Box>
            {seeAllInTab('events', 'See all events')}
        </OverviewPageModule>
    )

    const featureFlagsModule = (
        <OverviewPageModule title="Feature flags">
            <Box css={{ stack: 'y' }}>
                {activeFlags.length === 0 && (
                    <Inline css={{ color: 'secondary', padding: 'small' }}>No feature flags yet.</Inline>
                )}
                {activeFlags.map((flag: FlagRow, i: number) => {
                    const statusLabel =
                        flag.status === 'enabled' ? 'Enabled' : flag.status === 'beta' ? 'Beta' : 'Disabled'
                    return (
                        <Box key={flag.key}>
                            {i > 0 && <Divider />}
                            <MetricRow
                                label={flag.key}
                                value={statusLabel}
                                badgeLabel={statusLabel}
                                badgeType={flagBadgeType(flag.status)}
                            />
                        </Box>
                    )
                })}
            </Box>
            {seeAllInTab('feature-flags', 'See all feature flags')}
        </OverviewPageModule>
    )

    const webOverviewModule =
        client && projectId ? (
            <OverviewPageModule title="Web analytics">
                <Box css={{ stack: 'y', rowGap: 'medium' }}>
                    <Box css={{ stack: 'x', alignX: 'start' }}>
                        <TimeframeSelector value={timeframeValue} onChange={setTimeframeValue} />
                    </Box>
                    <WebOverviewCards items={webOverview} loading={webOverviewLoading} />
                </Box>
                {seeInPostHog('/web')}
            </OverviewPageModule>
        ) : null

    return (
        <OverviewPage
            primaryColumn={
                <>
                    {webOverviewModule}
                    {eventTrendsHeader}
                    {eventTrendsChart}
                    {eventTrendsFooter}
                    {journeyElements}
                </>
            }
            secondaryColumn={
                <>
                    {topEventsModule}
                    {featureFlagsModule}
                </>
            }
        />
    )
}

export default OverviewTab

function formatCompact(n: number): string {
    if (n >= 1_000_000) {
        return `${(n / 1_000_000).toFixed(1)}M`
    }
    if (n >= 1_000) {
        return `${(n / 1_000).toFixed(1)}K`
    }
    return n.toLocaleString()
}
