import { useActions, useValues } from 'kea'

import { IconCopy, IconSearch, IconSparkles } from '@posthog/icons'
import { Button, Text } from '@posthog/quill'

import type { InsightLogicProps } from '~/types'

import { insightStoryLogic } from './insightStoryLogic'
import type { StoryChapter } from './insightStoryLogic'

export function StoryDigDeeper({
    insightProps,
    chapter,
}: {
    insightProps: InsightLogicProps
    chapter: StoryChapter
}): JSX.Element {
    const { zoomEnabled } = useValues(insightStoryLogic(insightProps))
    const { sendMomentPrompt, zoomToMoment } = useActions(insightStoryLogic(insightProps))
    const { moment } = chapter
    const canZoom = zoomEnabled && (moment.kind === 'peak' || moment.kind === 'dip')

    return (
        <div className="flex flex-col gap-2" data-attr="quill-insight-story-dig-deeper">
            <div className="flex flex-col gap-1">
                <Text size="xs" weight="medium" variant="muted">
                    Dig deeper
                </Text>
                <Text size="xs" variant="muted">
                    Ask PostHog AI to look into this part, or copy the prompt for your own agent. The prompt has this
                    chart and what we found.
                </Text>
            </div>
            <div className="flex flex-wrap gap-1">
                <Button
                    variant="outline"
                    size="sm"
                    onClick={() => sendMomentPrompt(moment.id, 'posthog_ai')}
                    data-attr="quill-insight-story-ask-ai"
                >
                    <IconSparkles />
                    Ask PostHog AI
                </Button>
                <Button
                    variant="outline"
                    size="sm"
                    onClick={() => sendMomentPrompt(moment.id, 'clipboard')}
                    data-attr="quill-insight-story-copy-prompt"
                >
                    <IconCopy />
                    Copy prompt
                </Button>
                {canZoom && (
                    <Button
                        variant="outline"
                        size="sm"
                        onClick={() => zoomToMoment(moment.id)}
                        data-attr="quill-insight-story-zoom"
                    >
                        <IconSearch />
                        Zoom in
                    </Button>
                )}
            </div>
        </div>
    )
}
