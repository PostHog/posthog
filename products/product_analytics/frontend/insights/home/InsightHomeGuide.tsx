import { useValues } from 'kea'
import { router } from 'kea-router'

import * as chartPng from '@posthog/brand/hoggies/png/chart'
import * as explorerPng from '@posthog/brand/hoggies/png/explorer'
import * as loopsPng from '@posthog/brand/hoggies/png/loops'
import { IconX } from '@posthog/icons'
import { LemonButton, LemonCard } from '@posthog/lemon-ui'

import { pngHoggie } from 'lib/brand/hoggies'
import { Link } from 'lib/lemon-ui/Link'

import { Node, NodeKind } from '~/queries/schema/schema-general'
import { isInsightVizNode } from '~/queries/utils'
import { InsightType } from '~/types'

type GuidedInsightType = InsightType.FUNNELS | InsightType.PATHS | InsightType.STICKINESS

const GUIDE_ARTWORK = {
    [InsightType.FUNNELS]: pngHoggie(chartPng),
    [InsightType.PATHS]: pngHoggie(explorerPng),
    [InsightType.STICKINESS]: pngHoggie(loopsPng),
}

const GUIDE_QUERY_KIND: Record<GuidedInsightType, NodeKind> = {
    [InsightType.FUNNELS]: NodeKind.FunnelsQuery,
    [InsightType.PATHS]: NodeKind.PathsQuery,
    [InsightType.STICKINESS]: NodeKind.StickinessQuery,
}

function isGuidedInsightType(value: unknown): value is GuidedInsightType {
    return value === InsightType.FUNNELS || value === InsightType.PATHS || value === InsightType.STICKINESS
}

interface GuideContent {
    title: string
    explanation: string
    example: string
    steps: [string, string, string]
    resources: { label: string; url: string }[]
}

const GUIDE_CONTENT: Record<GuidedInsightType, GuideContent> = {
    [InsightType.FUNNELS]: {
        title: 'Build a funnel',
        explanation: 'See how many people complete a sequence of actions and where they leave it.',
        example: 'For example: view a product, start checkout, then complete a purchase.',
        steps: [
            'Choose the event that starts the journey.',
            'Add the next events in the order people should complete them.',
            'Use the results to find the step with the largest drop-off.',
        ],
        resources: [{ label: 'Funnel analysis guide', url: 'https://posthog.com/docs/product-analytics/funnels' }],
    },
    [InsightType.PATHS]: {
        title: 'Explore paths',
        explanation: 'See the routes people take through pages, screens, and events.',
        example: 'For example: start at a pricing page and follow the next actions people take.',
        steps: [
            'Choose the events or pages to include.',
            'Set a start or end point when you have a specific journey in mind.',
            'Follow the branches to find common routes and unexpected detours.',
        ],
        resources: [{ label: 'User paths guide', url: 'https://posthog.com/docs/product-analytics/paths' }],
    },
    [InsightType.STICKINESS]: {
        title: 'Measure stickiness',
        explanation: 'See how often people repeat an action within a period.',
        example: 'For example: how many people viewed a page on three or more days this week?',
        steps: [
            'Choose the event that represents meaningful activity.',
            'Pick the date range and interval you want to study.',
            'Read the frequency chart to see how many days people used the feature.',
        ],
        resources: [
            { label: 'Stickiness overview', url: 'https://posthog.com/docs/product-analytics/insights#stickiness' },
            {
                label: 'App and feature stickiness examples',
                url: 'https://posthog.com/product-engineers/mobile-app-metrics-kpis#6-app-and-feature-stickiness',
            },
        ],
    },
}

export function InsightHomeGuide({ query }: { query: Node | null }): JSX.Element | null {
    const { location, searchParams, hashParams } = useValues(router)
    const requestedType = searchParams.homeGuide

    if (!isGuidedInsightType(requestedType) || !isInsightVizNode(query)) {
        return null
    }

    if (query.source.kind !== GUIDE_QUERY_KIND[requestedType]) {
        return null
    }

    const guide = GUIDE_CONTENT[requestedType]
    const Hedgehog = GUIDE_ARTWORK[requestedType]

    const dismiss = (): void => {
        const nextSearchParams = { ...searchParams }
        delete nextSearchParams.homeGuide
        router.actions.replace(location.pathname, nextSearchParams, hashParams)
    }

    return (
        <LemonCard hoverEffect={false} className="@container/insight-home-guide mb-1 overflow-hidden p-0">
            <LemonButton
                type="tertiary"
                size="xsmall"
                icon={<IconX />}
                onClick={dismiss}
                aria-label="close"
                tooltip="Dismiss guide"
                data-attr="insight-home-guide-dismiss"
                className="absolute right-2 top-2"
            />
            <div className="flex items-center gap-4 px-4 py-4 pr-10 @min-[32rem]/insight-home-guide:px-5 @min-[32rem]/insight-home-guide:pr-10">
                <Hedgehog
                    className="hidden h-20 w-20 shrink-0 @min-[32rem]/insight-home-guide:block @min-[48rem]/insight-home-guide:h-24 @min-[48rem]/insight-home-guide:w-24"
                    aria-hidden="true"
                    loading="eager"
                />
                <div className="min-w-0">
                    <h2 className="m-0 mb-1 text-lg font-semibold">{guide.title}</h2>
                    <p className="m-0 text-sm">{guide.explanation}</p>
                    <p className="m-0 mt-1 text-sm text-secondary">{guide.example}</p>
                </div>
            </div>
            <div className="border-t border-primary bg-fill-secondary px-4 py-3 @min-[32rem]/insight-home-guide:px-5">
                <h3 className="m-0 mb-3 text-xs font-semibold text-secondary">Get started</h3>
                <ol className="m-0 flex list-none flex-col gap-3 p-0">
                    {guide.steps.map((step, index) => (
                        <li key={step} className="flex items-start gap-3 text-sm">
                            <span
                                className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full border border-primary bg-surface-primary text-xs font-semibold text-secondary"
                                aria-hidden="true"
                            >
                                {index + 1}
                            </span>
                            <span>{step}</span>
                        </li>
                    ))}
                </ol>
                <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
                    <span className="text-secondary">Read more:</span>
                    {guide.resources.map(({ label, url }) => (
                        <Link key={url} to={url} target="_blank" targetBlankIcon>
                            {label}
                        </Link>
                    ))}
                </div>
            </div>
        </LemonCard>
    )
}
