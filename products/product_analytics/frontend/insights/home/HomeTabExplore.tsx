import { combineUrl } from 'kea-router'

import * as chartPng from '@posthog/brand/hoggies/png/chart'
import * as explorerPng from '@posthog/brand/hoggies/png/explorer'
import * as loopsPng from '@posthog/brand/hoggies/png/loops'
import { LemonButton, LemonCard } from '@posthog/lemon-ui'

import { pngHoggie } from 'lib/brand/hoggies'
import { urls } from 'scenes/urls'

import { InsightType } from '~/types'

const HedgehogChart = pngHoggie(chartPng)
const HedgehogExplorer = pngHoggie(explorerPng)
const HedgehogLoops = pngHoggie(loopsPng)

const analyses = [
    {
        type: InsightType.FUNNELS,
        Hedgehog: HedgehogChart,
        name: 'Funnels',
        question: 'Where do people drop off?',
        description: 'Measure conversion between the steps people take.',
        dataAttr: 'home-tab-explore-funnels',
    },
    {
        type: InsightType.PATHS,
        Hedgehog: HedgehogExplorer,
        name: 'Paths',
        question: 'What do people do next?',
        description: 'See the actions people take before or after an event.',
        dataAttr: 'home-tab-explore-paths',
    },
    {
        type: InsightType.STICKINESS,
        Hedgehog: HedgehogLoops,
        name: 'Stickiness',
        question: 'How often do people come back?',
        description: 'Measure how many days people use a feature.',
        dataAttr: 'home-tab-explore-stickiness',
    },
]

export function HomeTabExplore(): JSX.Element {
    return (
        <section aria-labelledby="home-tab-explore-heading" className="@container/home-explore min-w-0">
            <LemonCard hoverEffect={false} className="flex h-full min-w-0 flex-col overflow-hidden p-0">
                <div className="border-b border-primary px-4 py-3">
                    <span className="text-xs font-medium text-secondary">Explore</span>
                    <h2 id="home-tab-explore-heading" className="m-0 text-base font-semibold">
                        Answer your next question
                    </h2>
                </div>
                <ul className="m-0 flex flex-1 list-none flex-col p-0">
                    {analyses.map(({ type, Hedgehog, name, question, description, dataAttr }) => (
                        <li
                            key={type}
                            className="grid flex-1 grid-cols-1 items-center gap-2 border-b border-primary px-4 py-2 last:border-b-0 @min-[19rem]/home-explore:grid-cols-[4rem_minmax(0,1fr)]"
                        >
                            <Hedgehog
                                className="hidden h-16 w-16 @min-[19rem]/home-explore:block"
                                aria-hidden="true"
                                loading="eager"
                            />
                            <div className="min-w-0">
                                <div className="flex flex-wrap items-center justify-between gap-x-2 gap-y-1">
                                    <span className="text-xs font-medium text-secondary">{name}</span>
                                    <LemonButton
                                        type="tertiary"
                                        size="small"
                                        to={combineUrl(urls.insightNew({ type }), { homeGuide: type }).url}
                                        aria-label={`Learn and build a ${name.toLowerCase()} insight`}
                                        data-attr={dataAttr}
                                    >
                                        Learn and build
                                    </LemonButton>
                                </div>
                                <h3 className="m-0 text-sm font-semibold">{question}</h3>
                                <p className="m-0 text-xs text-secondary">{description}</p>
                            </div>
                        </li>
                    ))}
                </ul>
            </LemonCard>
        </section>
    )
}
