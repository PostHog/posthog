import { useActions, useValues } from 'kea'

import { IconWarning } from '@posthog/icons'
import { Button, Item, ItemActions, ItemContent, ItemDescription, ItemMedia, ItemTitle } from '@posthog/quill'

import { releaseLogic } from './releaseLogic'

export function ReleasePartialLoadWarning(): JSX.Element | null {
    const { partialLoadFailed, loadFailed } = useValues(releaseLogic)
    const { reload } = useActions(releaseLogic)

    if (!partialLoadFailed || loadFailed) {
        return null
    }
    return (
        <Item variant="outline" tone="warning" size="sm" data-attr="release-partial-load">
            <ItemMedia variant="icon">
                <IconWarning />
            </ItemMedia>
            <ItemContent>
                <ItemTitle>Some linked details are missing</ItemTitle>
                <ItemDescription>
                    Some experiments, early access or schedules could not load or are hidden from you, so stages and
                    next steps can be incomplete.
                </ItemDescription>
            </ItemContent>
            <ItemActions>
                <Button size="sm" variant="outline" onClick={() => reload(true)}>
                    Try again
                </Button>
            </ItemActions>
        </Item>
    )
}
