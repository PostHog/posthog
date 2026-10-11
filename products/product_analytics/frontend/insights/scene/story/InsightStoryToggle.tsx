import { useActions, useValues } from 'kea'

import { IconSparkles } from '@posthog/icons'
import { Button } from '@posthog/quill'

import type { InsightLogicProps } from '~/types'

import { insightStoryLogic } from './insightStoryLogic'

export function InsightStoryToggle({ insightProps }: { insightProps: InsightLogicProps }): JSX.Element | null {
    const { storyAvailable, storyOpen } = useValues(insightStoryLogic(insightProps))
    const { openStory, closeStory } = useActions(insightStoryLogic(insightProps))

    if (!storyAvailable) {
        return null
    }

    return (
        <Button
            variant={storyOpen ? 'secondary' : 'outline'}
            size="sm"
            aria-pressed={storyOpen}
            onClick={() => (storyOpen ? closeStory() : openStory())}
            data-attr="quill-insight-story-toggle"
        >
            <IconSparkles />
            Walk me through it
        </Button>
    )
}
