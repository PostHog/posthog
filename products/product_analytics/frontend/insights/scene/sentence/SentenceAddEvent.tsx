import { useActions } from 'kea'

import { IconPlus } from '@posthog/icons'
import { Button } from '@posthog/quill'

import type { InsightLogicProps } from '~/types'

import { EventPickerPopover } from './EventPickerPopover'
import { insightSentenceLogic } from './insightSentenceLogic'

export function SentenceAddEvent({ insightProps }: { insightProps: InsightLogicProps }): JSX.Element {
    const { addSeries } = useActions(insightSentenceLogic(insightProps))

    return (
        <EventPickerPopover
            onPick={(groupType, value, name) => addSeries(groupType, value, name)}
            trigger={(open, toggle) => (
                <Button
                    variant="outline"
                    size="sm"
                    aria-expanded={open}
                    onClick={toggle}
                    data-attr="quill-insight-add-event"
                >
                    <IconPlus />
                    and another event
                </Button>
            )}
        />
    )
}
