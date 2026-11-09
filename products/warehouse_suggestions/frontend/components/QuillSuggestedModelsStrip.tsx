import { BindLogic, useActions, useValues } from 'kea'
import { ReactNode } from 'react'

import { IconChevronRight, IconLightBulb, IconWarning } from '@posthog/icons'
import { Button, Item, ItemActions, ItemContent, ItemMedia, Progress, Text } from '@posthog/quill'

import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'

import { WarehouseSuggestionsLogicProps, warehouseSuggestionsLogic } from '../warehouseSuggestionsLogic'
import { QuillSuggestedModelsDialogs } from './QuillSuggestedModelsDialogs'
import { SavingsBannerMessage } from './SavingsBannerMessage'
import { SuggestedModelsStripProps } from './SuggestedModelsStrip'

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

function QuillSuggestionsBanner(): JSX.Element {
    const { surfaceSuggestions, savingsSummary, unusedViewCount } = useValues(warehouseSuggestionsLogic)
    const { openReview } = useActions(warehouseSuggestionsLogic)

    return (
        <Item variant="outline" size="sm" className="flex-wrap">
            <ItemMedia
                variant="icon"
                className="group/colorful-product-icons colorful-product-icons-true translate-y-px"
            >
                {iconForType('data_modeling')}
            </ItemMedia>
            <ItemContent className="min-w-0">
                <Text size="sm" render={<span />}>
                    <SavingsBannerMessage summary={savingsSummary} unusedViews={unusedViewCount} />
                </Text>
            </ItemContent>
            <ItemActions>
                <Button variant="primary" onClick={() => openReview()} data-attr="warehouse-suggestions-review">
                    {`Review ${surfaceSuggestions.length}`}
                    <IconChevronRight />
                </Button>
            </ItemActions>
        </Item>
    )
}

function QuillSuggestedModelsStripContent(): JSX.Element | null {
    const { stripState, status } = useValues(warehouseSuggestionsLogic)
    const { reload } = useActions(warehouseSuggestionsLogic)
    const windowDays = status?.window_days ?? 0

    if (stripState === 'error') {
        return (
            <QuillSuggestionsNotice
                tone="warning"
                icon={<IconWarning />}
                message="Couldn't load suggested models."
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
                message="Suggested models get better as read history builds up."
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
                message="Suggested models start once people in this project read its views regularly."
            />
        )
    }
    if (stripState !== 'active' && stripState !== 'all_done') {
        return null
    }

    return (
        <>
            {stripState === 'active' && <QuillSuggestionsBanner />}
            <QuillSuggestedModelsDialogs />
        </>
    )
}

export function QuillSuggestedModelsStrip({
    onAccepted,
    placement = 'models_tab',
}: SuggestedModelsStripProps): JSX.Element {
    const logicProps: WarehouseSuggestionsLogicProps = { surface: 'models', placement, onAccepted }
    return (
        <BindLogic logic={warehouseSuggestionsLogic} props={logicProps}>
            <QuillSuggestedModelsStripContent />
        </BindLogic>
    )
}
