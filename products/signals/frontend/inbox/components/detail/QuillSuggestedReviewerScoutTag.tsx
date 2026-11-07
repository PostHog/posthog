import { Badge, Popover, PopoverContent, PopoverTrigger, Text } from '@posthog/quill'

/** The quill sibling of `SuggestedReviewerScoutTag`, for the report page behind `today-rail-nav`. */
export function QuillSuggestedReviewerScoutTag({ scoutNames }: { scoutNames: string[] }): JSX.Element {
    // The popover holds the only copy of the scout names, so it opens on tap as well as on hover.
    return (
        <Popover>
            <PopoverTrigger openOnHover render={<Badge render={<button type="button" />} className="cursor-help" />}>
                Added by scout
            </PopoverTrigger>
            <PopoverContent side="top" className="flex flex-col gap-1">
                {scoutNames.map((scoutName) => (
                    <Text key={scoutName} size="xs" className="m-0">
                        {scoutName}
                    </Text>
                ))}
            </PopoverContent>
        </Popover>
    )
}
