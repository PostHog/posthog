import { useActions, useValues } from 'kea'

import { IconLightBulb } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { countOf } from '../suggestionCopy'
import { warehouseSuggestionsLogic } from '../warehouseSuggestionsLogic'
import { SuggestionsStatusNotice } from './SuggestionsStatusNotice'

export function WaitingSuggestionsNotice(): JSX.Element {
    const { status, showingMore } = useValues(warehouseSuggestionsLogic)
    const { showMore } = useActions(warehouseSuggestionsLogic)

    return (
        <SuggestionsStatusNotice
            icon={<IconLightBulb />}
            message={`You've reviewed today's suggestions. ${countOf(status?.waiting ?? 0, 'more is', 'more are')} waiting.`}
            extra={
                <LemonButton
                    size="xsmall"
                    type="secondary"
                    loading={showingMore}
                    onClick={() => showMore('strip')}
                    data-attr="warehouse-suggestions-show-more"
                >
                    Show more
                </LemonButton>
            }
        />
    )
}
