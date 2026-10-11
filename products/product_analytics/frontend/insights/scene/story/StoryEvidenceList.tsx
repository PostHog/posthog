import { useValues } from 'kea'

import { IconArrowUpRight } from '@posthog/icons'
import { Button, Spinner, Text, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { Link } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import type { InsightLogicProps } from '~/types'

import { insightStoryLogic } from './insightStoryLogic'
import type { StoryChapter } from './insightStoryLogic'
import { StoryMarkedText } from './StoryMarkedText'

export interface StoryEvidenceListProps {
    insightProps: InsightLogicProps
    chapter: StoryChapter
    heading: string
}

export function StoryEvidenceList({ insightProps, chapter, heading }: StoryEvidenceListProps): JSX.Element | null {
    const { evidenceStatus } = useValues(insightStoryLogic(insightProps))
    const isLoading = chapter.hasCause && evidenceStatus === 'loading'

    if (!isLoading && !chapter.evidence.length && !chapter.hasCause) {
        return null
    }

    return (
        <div className="flex flex-col gap-1.5" data-attr="quill-insight-story-evidence">
            <Text size="xs" weight="medium" variant="muted">
                {heading}
            </Text>
            {isLoading ? (
                <div className="flex items-center gap-2" role="status">
                    <Spinner />
                    <Text size="sm" variant="muted">
                        Checking where it came from
                    </Text>
                </div>
            ) : !chapter.evidence.length ? (
                <Text size="sm" variant="muted">
                    The data we checked does not point at a cause.
                </Text>
            ) : (
                <ul className="m-0 flex list-none flex-col gap-2 p-0">
                    {chapter.evidence.map((item) => (
                        <li key={item.id} className="flex items-start gap-1 border-l-2 border-(--border) ps-2">
                            <Text size="sm" className="min-w-0 flex-1">
                                <StoryMarkedText text={item.text} />
                            </Text>
                            {item.query && (
                                <Tooltip>
                                    <TooltipTrigger
                                        render={
                                            <Button
                                                variant="default"
                                                size="icon-xs"
                                                aria-label="See the chart behind this"
                                                render={
                                                    <Link to={urls.insightNew({ query: item.query })} target="_blank" />
                                                }
                                                data-attr="quill-insight-story-evidence-chart"
                                            />
                                        }
                                    >
                                        <IconArrowUpRight />
                                    </TooltipTrigger>
                                    <TooltipContent side="left">See the chart behind this</TooltipContent>
                                </Tooltip>
                            )}
                        </li>
                    ))}
                </ul>
            )}
        </div>
    )
}
