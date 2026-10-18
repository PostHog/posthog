import { useValues } from 'kea'

import { IconCheck, IconWarning } from '@posthog/icons'
import { Dot, Spinner, cn } from '@posthog/quill'

import { pluralize } from 'lib/utils/strings'

import type { InsightLogicProps } from '~/types'

import { DataChecksPopover } from './DataChecksPopover'
import { insightDataChecksLogic } from './insightDataChecksLogic'
import type { InsightDataChecksStatus } from './insightDataChecksLogic'

const COLORS: Partial<Record<InsightDataChecksStatus, string>> = {
    passed: 'border-(--success-foreground) bg-(--success) text-(--success-foreground)',
    warning: 'border-(--warning-foreground) bg-(--warning) text-(--warning-foreground)',
    problem: 'border-(--destructive-foreground) bg-(--destructive) text-(--destructive-foreground)',
}

function statusLabel(status: InsightDataChecksStatus, findingCount: number): string {
    switch (status) {
        case 'checking':
            return 'Checking data'
        case 'failed':
            return "Data checks didn't finish"
        case 'no_events':
            return 'No data to check'
        case 'inconclusive':
            return 'Data not checked'
        case 'warning':
            return pluralize(findingCount, 'data warning')
        case 'problem':
            return pluralize(findingCount, 'data issue')
        default:
            return 'No data issues found'
    }
}

export function InsightDataChecks({ insightProps }: { insightProps: InsightLogicProps }): JSX.Element | null {
    const { findings, labelOpen, status } = useValues(insightDataChecksLogic(insightProps))

    if (status === 'unavailable' || status === 'unsupported') {
        return null
    }

    return (
        <DataChecksPopover
            insightProps={insightProps}
            trigger={
                <button
                    type="button"
                    data-quill
                    className={cn(
                        'group/checks inline-flex cursor-pointer items-center rounded-full border-2 p-0',
                        'transition-colors duration-700 motion-reduce:duration-0',
                        'focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-(--ring)',
                        COLORS[status] ?? 'border-(--border) bg-(--muted) text-(--muted-foreground)'
                    )}
                    data-attr="insight-data-checks"
                    data-status={status}
                />
            }
        >
            <span
                key={status}
                className="inline-flex size-5 shrink-0 items-center justify-center transition-opacity duration-500 starting:opacity-0"
            >
                {status === 'passed' ? (
                    <IconCheck className="size-4" />
                ) : status === 'checking' ? (
                    <Spinner className="size-3.5" />
                ) : status === 'no_events' || status === 'inconclusive' ? (
                    <Dot variant="default" />
                ) : (
                    <IconWarning className="size-4" />
                )}
            </span>
            <span
                className={cn(
                    'overflow-hidden text-xs font-medium whitespace-nowrap',
                    'transition-[max-width,opacity] duration-700 ease-out motion-reduce:duration-0',
                    labelOpen ? 'max-w-40 opacity-100' : 'max-w-0 opacity-0',
                    'group-hover/checks:max-w-40 group-hover/checks:opacity-100',
                    'group-focus-visible/checks:max-w-40 group-focus-visible/checks:opacity-100',
                    'group-data-popup-open/checks:max-w-40 group-data-popup-open/checks:opacity-100'
                )}
            >
                <span key={status} className="pe-2.5 transition-opacity duration-500 starting:opacity-0">
                    {statusLabel(status, findings.length)}
                </span>
            </span>
        </DataChecksPopover>
    )
}
