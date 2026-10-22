import { useActions, useValues } from 'kea'

import { IconCheck, IconWarning } from '@posthog/icons'
import { AccordionContent, AccordionItem, AccordionTrigger, Dot, Skeleton, Spinner, Text } from '@posthog/quill'

import type { InsightLogicProps } from '~/types'

import type {
    InsightDataCheckApi,
    InsightDataCheckLevelEnumApi,
} from 'products/product_analytics/frontend/generated/api.schemas'

import { FILTER_CHECK_KEYS, dataCheckText, isFinding } from './dataCheckText'
import { DuplicateEventsDetails } from './DuplicateEventsDetails'
import { FilterCheckDetails } from './FilterCheckDetails'
import { insightDataChecksLogic } from './insightDataChecksLogic'

const LEVEL_LABELS: Record<InsightDataCheckLevelEnumApi, string> = {
    passed: 'Passed',
    warning: 'Warning',
    problem: 'Problem',
    skipped: 'Not checked',
}

function LevelIcon({ check }: { check: InsightDataCheckApi }): JSX.Element {
    if (check.level === 'passed') {
        return <IconCheck className="size-4 text-(--success-foreground)" />
    }
    if (isFinding(check)) {
        return (
            <IconWarning
                className={
                    check.level === 'problem'
                        ? 'size-4 text-(--destructive-foreground)'
                        : 'size-4 text-(--warning-foreground)'
                }
            />
        )
    }
    return <Dot variant="default" />
}

export function InsightDataCheckRow({
    insightProps,
    check,
}: {
    insightProps: InsightLogicProps
    check: InsightDataCheckApi
}): JSX.Element {
    const logic = insightDataChecksLogic(insightProps)
    const { filtersTestAccounts, status } = useValues(logic)
    const { reportCheckExpanded } = useActions(logic)
    const checking = status === 'checking'
    const text = dataCheckText(check, filtersTestAccounts)
    const dependsOnFilter = FILTER_CHECK_KEYS.includes(check.key)
    const foundRepeats = check.key === 'duplicate_events' && isFinding(check)
    const hasDetails = dependsOnFilter || foundRepeats

    const header = (
        <span className="flex items-start gap-2">
            <span className="flex h-5 w-4 shrink-0 items-center justify-center">
                {checking ? <Spinner aria-hidden className="text-(--muted-foreground)" /> : <LevelIcon check={check} />}
            </span>
            <span className="flex flex-col">
                {/* No size of its own, so the name takes the text size that quill gives a popover. */}
                <Text size={null} weight="medium" render={<span />}>
                    {text.name}
                    <span className="sr-only">{`: ${checking ? 'Checking' : LEVEL_LABELS[check.level]}`}</span>
                </Text>
                {checking ? (
                    <span className="flex h-4 items-center">
                        <Skeleton className="h-2.5 w-28" />
                    </span>
                ) : (
                    <Text size="xs" variant="muted" render={<span />}>
                        {text.result}
                    </Text>
                )}
            </span>
        </span>
    )

    if (!hasDetails) {
        return (
            <div
                data-attr="insight-data-check"
                data-check={check.key}
                data-level={check.level}
                className="border-b border-(--border) px-2 py-1 last:border-b-0"
            >
                {header}
            </div>
        )
    }

    return (
        <AccordionItem
            value={check.key}
            onOpenChange={(open) => {
                if (open) {
                    reportCheckExpanded(check)
                }
            }}
            data-attr="insight-data-check"
            data-check={check.key}
            data-level={check.level}
            // The trigger sits in an h3, and the app's base styles give every h3 a bottom margin.
            className="[&>h3]:m-0"
        >
            <AccordionTrigger className="px-2 py-1 font-normal">{header}</AccordionTrigger>
            <AccordionContent className="flex flex-col items-start gap-2 ps-6 pt-2">
                {foundRepeats && <DuplicateEventsDetails insightProps={insightProps} check={check} />}
                {dependsOnFilter && <FilterCheckDetails insightProps={insightProps} check={check} />}
            </AccordionContent>
        </AccordionItem>
    )
}
