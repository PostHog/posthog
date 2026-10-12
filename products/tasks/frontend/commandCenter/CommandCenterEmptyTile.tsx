import { useActions, useValues } from 'kea'

import { IconPlus } from '@posthog/icons'
import {
    Button,
    Combobox,
    ComboboxContent,
    ComboboxEmpty,
    ComboboxInput,
    ComboboxItem,
    ComboboxList,
    Empty,
    EmptyContent,
    EmptyDescription,
    EmptyHeader,
    EmptyTitle,
} from '@posthog/quill'

import { commandCenterSceneLogic } from './commandCenterSceneLogic'

export interface CommandCenterEmptyTileProps {
    index: number
}

export function CommandCenterEmptyTile({ index }: CommandCenterEmptyTileProps): JSX.Element {
    const { pickableSessionIds, sessionTitles, recentTasksLoading } = useValues(commandCenterSceneLogic)
    const { placeSession, startComposing } = useActions(commandCenterSceneLogic)
    const resolving = recentTasksLoading && pickableSessionIds.length === 0

    return (
        <Empty className="h-full">
            <EmptyHeader>
                <EmptyTitle>Empty tile</EmptyTitle>
                <EmptyDescription>Open a recent chat here, or start a new one.</EmptyDescription>
            </EmptyHeader>
            <EmptyContent>
                <Combobox
                    items={pickableSessionIds}
                    value={null}
                    onValueChange={(sessionId: string | null) => {
                        if (sessionId) {
                            placeSession(index, sessionId, 'picked')
                        }
                    }}
                    itemToStringLabel={(sessionId: string) => sessionTitles.get(sessionId) ?? ''}
                    disabled={resolving}
                >
                    <ComboboxInput
                        className="w-64 max-w-full"
                        placeholder={resolving ? 'Loading recent chats…' : 'Search recent chats'}
                        aria-label="Search recent chats"
                        disabled={resolving}
                        data-attr="command-center-tile-search"
                    />
                    <ComboboxContent>
                        <ComboboxEmpty>
                            {pickableSessionIds.length > 0
                                ? 'No recent chats match that search.'
                                : 'No recent chats to open. Start a new one.'}
                        </ComboboxEmpty>
                        <ComboboxList>
                            {(sessionId: string) => (
                                <ComboboxItem key={sessionId} value={sessionId}>
                                    <span className="truncate">{sessionTitles.get(sessionId)}</span>
                                </ComboboxItem>
                            )}
                        </ComboboxList>
                    </ComboboxContent>
                </Combobox>
                <Button
                    variant="outline"
                    onClick={() => startComposing(index)}
                    data-attr="command-center-tile-new-chat"
                >
                    <IconPlus />
                    New chat
                </Button>
            </EmptyContent>
        </Empty>
    )
}
