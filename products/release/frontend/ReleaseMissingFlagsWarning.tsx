import { useActions, useValues } from 'kea'

import { IconWarning } from '@posthog/icons'
import { Button, Item, ItemActions, ItemContent, ItemDescription, ItemMedia, ItemTitle } from '@posthog/quill'

import { releaseLogic } from './releaseLogic'
import { ReleaseRow } from './releaseUtils'

export function ReleaseMissingFlagsWarning({ row }: { row: ReleaseRow }): JSX.Element | null {
    const { canEditReleases } = useValues(releaseLogic)
    const { updateRelease } = useActions(releaseLogic)
    const count = row.missingFlagIds.length

    if (!count) {
        return null
    }
    return (
        <Item variant="outline" tone="warning" size="sm" data-attr="release-missing-flags">
            <ItemMedia variant="icon">
                <IconWarning />
            </ItemMedia>
            <ItemContent>
                <ItemTitle>
                    {count === 1 ? 'A linked flag was deleted' : `${count} linked flags were deleted`}
                </ItemTitle>
                <ItemDescription>
                    {count === 1
                        ? 'Remove it, or link the flag that replaced it.'
                        : 'Remove them, or link the flags that replaced them.'}
                </ItemDescription>
            </ItemContent>
            {canEditReleases && (
                <ItemActions>
                    <Button
                        size="sm"
                        variant="outline"
                        onClick={() => updateRelease(row.id, { feature_flag_ids: row.flags.map((flag) => flag.id) })}
                    >
                        Remove
                    </Button>
                </ItemActions>
            )}
        </Item>
    )
}
