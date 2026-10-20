import { useValues } from 'kea'

import { IconCheck, IconWarning } from '@posthog/icons'
import { AccordionContent, AccordionItem, AccordionTrigger, Dot, Text } from '@posthog/quill'

import type { InsightLogicProps } from '~/types'

import type {
    InsightDataCheckApi,
    InsightDataCheckLevelEnumApi,
} from 'products/product_analytics/frontend/generated/api.schemas'

import { FILTER_CHECK_KEYS, dataCheckText } from './dataCheckText'
import { DuplicateEventsDetails } from './DuplicateEventsDetails'
import { FilterCheckDetails } from './FilterCheckDetails'
import { insightDataChecksLogic } from './insightDataChecksLogic'

const LEVEL_LABELS: Record<InsightDataCheckLevelEnumApi, string> = {
    passed: 'Passed',
    warning: 'Warning',
    problem: 'Problem',
    skipped: 'Not checked',
}

function LevelIcon({ level }: { level: InsightDataCheckApi['level'] }): JSX.Element {
    if (level === 'passed') {
        return <IconCheck className="size-4 text-(--success-foreground)" />
    }
    if (level === 'warning' || level === 'problem') {
        return (
            <IconWarning
                className={
                    level === 'problem'
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
    const { filtersTestAccounts, refreshing } = useValues(insightDataChecksLogic(insightProps))
    const text = dataCheckText(check, filtersTestAccounts)
    const dependsOnFilter = FILTER_CHECK_KEYS.includes(check.key)
    const foundRepeats = check.key === 'duplicate_events' && (check.level === 'warning' || check.level === 'problem')
    const hasDetails = dependsOnFilter || foundRepeats

    const header = (
        <span className="flex items-start gap-2">
            <span className="flex h-5 w-4 shrink-0 items-center justify-center">
                <LevelIcon level={check.level} />
            </span>
            <span className="flex flex-col">
                {/* No size of its own, so the name takes the text size that quill gives a popover. */}
                <Text size={null} weight="medium" render={<span />}>
                    {text.name}
                    <span className="sr-only">{`: ${LEVEL_LABELS[check.level]}`}</span>
                </Text>
                <Text
                    size="xs"
                    variant="muted"
                    className={refreshing ? 'animate-pulse motion-reduce:animate-none' : undefined}
                    render={<span />}
                >
                    {text.result}
                </Text>
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
        <AccordionItem value={check.key} data-attr="insight-data-check" data-check={check.key} data-level={check.level}>
            <AccordionTrigger className="px-2 py-1 font-normal">{header}</AccordionTrigger>
            <AccordionContent className="flex flex-col items-start gap-2 ps-6">
                {foundRepeats && <DuplicateEventsDetails insightProps={insightProps} check={check} />}
                {dependsOnFilter && <FilterCheckDetails insightProps={insightProps} check={check} />}
            </AccordionContent>
        </AccordionItem>
    )
}
