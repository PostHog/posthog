import { useActions, useValues } from 'kea'

import { IconChevronRight } from '@posthog/icons'
import { Button, Item, ItemActions, ItemContent, ItemMedia, Text } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'

import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'

import { warehouseSuggestionsLogic } from '../warehouseSuggestionsLogic'
import { QuillSuggestionsSummary } from './QuillSuggestionsSummary'

export interface QuillSuggestionsBannerProps {
    reviewTo?: string
}

export function QuillSuggestionsBanner({ reviewTo }: QuillSuggestionsBannerProps): JSX.Element {
    const { surfaceSuggestions } = useValues(warehouseSuggestionsLogic)
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
                    <QuillSuggestionsSummary />
                </Text>
            </ItemContent>
            <ItemActions>
                <Button
                    variant="primary"
                    render={reviewTo ? <LinkPrimitive to={reviewTo} /> : undefined}
                    onClick={reviewTo ? undefined : () => openReview()}
                    data-attr="warehouse-suggestions-review"
                >
                    {`Review ${surfaceSuggestions.length}`}
                    <IconChevronRight />
                </Button>
            </ItemActions>
        </Item>
    )
}
