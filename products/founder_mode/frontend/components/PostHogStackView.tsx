import { useMemo } from 'react'

import { IconArrowRight, IconBook } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonCard } from 'lib/lemon-ui/LemonCard'
import { LemonTag } from 'lib/lemon-ui/LemonTag'

import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'

import type { LandingPageBuildSpec } from './founderLandingPageLogic'
import {
    type ProductRecommendation,
    type RecommendationPriority,
    groupByPriority,
    recommendProducts,
} from './postHogStackRecommendations'

interface Props {
    spec: LandingPageBuildSpec
}

const PRIORITY_COPY: Record<
    RecommendationPriority,
    { label: string; blurb: string; tagType: 'danger' | 'warning' | 'option' }
> = {
    critical: {
        label: 'Set up first',
        blurb: "You won't know if the launch worked without these.",
        tagType: 'danger',
    },
    recommended: {
        label: 'Set up in week one',
        blurb: 'Big leverage for very little setup cost.',
        tagType: 'warning',
    },
    'nice-to-have': {
        label: 'Add when you have signal',
        blurb: 'Worth it once you have steady traffic to measure.',
        tagType: 'option',
    },
}

export function PostHogStackView({ spec }: Props): JSX.Element {
    const recs = useMemo(() => recommendProducts(spec), [spec])
    const grouped = useMemo(() => groupByPriority(recs), [recs])

    return (
        <div className="flex flex-col gap-6">
            <SummaryHeader spec={spec} recCount={recs.length} />
            {grouped.map((group) => (
                <PriorityGroup key={group.priority} priority={group.priority} items={group.items} />
            ))}
        </div>
    )
}

function SummaryHeader({ spec, recCount }: { spec: LandingPageBuildSpec; recCount: number }): JSX.Element {
    return (
        <LemonCard className="p-5">
            <h3 className="text-base font-semibold">Your PostHog stack for {spec.project_name}</h3>
            <p className="text-sm text-text-secondary mt-1">
                {recCount} product{recCount === 1 ? '' : 's'} pulled from your build spec. Each one answers a real
                question your launch will surface in week one.
            </p>
            <div className="mt-3 flex flex-wrap gap-2 text-[11px]">
                <span className="px-2 py-1 rounded bg-fill-highlight-100 border border-border text-text-secondary">
                    {spec.page_sections.length} page sections
                </span>
                <span className="px-2 py-1 rounded bg-fill-highlight-100 border border-border text-text-secondary">
                    {spec.project_brief.top_user_pains.length} pain points
                </span>
                <span className="px-2 py-1 rounded bg-fill-highlight-100 border border-border text-text-secondary">
                    {spec.project_brief.proof_points.length} proof points
                </span>
                <span className="px-2 py-1 rounded bg-fill-highlight-100 border border-border text-text-secondary">
                    {spec.seo_keywords.filter((k) => k.priority === 'high').length} high-priority keywords
                </span>
            </div>
        </LemonCard>
    )
}

function PriorityGroup({
    priority,
    items,
}: {
    priority: RecommendationPriority
    items: ProductRecommendation[]
}): JSX.Element {
    const copy = PRIORITY_COPY[priority]
    return (
        <section className="flex flex-col gap-3">
            <header className="flex items-baseline gap-3">
                <h4 className="text-sm font-semibold uppercase tracking-wide text-text-primary">{copy.label}</h4>
                <span className="text-xs text-text-secondary">{copy.blurb}</span>
            </header>
            <div className="grid grid-cols-1 gap-3">
                {items.map((item) => (
                    <RecommendationCard key={item.productKey} rec={item} priorityTagType={copy.tagType} />
                ))}
            </div>
        </section>
    )
}

function RecommendationCard({
    rec,
    priorityTagType,
}: {
    rec: ProductRecommendation
    priorityTagType: 'danger' | 'warning' | 'option'
}): JSX.Element {
    return (
        <LemonCard className="p-5">
            <div className="flex items-start gap-4">
                <div
                    className="shrink-0 w-10 h-10 rounded-lg bg-fill-highlight-100 border border-border flex items-center justify-center text-2xl group/colorful-product-icons colorful-product-icons-true"
                    aria-hidden
                >
                    {iconForType(rec.iconType)}
                </div>
                <div className="flex-1 min-w-0">
                    <div className="flex items-start justify-between gap-3 flex-wrap">
                        <div>
                            <h5 className="text-base font-semibold">{rec.name}</h5>
                            <p className="text-sm text-text-secondary mt-0.5">{rec.tagline}</p>
                        </div>
                        <LemonTag type={priorityTagType} className="shrink-0">
                            {rec.priority}
                        </LemonTag>
                    </div>

                    <p className="mt-3 text-sm text-text-primary leading-relaxed">{rec.why}</p>

                    <div className="mt-4">
                        <div className="text-[11px] uppercase tracking-wide text-text-tertiary mb-1.5">
                            First actions
                        </div>
                        <ul className="flex flex-col gap-1.5 text-sm text-text-primary list-none p-0">
                            {rec.firstActions.map((action, i) => (
                                <li key={i} className="flex items-start gap-2">
                                    <span className="text-text-tertiary mt-0.5 shrink-0">{i + 1}.</span>
                                    <span>{action}</span>
                                </li>
                            ))}
                        </ul>
                    </div>

                    {rec.sourceContext.length > 0 && (
                        <div className="mt-4">
                            <div className="text-[11px] uppercase tracking-wide text-text-tertiary mb-1.5">
                                From your build spec
                            </div>
                            <div className="flex flex-wrap gap-1.5">
                                {rec.sourceContext.map((ctx) => (
                                    <span
                                        key={ctx}
                                        className="text-[11px] px-2 py-0.5 rounded-full bg-fill-highlight-100 border border-border text-text-secondary"
                                    >
                                        {ctx}
                                    </span>
                                ))}
                            </div>
                        </div>
                    )}

                    <div className="mt-4 flex flex-wrap gap-2">
                        <LemonButton size="small" type="primary" to={rec.url} sideIcon={<IconArrowRight />}>
                            Set up {rec.name.toLowerCase()}
                        </LemonButton>
                        <LemonButton size="small" type="tertiary" to={rec.docsUrl} targetBlank icon={<IconBook />}>
                            Docs
                        </LemonButton>
                    </div>
                </div>
            </div>
        </LemonCard>
    )
}
