import { useActions, useValues } from 'kea'

import { IconChevronDown } from '@posthog/icons'
import { LemonButton, LemonMenu } from '@posthog/lemon-ui'

import { FEED_DATE_OPTIONS, feedWindowOption, highlightFeedLogic } from '../highlightFeedLogic'

export function HighlightFeedRangeMenu(): JSX.Element {
    const { dateFrom } = useValues(highlightFeedLogic)
    const { setDateFrom } = useActions(highlightFeedLogic)
    return (
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
    )
}
