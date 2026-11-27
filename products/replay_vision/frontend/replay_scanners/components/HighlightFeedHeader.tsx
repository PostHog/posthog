import clsx from 'clsx'
import { useActions, useValues } from 'kea'

import { IconChevronDown } from '@posthog/icons'
import { LemonButton, LemonMenu } from '@posthog/lemon-ui'

import { highlightFeedLogic } from '../highlightFeedLogic'
import { HighlightFeedCustomizeButton } from './HighlightFeedCustomizeButton'
import { HighlightFeedRangeMenu } from './HighlightFeedRangeMenu'

export function HighlightFeedHeader({ className }: { className?: string }): JSX.Element {
    const { scopedToMine, hasOwnScanners } = useValues(highlightFeedLogic)
    const { setOnlyMyScanners } = useActions(highlightFeedLogic)
    return (
        <div className={clsx('flex flex-wrap items-center gap-x-4 gap-y-2', className)}>
            <p className="m-0 min-w-0 text-sm text-secondary">
                Sessions your scanners picked out for signs of failures, struggles, or payment problems.
            </p>
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
                <HighlightFeedRangeMenu />
                <HighlightFeedCustomizeButton />
            </div>
        </div>
    )
}
