import { useActions, useValues } from 'kea'

import { IconUndo } from '@posthog/icons'
import { Button, Text } from '@posthog/quill'

import type { InsightLogicProps } from '~/types'

import { insightStoryLogic } from './insightStoryLogic'

export function StoryZoomReturn({ insightProps }: { insightProps: InsightLogicProps }): JSX.Element | null {
    const { zoomReturnTarget } = useValues(insightStoryLogic(insightProps))
    const { returnFromZoom } = useActions(insightStoryLogic(insightProps))

    if (!zoomReturnTarget) {
        return null
    }

    return (
        <div
            className="flex items-center justify-between gap-3 border-b border-(--border) bg-(--muted) py-2 ps-5 pe-3"
            data-attr="quill-insight-story-zoom-return"
        >
            <Text size="xs" variant="muted" className="min-w-0 truncate">
                Zoomed in on: {zoomReturnTarget.title}
            </Text>
            <Button
                variant="outline"
                size="sm"
                className="shrink-0"
                onClick={() => returnFromZoom()}
                data-attr="quill-insight-story-zoom-return-button"
            >
                <IconUndo />
                Back to chapter {zoomReturnTarget.position}
            </Button>
        </div>
    )
}
