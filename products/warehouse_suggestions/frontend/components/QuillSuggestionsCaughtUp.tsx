import { useActions, useValues } from 'kea'

import { Button, Text } from '@posthog/quill'

import { waitingSuggestionsText } from '../suggestionCopy'
import { ShowMorePlacement, warehouseSuggestionsLogic } from '../warehouseSuggestionsLogic'

export interface QuillSuggestionsCaughtUpProps {
    placement: ShowMorePlacement
}

export function QuillSuggestionsCaughtUp({ placement }: QuillSuggestionsCaughtUpProps): JSX.Element {
    const { status, showingMore } = useValues(warehouseSuggestionsLogic)
    const { showMore } = useActions(warehouseSuggestionsLogic)

    return (
        <div tabIndex={-1} data-suggestions-done className="flex flex-col items-center gap-2 px-3 py-6 text-center">
            {status?.can_show_more ? (
                <>
                    <Text size="xs" variant="muted" render={<span />}>
                        {`All caught up for today. ${waitingSuggestionsText(status.waiting)}`}
                    </Text>
                    <Button
                        variant="outline"
                        size="sm"
                        loading={showingMore}
                        onClick={() => showMore(placement)}
                        data-attr="warehouse-suggestions-show-more"
                    >
                        Show more
                    </Button>
                </>
            ) : (
                <Text size="xs" variant="muted" render={<span />}>
                    All caught up. New suggestions appear as usage changes.
                </Text>
            )}
        </div>
    )
}
