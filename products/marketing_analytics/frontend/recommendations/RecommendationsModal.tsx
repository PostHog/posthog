import { BindLogic } from 'kea'
import { useRef } from 'react'

import {
    LemonBadge,
    LemonBanner,
    LemonButton,
    LemonModal,
    LemonTable,
    LemonTag,
    LemonTagType,
    Tooltip,
} from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'
import { formatMarketingMoney } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/utils'

import { DataNodeLogicProps, dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { ElapsedTime } from '~/queries/nodes/DataNode/ElapsedTime'
import { Reload } from '~/queries/nodes/DataNode/Reload'
import { MarketingAnalyticsRecommendation } from '~/queries/schema/schema-general'

import {
    IMPACT_DIRECTION_DESCRIPTIONS,
    IMPACT_DIRECTION_LABELS,
    RECOMMENDATION_CATEGORY_LABELS,
    RECOMMENDATION_RULE_DESCRIPTIONS,
    RECOMMENDATION_RULE_LABELS,
    RecommendationDataGap,
    RecommendationGroup,
    RecommendationSection,
    RecommendationTotal,
} from './recommendations'

const DIRECTION_TAG: Record<MarketingAnalyticsRecommendation['impactDirection'], LemonTagType> = {
    save: 'success',
    gain: 'info',
    invest: 'warning',
    keep: 'muted',
}

const SUBJECT_NOUNS: Record<MarketingAnalyticsRecommendation['level'], [string, string]> = {
    campaign: ['campaign', 'campaigns'],
    search_term: ['search term', 'search terms'],
}

function subjectCount(group: RecommendationGroup): string {
    const [singular, plural] = SUBJECT_NOUNS[group.level]
    const count = group.recommendations.length
    return `${count} ${count === 1 ? singular : plural}`
}

function ImpactTotals({ totals }: { totals: RecommendationTotal[] }): JSX.Element {
    return (
        <span className="flex flex-wrap items-center gap-1">
            {totals.map((total) => (
                <Tooltip
                    key={`${total.direction}-${total.currency}`}
                    title={IMPACT_DIRECTION_DESCRIPTIONS[total.direction]}
                >
                    <LemonTag type={DIRECTION_TAG[total.direction]}>
                        <span translate="no">
                            {`${IMPACT_DIRECTION_LABELS[total.direction]} ${formatMarketingMoney(total.amount, total.currency, true)}/mo`}
                        </span>
                    </LemonTag>
                </Tooltip>
            ))}
        </span>
    )
}

function RecommendationRows({ rows }: { rows: MarketingAnalyticsRecommendation[] }): JSX.Element {
    return (
        <LemonTable<MarketingAnalyticsRecommendation>
            size="small"
            dataSource={rows}
            rowKey={(row, index) => `${row.rule}-${row.subject}-${row.campaign ?? ''}-${index}`}
            columns={[
                {
                    title: 'For',
                    key: 'subject',
                    width: '28%',
                    render: (_, row) => (
                        <div className="flex flex-col py-1 break-words">
                            <span className="font-semibold">{row.subject}</span>
                            {row.campaign && <span className="text-xs text-secondary">{row.campaign}</span>}
                        </div>
                    ),
                },
                {
                    title: 'Recommendation',
                    key: 'action',
                    render: (_, row) => (
                        <div className="flex flex-col gap-0.5 py-1">
                            <span>{row.action}</span>
                            <span className="text-xs text-secondary">{row.reason}</span>
                        </div>
                    ),
                },
                {
                    title: 'Impact',
                    key: 'impact',
                    align: 'right',
                    width: 140,
                    render: (_, row) =>
                        row.impact == null ? (
                            <span className="text-secondary">–</span>
                        ) : (
                            <div className="flex flex-col items-end gap-0.5 py-1 whitespace-nowrap">
                                <span className="font-semibold tabular-nums" translate="no">
                                    {`${formatMarketingMoney(row.impact, row.currency)}/mo`}
                                </span>
                                <LemonTag type={DIRECTION_TAG[row.impactDirection]} size="small">
                                    {row.impactType === 'estimated'
                                        ? `${IMPACT_DIRECTION_LABELS[row.impactDirection]}, estimated`
                                        : IMPACT_DIRECTION_LABELS[row.impactDirection]}
                                </LemonTag>
                            </div>
                        ),
                },
            ]}
        />
    )
}

export function RecommendationsModal({
    isOpen,
    onClose,
    total,
    totals,
    sections,
    selectedGroup,
    onSelect,
    dataNodeProps,
    dataGaps,
    disclaimer,
}: {
    isOpen: boolean
    onClose: () => void
    total: number
    totals: RecommendationTotal[]
    sections: RecommendationSection[]
    selectedGroup: RecommendationGroup | undefined
    onSelect: (rule: string) => void
    dataNodeProps: DataNodeLogicProps
    dataGaps: RecommendationDataGap[]
    disclaimer: string | undefined
}): JSX.Element {
    const navRef = useRef<HTMLElement>(null)
    const detailRef = useRef<HTMLElement>(null)
    const selectRule = (rule: string): void => {
        onSelect(rule)
        // In a narrow modal the rule list sits above the table, so the table has to come into view.
        if ((detailRef.current?.offsetTop ?? 0) > (navRef.current?.offsetTop ?? 0) + 8) {
            requestAnimationFrame(() => detailRef.current?.scrollIntoView({ block: 'start', behavior: 'smooth' }))
        }
    }
    return (
        <LemonModal
            isOpen={isOpen}
            onClose={onClose}
            width={1120}
            title={
                <div className="flex flex-wrap items-center justify-between gap-2 pr-8">
                    <span>Recommendations</span>
                    <BindLogic logic={dataNodeLogic} props={dataNodeProps}>
                        <span className="flex items-center gap-2 text-sm font-normal">
                            <ElapsedTime />
                            <Reload />
                        </span>
                    </BindLogic>
                </div>
            }
            footer={
                disclaimer ? (
                    <p className="mb-0 mr-auto text-xs text-secondary whitespace-normal">{disclaimer}</p>
                ) : undefined
            }
            description={
                <span className="flex flex-wrap items-center gap-2">
                    <span>{`${total} for the selected sources and dates`}</span>
                    <ImpactTotals totals={totals} />
                </span>
            }
        >
            <div className="@container">
                <div className="grid gap-4 @min-[44rem]:grid-cols-[15rem_minmax(0,1fr)]">
                    <nav
                        ref={navRef}
                        className="flex flex-col self-start @min-[44rem]:sticky @min-[44rem]:top-0 @min-[44rem]:border-r @min-[44rem]:pr-3"
                    >
                        {sections.map((section) => (
                            <div
                                key={section.category}
                                className="flex flex-col gap-0.5 py-3 first:pt-0 last:pb-0 border-t first:border-t-0"
                            >
                                <span className="px-2 pb-1.5 text-xs font-semibold uppercase tracking-wide text-tertiary">
                                    {RECOMMENDATION_CATEGORY_LABELS[section.category]}
                                </span>
                                {section.groups.map((group) => (
                                    <LemonButton
                                        key={group.rule}
                                        size="small"
                                        fullWidth
                                        active={group.rule === selectedGroup?.rule}
                                        onClick={() => selectRule(group.rule)}
                                        sideIcon={
                                            <LemonBadge.Number
                                                count={group.recommendations.length}
                                                maxDigits={2}
                                                status={group.rule === selectedGroup?.rule ? 'primary' : 'muted'}
                                            />
                                        }
                                        data-attr={`marketing-recommendations-group-${group.rule}`}
                                    >
                                        {RECOMMENDATION_RULE_LABELS[group.rule]}
                                    </LemonButton>
                                ))}
                            </div>
                        ))}
                    </nav>
                    {selectedGroup ? (
                        <section ref={detailRef} className="flex flex-col gap-3 min-w-0">
                            <div className="flex flex-wrap items-start justify-between gap-2">
                                <div className="flex flex-col gap-1 min-w-0">
                                    <h3 className="mb-0">
                                        {RECOMMENDATION_RULE_LABELS[selectedGroup.rule]}
                                        <span className="ml-2 text-sm font-normal text-secondary">
                                            {subjectCount(selectedGroup)}
                                        </span>
                                    </h3>
                                    <p className="mb-0 text-secondary">
                                        {RECOMMENDATION_RULE_DESCRIPTIONS[selectedGroup.rule]}
                                    </p>
                                </div>
                                <ImpactTotals totals={selectedGroup.totals} />
                            </div>
                            {dataGaps
                                .filter((gap) => gap.rules.includes(selectedGroup.rule))
                                .map((gap) => (
                                    <LemonBanner
                                        key={`${gap.sourceId}-${gap.table}`}
                                        type="info"
                                        action={{
                                            children: 'Manage source',
                                            to: urls.dataWarehouseSource(`managed-${gap.sourceId}`),
                                            'data-attr': 'marketing-recommendations-rule-data-gap-manage-source',
                                        }}
                                    >
                                        <div className="font-semibold">{gap.sourceName}</div>
                                        <div>{gap.description}</div>
                                    </LemonBanner>
                                ))}
                            <RecommendationRows rows={selectedGroup.recommendations} />
                        </section>
                    ) : (
                        <p className="mb-0 text-secondary">No recommendations for the selected sources and dates.</p>
                    )}
                </div>
            </div>
        </LemonModal>
    )
}
