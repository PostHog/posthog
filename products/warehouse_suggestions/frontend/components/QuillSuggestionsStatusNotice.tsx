import { useActions, useValues } from 'kea'
import { ReactNode } from 'react'

import { IconLightBulb, IconWarning } from '@posthog/icons'
import { Button, Item, ItemActions, ItemContent, ItemMedia, Progress, Text } from '@posthog/quill'

import { warehouseSuggestionsLogic } from '../warehouseSuggestionsLogic'

function QuillSuggestionsNotice({
    icon,
    message,
    extra,
    tone,
}: {
    icon: ReactNode
    message: string
    extra?: ReactNode
    tone?: 'warning'
}): JSX.Element {
    return (
        <Item variant="outline" size="sm" tone={tone} className="flex-wrap">
            <ItemMedia variant="icon">{icon}</ItemMedia>
            <ItemContent className="min-w-0">
                <Text size="sm" render={<span />}>
                    {message}
                </Text>
            </ItemContent>
            {extra && <ItemActions>{extra}</ItemActions>}
        </Item>
    )
}

export function QuillSuggestionsStatusNotice(): JSX.Element | null {
    const { stripState, status } = useValues(warehouseSuggestionsLogic)
    const { reload } = useActions(warehouseSuggestionsLogic)
    const windowDays = status?.window_days ?? 0

    if (stripState === 'error') {
        return (
            <QuillSuggestionsNotice
                tone="warning"
                icon={<IconWarning />}
                message="Couldn't load suggestions."
                extra={
                    <Button variant="outline" size="sm" onClick={() => reload()}>
                        Retry
                    </Button>
                }
            />
        )
    }
    if (stripState === 'warming_up') {
        const daysWithData = status?.days_with_data ?? 0
        return (
            <QuillSuggestionsNotice
                icon={<IconLightBulb />}
                message="Suggestions get better as read history builds up."
                extra={
                    <span className="flex shrink-0 items-center gap-2 whitespace-nowrap">
                        <Progress
                            className="w-24"
                            value={windowDays ? (daysWithData / windowDays) * 100 : 0}
                            aria-label="Days of read history"
                        />
                        <Text size="xs" variant="muted" render={<span translate="no" className="tabular-nums" />}>
                            {`${daysWithData} of ${windowDays} days`}
                        </Text>
                    </span>
                }
            />
        )
    }
    if (stripState === 'not_eligible') {
        return (
            <QuillSuggestionsNotice
                icon={<IconLightBulb />}
                message="Suggestions start once people in this project read its views regularly."
            />
        )
    }
    return null
}
