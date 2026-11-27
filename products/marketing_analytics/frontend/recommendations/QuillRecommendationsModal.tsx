import { useActions, useValues } from 'kea'
import { RefObject, useRef } from 'react'

import {
    Button,
    cn,
    Dialog,
    DialogBody,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
    Heading,
    Item,
    ItemActions,
    ItemContent,
    ItemDescription,
    ItemTitle,
    MenuLabel,
    Text,
} from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { MarketingAnalyticsRecommendation } from '~/queries/schema/schema-general'

import { QuillRecommendationCountBadge } from './QuillRecommendationCountBadge'
import { QuillRecommendationDataGapButton } from './QuillRecommendationDataGapButton'
import { QuillRecommendationImpactTotals } from './QuillRecommendationImpactTotals'
import { RecommendationDataGapDescription } from './RecommendationDataGapDescription'
import {
    conversionSourceLabel,
    RECOMMENDATION_CATEGORY_LABELS,
    RECOMMENDATION_RULE_DESCRIPTIONS,
    RECOMMENDATION_RULE_LABELS,
    RecommendationGroup,
} from './recommendations'
import { recommendationsLogic } from './recommendationsLogic'

export function QuillRecommendationsModal({
    navRef,
    detailRef,
    selectedGroupSubjectCount,
    onToggleResolved,
    onSelectGroup,
    renderRows,
}: {
    navRef: RefObject<HTMLElement>
    detailRef: RefObject<HTMLElement>
    selectedGroupSubjectCount: string | null
    onToggleResolved: () => void
    onSelectGroup: (group: RecommendationGroup) => void
    renderRows: (
        rows: MarketingAnalyticsRecommendation[],
        options: { keepOnly: boolean; showRule?: boolean }
    ) => JSX.Element
}): JSX.Element {
    const {
        showResolved,
        showingResolved,
        selectedRule,
        activeRecommendations,
        resolvedRecommendations,
        totals,
        resolvedCount,
        sections,
        selectedGroup,
        selectedGroupTotals,
        dataGaps,
        serverDataGaps,
        conversionSource,
        disclaimer,
    } = useValues(recommendationsLogic)
    const { reportRecommendationsActionClicked, closeRecommendations } = useActions(recommendationsLogic)
    // The header's first tabbable controls open tooltips on focus, so the dialog opens with focus on its title.
    const titleRef = useRef<HTMLHeadingElement>(null)

    return (
        <Dialog open={selectedRule !== null} onOpenChange={(open) => !open && closeRecommendations()}>
            <DialogContent size="wide" initialFocus={titleRef}>
                <DialogHeader className="gap-2">
                    <div className="flex flex-wrap items-center justify-between gap-2 pr-8">
                        <DialogTitle ref={titleRef} tabIndex={-1} className="m-0 outline-none">
                            Recommendations
                        </DialogTitle>
                        {dataGaps.length + serverDataGaps.length > 0 && (
                            <QuillRecommendationDataGapButton
                                gaps={dataGaps}
                                serverGaps={serverDataGaps}
                                dataAttr="marketing-recommendations-modal-data-gaps"
                                location="modal_data_gaps"
                            />
                        )}
                    </div>
                    <DialogDescription className="m-0 flex flex-wrap items-center gap-2">
                        <span>{`${activeRecommendations.length} for the selected sources and dates`}</span>
                        <QuillRecommendationImpactTotals totals={totals} />
                        {conversionSource && <span>{conversionSourceLabel(conversionSource)}</span>}
                        {resolvedCount > 0 && (
                            <Button onClick={onToggleResolved} data-attr="marketing-recommendations-toggle-resolved">
                                {showResolved
                                    ? 'Hide dismissed and applied'
                                    : `Review ${resolvedCount} dismissed or applied`}
                            </Button>
                        )}
                    </DialogDescription>
                </DialogHeader>
                <DialogBody>
                    <div className="@container">
                        <div className="flex flex-col gap-4 @2xl:flex-row">
                            <nav
                                ref={navRef}
                                className="flex flex-col @2xl:sticky @2xl:self-start @2xl:top-0 @2xl:w-60 @2xl:shrink-0 @2xl:border-r @2xl:border-border @2xl:pr-3"
                            >
                                {sections.map((section) => (
                                    <div
                                        key={section.category}
                                        className="flex flex-col gap-0.5 border-t border-border py-3 first:border-t-0 first:pt-0 last:pb-0"
                                    >
                                        <MenuLabel>{RECOMMENDATION_CATEGORY_LABELS[section.category]}</MenuLabel>
                                        {section.groups.map((group) => {
                                            const selected = !showingResolved && group.rule === selectedGroup?.rule
                                            return (
                                                <Button
                                                    key={group.rule}
                                                    size="row"
                                                    left
                                                    aria-current={selected ? 'true' : undefined}
                                                    className={cn(selected && 'bg-fill-selected')}
                                                    onClick={() => onSelectGroup(group)}
                                                    data-attr={`marketing-recommendations-group-${group.rule}`}
                                                >
                                                    <span className="min-w-0 flex-1 truncate text-left">
                                                        {RECOMMENDATION_RULE_LABELS[group.rule]}
                                                    </span>
                                                    <QuillRecommendationCountBadge
                                                        count={group.recommendations.length}
                                                        maxDigits={2}
                                                        showZero
                                                        variant={selected ? 'info' : 'default'}
                                                    />
                                                </Button>
                                            )
                                        })}
                                    </div>
                                ))}
                            </nav>
                            {showingResolved ? (
                                <section ref={detailRef} className="flex min-w-0 flex-1 flex-col gap-3">
                                    <Heading
                                        size="base"
                                        render={<h3 className="m-0 flex flex-wrap items-baseline gap-x-2" />}
                                    >
                                        <span>Dismissed and applied</span>
                                        <Text size="xs" variant="muted" render={<span translate="no" />}>
                                            {resolvedCount}
                                        </Text>
                                    </Heading>
                                    {renderRows(resolvedRecommendations, { keepOnly: false, showRule: true })}
                                </section>
                            ) : selectedGroup ? (
                                <section ref={detailRef} className="flex min-w-0 flex-1 flex-col gap-3">
                                    <div className="flex flex-wrap items-start justify-between gap-2">
                                        <div className="flex min-w-0 flex-col gap-1">
                                            <Heading
                                                size="base"
                                                render={<h3 className="m-0 flex flex-wrap items-baseline gap-x-2" />}
                                            >
                                                <span>{RECOMMENDATION_RULE_LABELS[selectedGroup.rule]}</span>
                                                <Text size="xs" variant="muted" render={<span />}>
                                                    {selectedGroupSubjectCount}
                                                </Text>
                                            </Heading>
                                            <Text size="xs" variant="muted" render={<p className="m-0" />}>
                                                {RECOMMENDATION_RULE_DESCRIPTIONS[selectedGroup.rule]}
                                            </Text>
                                        </div>
                                        <QuillRecommendationImpactTotals totals={selectedGroupTotals} />
                                    </div>
                                    {dataGaps
                                        .filter((gap) => gap.rules.includes(selectedGroup.rule))
                                        .map((gap) => (
                                            <Item
                                                key={`${gap.sourceId}-${gap.table}`}
                                                tone="info"
                                                size="sm"
                                                className="flex-wrap"
                                            >
                                                <ItemContent>
                                                    <ItemTitle>{gap.sourceName}</ItemTitle>
                                                    <ItemDescription>
                                                        <RecommendationDataGapDescription gap={gap} />
                                                    </ItemDescription>
                                                </ItemContent>
                                                <ItemActions>
                                                    <Button
                                                        variant="outline"
                                                        render={
                                                            <LinkPrimitive
                                                                to={urls.dataWarehouseSource(`managed-${gap.sourceId}`)}
                                                            />
                                                        }
                                                        data-attr="marketing-recommendations-rule-data-gap-manage-source"
                                                        onClick={() =>
                                                            reportRecommendationsActionClicked(
                                                                'manage_source',
                                                                'rule_banner',
                                                                selectedGroup.rule
                                                            )
                                                        }
                                                    >
                                                        Manage source
                                                    </Button>
                                                </ItemActions>
                                            </Item>
                                        ))}
                                    {selectedGroup.recommendations.length > 0 ? (
                                        renderRows(selectedGroup.recommendations, { keepOnly: selectedGroup.keepOnly })
                                    ) : (
                                        <Text size="xs" variant="muted" render={<p className="m-0 text-center" />}>
                                            Every recommendation in this rule is dismissed or applied. Review them to
                                            see each one.
                                        </Text>
                                    )}
                                </section>
                            ) : (
                                <Text size="xs" variant="muted" render={<p className="m-0" />}>
                                    {resolvedCount > 0
                                        ? 'Every recommendation for these sources and dates is dismissed or applied. Review them to see each one.'
                                        : 'No recommendations for the selected sources and dates.'}
                                </Text>
                            )}
                        </div>
                    </div>
                </DialogBody>
                {disclaimer ? (
                    <DialogFooter className="sm:justify-start">
                        <Text size="xs" variant="muted" render={<p className="m-0" />}>
                            {disclaimer}
                        </Text>
                    </DialogFooter>
                ) : null}
            </DialogContent>
        </Dialog>
    )
}
