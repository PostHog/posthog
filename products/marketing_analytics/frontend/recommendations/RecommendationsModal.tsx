import { BindLogic, useActions, useValues } from 'kea'
import { useRef, useState } from 'react'

import { IconChevronDown, IconChevronRight } from '@posthog/icons'
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

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { ElapsedTime } from '~/queries/nodes/DataNode/ElapsedTime'
import { Reload } from '~/queries/nodes/DataNode/Reload'
import { MarketingAnalyticsRecommendation } from '~/queries/schema/schema-general'

import { RecommendationCpa } from './RecommendationCpa'
import { RecommendationDataGapButton } from './RecommendationDataGapButton'
import { RecommendationDataGapDescription } from './RecommendationDataGapDescription'
import { RecommendationResolutionButtons } from './RecommendationResolutionButtons'
import {
    IMPACT_DIRECTION_DESCRIPTIONS,
    IMPACT_DIRECTION_LABELS,
    RECOMMENDATION_CATEGORY_LABELS,
    RECOMMENDATION_RULE_DESCRIPTIONS,
    RECOMMENDATION_RULE_LABELS,
    RecommendationGroup,
    RecommendationTotal,
} from './recommendations'
import { recommendationsLogic } from './recommendationsLogic'
import { RecommendationSteps } from './RecommendationSteps'

const DIRECTION_TAG: Record<MarketingAnalyticsRecommendation['impactDirection'], LemonTagType> = {
    save: 'success',
    gain: 'info',
    invest: 'warning',
    keep: 'muted',
}

const SUBJECT_NOUNS: Record<MarketingAnalyticsRecommendation['level'], [string, string]> = {
    account: ['account', 'accounts'],
    campaign: ['campaign', 'campaigns'],
    search_term: ['search term', 'search terms'],
}

function subjectCount(group: RecommendationGroup, count: number): string {
    const [singular, plural] = SUBJECT_NOUNS[group.level]
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
    const { reportRecommendationsActionClicked } = useActions(recommendationsLogic)
    const [expanded, setExpanded] = useState<Set<string>>(new Set())
    const toggle = (key: string, rule: MarketingAnalyticsRecommendation['rule']): void => {
        if (!expanded.has(key)) {
            reportRecommendationsActionClicked('view_instructions', 'instructions', rule)
        }
        setExpanded((current) => {
            const next = new Set(current)
            if (!next.delete(key)) {
                next.add(key)
            }
            return next
        })
    }
    return (
        <LemonTable<MarketingAnalyticsRecommendation>
            size="small"
            dataSource={rows}
            rowKey={(row) => row.key}
            // Dims the content but not the last cell, so Restore still reads as a live button.
            rowClassName={(row) => (row.resolution ? '[&>td:not(:last-child)]:text-tertiary' : null)}
            expandable={{
                expandedRowRender: (row) => <RecommendationSteps steps={row.steps ?? []} rule={row.rule} />,
                rowExpandable: (row) => (row.steps?.length ? 1 : 0),
                isRowExpanded: (row) => expanded.has(row.key),
                showRowExpansionToggle: false,
            }}
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
                    render: (_, row) => {
                        const key = row.key
                        return (
                            <div className="flex flex-col items-start gap-0.5 py-1">
                                <span className="text-pretty">{row.action}</span>
                                <span className="text-xs text-secondary">{row.reason}</span>
                                <RecommendationCpa recommendation={row} />
                                {!!row.steps?.length && (
                                    <LemonButton
                                        size="xsmall"
                                        type="tertiary"
                                        className="-ml-1 mt-0.5"
                                        sideIcon={expanded.has(key) ? <IconChevronDown /> : <IconChevronRight />}
                                        onClick={() => toggle(key, row.rule)}
                                        data-attr="marketing-recommendations-view-instructions"
                                    >
                                        {expanded.has(key) ? 'Hide instructions' : 'View instructions'}
                                    </LemonButton>
                                )}
                            </div>
                        )
                    },
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
                {
                    key: 'resolution',
                    align: 'right',
                    width: 0,
                    render: (_, row) => <RecommendationResolutionButtons recommendation={row} />,
                },
            ]}
        />
    )
}

export function RecommendationsModal(): JSX.Element {
    const {
        showResolved,
        selectedRule,
        activeRecommendations,
        totals,
        resolvedCount,
        sections,
        selectedGroup,
        selectedGroupTotals,
        dataNodeProps,
        dataGaps,
        disclaimer,
    } = useValues(recommendationsLogic)
    const { reportRecommendationsActionClicked, setShowResolved, selectRule, closeRecommendations } =
        useActions(recommendationsLogic)
    const toggleResolved = (): void => {
        if (!showResolved) {
            reportRecommendationsActionClicked('show_resolved', 'modal')
        }
        setShowResolved(!showResolved)
    }
    const navRef = useRef<HTMLElement>(null)
    const detailRef = useRef<HTMLElement>(null)
    const selectGroup = (group: RecommendationGroup): void => {
        selectRule(group.rule, group.activeCount)
        // In a narrow modal the rule list sits above the table, so the table has to come into view.
        if ((detailRef.current?.offsetTop ?? 0) > (navRef.current?.offsetTop ?? 0) + 8) {
            requestAnimationFrame(() => detailRef.current?.scrollIntoView({ block: 'start', behavior: 'smooth' }))
        }
    }
    return (
        <LemonModal
            isOpen={selectedRule !== null}
            onClose={closeRecommendations}
            width={1120}
            title={
                <div className="flex flex-wrap items-center justify-between gap-2 pr-8">
                    <span>Recommendations</span>
                    <BindLogic logic={dataNodeLogic} props={dataNodeProps}>
                        <span className="flex items-center gap-2 text-sm font-normal">
                            {dataGaps.length > 0 && (
                                <RecommendationDataGapButton
                                    gaps={dataGaps}
                                    dataAttr="marketing-recommendations-modal-data-gaps"
                                    location="modal_data_gaps"
                                />
                            )}
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
                    <span>{`${activeRecommendations.length} for the selected sources and dates`}</span>
                    <ImpactTotals totals={totals} />
                    {resolvedCount > 0 && (
                        <LemonButton
                            size="xsmall"
                            type="tertiary"
                            onClick={toggleResolved}
                            data-attr="marketing-recommendations-toggle-resolved"
                        >
                            {showResolved
                                ? 'Hide dismissed and applied'
                                : `Review ${resolvedCount} dismissed or applied`}
                        </LemonButton>
                    )}
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
                                        onClick={() => selectGroup(group)}
                                        sideIcon={
                                            <LemonBadge.Number
                                                count={group.activeCount}
                                                maxDigits={2}
                                                showZero
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
                                            {subjectCount(selectedGroup, selectedGroup.activeCount)}
                                        </span>
                                    </h3>
                                    <p className="mb-0 text-secondary">
                                        {RECOMMENDATION_RULE_DESCRIPTIONS[selectedGroup.rule]}
                                    </p>
                                </div>
                                <ImpactTotals totals={selectedGroupTotals} />
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
                                            onClick: () =>
                                                reportRecommendationsActionClicked(
                                                    'manage_source',
                                                    'rule_banner',
                                                    selectedGroup.rule
                                                ),
                                        }}
                                    >
                                        <div className="font-semibold">{gap.sourceName}</div>
                                        <div>
                                            <RecommendationDataGapDescription gap={gap} />
                                        </div>
                                    </LemonBanner>
                                ))}
                            {selectedGroup.recommendations.length > 0 ? (
                                <RecommendationRows rows={selectedGroup.recommendations} />
                            ) : (
                                <p className="mb-0 text-secondary">
                                    Every recommendation in this rule is dismissed or applied. Review them to restore
                                    one.
                                </p>
                            )}
                        </section>
                    ) : (
                        <p className="mb-0 text-secondary">
                            {resolvedCount > 0
                                ? 'Every recommendation for these sources and dates is dismissed or applied. Review them to restore one.'
                                : 'No recommendations for the selected sources and dates.'}
                        </p>
                    )}
                </div>
            </div>
        </LemonModal>
    )
}
