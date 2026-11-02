import { IconEllipsis } from '@posthog/icons'
import { Button, Popover, PopoverContent, PopoverTrigger } from '@posthog/quill'

import { DisplayOptionTab } from './insightDisplayOptions'
import { InsightDisplayOptionsPanel } from './InsightDisplayOptionsPanel'

export interface QuillInsightDisplayOptionsButtonProps {
    tabs: DisplayOptionTab[]
    advancedOptionsCount: number | undefined
    disabledReason: string | null
}

export function QuillInsightDisplayOptionsButton({
    tabs,
    advancedOptionsCount,
    disabledReason,
}: QuillInsightDisplayOptionsButtonProps): JSX.Element {
    return (
        <Popover>
            <PopoverTrigger
                render={
                    <Button
                        variant="default"
                        aria-label="Options"
                        disabledReason={disabledReason}
                        className="@max-[780px]:order-last"
                    />
                }
            >
                <span className="whitespace-nowrap @max-[780px]:hidden">
                    Options
                    {advancedOptionsCount ? (
                        <span className="ml-0.5 text-muted-foreground ligatures-none">({advancedOptionsCount})</span>
                    ) : null}
                </span>
                <IconEllipsis className="hidden @max-[780px]:block" />
            </PopoverTrigger>
            <PopoverContent align="end" className="w-auto p-0">
                <InsightDisplayOptionsPanel tabs={tabs} />
            </PopoverContent>
        </Popover>
    )
}
