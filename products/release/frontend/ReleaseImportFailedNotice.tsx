import { useActions, useValues } from 'kea'

import { IconWarning } from '@posthog/icons'
import { Button, Item, ItemActions, ItemContent, ItemDescription, ItemMedia, ItemTitle } from '@posthog/quill'

import { releaseImportLogic } from './releaseImportLogic'

export function ReleaseImportFailedNotice(): JSX.Element | null {
    const { autoImportState, showAutoImport } = useValues(releaseImportLogic)
    const { runAutoImport } = useActions(releaseImportLogic)

    if (autoImportState !== 'failed' || showAutoImport) {
        return null
    }
    return (
        <Item variant="outline" tone="warning" size="sm" data-attr="release-import-failed">
            <ItemMedia variant="icon">
                <IconWarning />
            </ItemMedia>
            <ItemContent>
                <ItemTitle>Your existing flags could not be imported</ItemTitle>
                <ItemDescription>Check your connection, then try again.</ItemDescription>
            </ItemContent>
            <ItemActions>
                <Button size="sm" variant="outline" onClick={runAutoImport} data-attr="release-import-failed-retry">
                    Try again
                </Button>
            </ItemActions>
        </Item>
    )
}
