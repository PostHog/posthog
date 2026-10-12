import { useValues } from 'kea'

import { CommandCenterComposerTile } from './CommandCenterComposerTile'
import { CommandCenterEmptyTile } from './CommandCenterEmptyTile'
import { commandCenterSceneLogic } from './commandCenterSceneLogic'
import { CommandCenterSessionTile } from './CommandCenterSessionTile'

export interface CommandCenterTileProps {
    index: number
}

export function CommandCenterTile({ index }: CommandCenterTileProps): JSX.Element {
    const { cells, composingIndex } = useValues(commandCenterSceneLogic)
    const sessionId = cells[index]

    return (
        <section
            aria-label={`Tile ${index + 1}`}
            className="flex min-h-0 min-w-0 flex-col overflow-hidden rounded-md border border-[var(--border)]"
        >
            {composingIndex === index ? (
                <CommandCenterComposerTile index={index} />
            ) : sessionId ? (
                <CommandCenterSessionTile index={index} sessionId={sessionId} />
            ) : (
                <CommandCenterEmptyTile index={index} />
            )}
        </section>
    )
}
