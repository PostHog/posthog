import { useValues } from 'kea'

import { Table, TableBody, TableEmpty, TableHead, TableHeader, TableRow, Text } from '@posthog/quill'

import { SpaceLoopRow } from './SpaceLoopRow'
import { spaceLoopsLogic } from './spaceLoopsLogic'

export function SpaceLoopsTable({ id }: { id: string }): JSX.Element {
    const { filteredLoops } = useValues(spaceLoopsLogic({ id }))

    return (
        <Table fullWidth>
            <TableHeader>
                <TableRow>
                    <TableHead expand>Loop</TableHead>
                    <TableHead className="hidden @2xl:table-cell">Trigger</TableHead>
                    <TableHead className="hidden @xl:table-cell">Last run</TableHead>
                    <TableHead>
                        <span className="sr-only">Active</span>
                    </TableHead>
                </TableRow>
            </TableHeader>
            {filteredLoops.length ? (
                <TableBody>
                    {filteredLoops.map((loop) => (
                        <SpaceLoopRow key={loop.id} spaceId={id} loop={loop} />
                    ))}
                </TableBody>
            ) : (
                <TableEmpty>
                    <Text size="sm" variant="muted" className="py-6">
                        No loops match your filters.
                    </Text>
                </TableEmpty>
            )}
        </Table>
    )
}
