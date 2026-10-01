import { useValues } from 'kea'

import { ItemGroup, Text } from '@posthog/quill'

import { SpaceLoopRow } from './SpaceLoopRow'
import { spaceLoopsLogic } from './spaceLoopsLogic'

export function SpaceLoopsList({ id }: { id: string }): JSX.Element {
    const { filteredLoops } = useValues(spaceLoopsLogic({ id }))

    if (!filteredLoops.length) {
        return (
            <Text size="xs" variant="muted" className="px-0.5 py-2">
                No loops match your filters.
            </Text>
        )
    }
    return (
        <ItemGroup combined>
            {filteredLoops.map((loop) => (
                <SpaceLoopRow key={loop.id} spaceId={id} loop={loop} />
            ))}
        </ItemGroup>
    )
}
