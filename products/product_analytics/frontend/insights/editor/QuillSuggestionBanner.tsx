import { IconCheck, IconInfo, IconX } from '@posthog/icons'
import { Button, Dot, Text, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { pluralize } from 'lib/utils/strings'

export interface QuillSuggestionBannerProps {
    containerRef: React.RefObject<HTMLDivElement>
    changedLabels: string[]
    diffString: string
    onKeep: () => void
    onReject: () => void
}

export function QuillSuggestionBanner({
    containerRef,
    changedLabels,
    diffString,
    onKeep,
    onReject,
}: QuillSuggestionBannerProps): JSX.Element {
    return (
        <div className="w-full px-2" ref={containerRef}>
            <div
                data-quill
                className="mx-auto flex w-full flex-wrap items-center justify-between gap-1 rounded-b-md bg-muted p-1 pl-2"
            >
                <div className="flex items-center gap-2">
                    <Dot variant="info" />
                    <Text size="xs" variant="muted" render={<span />}>
                        {pluralize(changedLabels.length, 'change')}
                    </Text>
                    {changedLabels.length > 0 && (
                        <Tooltip>
                            <TooltipTrigger
                                render={<span className="inline-flex text-muted-foreground" />}
                                aria-label="Changed sections"
                            >
                                <IconInfo />
                            </TooltipTrigger>
                            <TooltipContent>
                                <div className="whitespace-pre-line">{diffString}</div>
                            </TooltipContent>
                        </Tooltip>
                    )}
                </div>
                <div className="flex flex-wrap items-center gap-1">
                    <Button
                        variant="destructive-outline"
                        onClick={onReject}
                        tooltip="Go back to the query from before these changes"
                        data-attr="insight-suggestion-reject"
                    >
                        <IconX />
                        Reject changes
                    </Button>
                    <Button
                        onClick={onKeep}
                        tooltip="Keep these changes. They stay unsaved until you save the insight."
                        data-attr="insight-suggestion-keep"
                    >
                        <IconCheck />
                        Keep changes
                    </Button>
                </div>
            </div>
        </div>
    )
}
