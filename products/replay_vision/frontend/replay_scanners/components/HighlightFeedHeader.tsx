import clsx from 'clsx'
import { useActions, useValues } from 'kea'

import { IconChevronDown } from '@posthog/icons'
import { LemonButton, LemonMenu } from '@posthog/lemon-ui'

import { FEED_DATE_OPTIONS, feedWindowOption, highlightFeedLogic } from '../highlightFeedLogic'
import { HighlightFeedCustomizeButton } from './HighlightFeedCustomizeButton'

export function HighlightFeedHeader({ className }: { className?: string }): JSX.Element {
    const { dateFrom, scopedToMine, hasOwnScanners } = useValues(highlightFeedLogic)
    const { setDateFrom, setOnlyMyScanners } = useActions(highlightFeedLogic)
    return (
        <div className={clsx('flex flex-wrap items-end gap-x-4 gap-y-2', className)}>
            <div className="flex min-w-0 flex-col">
                <h3 className="m-0 text-base font-semibold">Sessions worth watching</h3>
                <p className="m-0 text-xs text-secondary">
                    Picked from your scanners for signs of failures, struggles, or payment problems.
                </p>
            </div>
            <div className="ml-auto flex items-center gap-1">
                {/* Only someone who created a scanner has a "mine" to narrow to. */}
                {hasOwnScanners && (
                    <LemonMenu
                        items={[
                            {
                                label: 'All scanners',
                                active: !scopedToMine,
                                onClick: () => setOnlyMyScanners(false),
                                'data-attr': 'vision-highlight-feed-scope-all',
                            },
                            {
                                label: 'My scanners',
                                active: scopedToMine,
                                onClick: () => setOnlyMyScanners(true),
                                'data-attr': 'vision-highlight-feed-scope-mine',
                            },
                        ]}
                    >
                        <LemonButton
                            size="small"
                            type="tertiary"
                            sideIcon={<IconChevronDown />}
                            data-attr="vision-highlight-feed-scope"
                        >
                            {scopedToMine ? 'My scanners' : 'All scanners'}
                        </LemonButton>
                    </LemonMenu>
                )}
                <LemonMenu
                    items={FEED_DATE_OPTIONS.map((option) => ({
                        label: option.label,
                        active: option.value === dateFrom,
                        onClick: () => setDateFrom(option.value),
                    }))}
                >
                    <LemonButton
                        size="small"
                        type="tertiary"
                        sideIcon={<IconChevronDown />}
                        data-attr="vision-highlight-feed-range"
                    >
                        {feedWindowOption(dateFrom)?.label ?? dateFrom}
                    </LemonButton>
                </LemonMenu>
                <HighlightFeedCustomizeButton />
            </div>
        </div>
    )
}
