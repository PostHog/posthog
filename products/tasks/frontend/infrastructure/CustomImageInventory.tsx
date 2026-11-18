import { Badge, Button, Card, Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@posthog/quill'

import { Sources, customState, fresh, labels, variants } from './infrastructureTypes'

export function CustomImageInventory({
    sources,
    onInspect,
    inspecting,
}: {
    sources: Sources
    onInspect: (id: string) => void
    inspecting?: string | null
}): JSX.Element {
    const data = sources.custom?.data
    const base = fresh(sources.vm) ? sources.vm?.data?.reference : undefined
    return (
        <Card className="inventory">
            <div className="section-title">
                <div>
                    <h2>Custom image fan-out</h2>
                    <p className="muted">Automatic refresh checks run every 10 minutes, up to 10 images per sweep.</p>
                </div>
            </div>
            {!data ? (
                <p className="empty-state">
                    {sources.custom?.status === 'error'
                        ? 'Inventory unavailable. Refresh to retry.'
                        : 'Loading custom images…'}
                </p>
            ) : (
                <>
                    {(!fresh(sources.custom) || !base) && (
                        <p className="alert">
                            Freshness is unverified until both inventory and the VM registry are available.
                        </p>
                    )}
                    {data.truncated && (
                        <p className="alert">
                            Showing the first {data.limit} images. This is a partial inventory; fleet completion is
                            unverified.
                        </p>
                    )}
                    {data.images.length === 0 ? (
                        <p className="empty-state">No active custom images in this region.</p>
                    ) : (
                        <Table>
                            <TableHeader>
                                <TableRow>
                                    <TableHead>Image / project</TableHead>
                                    <TableHead>Published</TableHead>
                                    <TableHead>Refresh</TableHead>
                                    <TableHead>Base → target</TableHead>
                                    <TableHead>Evidence</TableHead>
                                </TableRow>
                            </TableHeader>
                            <TableBody>
                                {data.images.map((image) => {
                                    const state = fresh(sources.custom) ? customState(image, base) : 'unknown'
                                    const staleServing =
                                        fresh(sources.custom) &&
                                        image.status === 'ready' &&
                                        image.has_published_image &&
                                        !!base &&
                                        image.base_image_reference !== base
                                    return (
                                        <TableRow key={image.id}>
                                            <TableCell>
                                                <code title={image.id}>{image.id.slice(0, 8)}</code>
                                                <div className="muted">Project {image.team_id}</div>
                                            </TableCell>
                                            <TableCell>
                                                <span>{image.has_published_image ? `v${image.version}` : 'None'}</span>
                                                <div className="muted">
                                                    {staleServing ? 'Serving older base' : image.status}
                                                </div>
                                            </TableCell>
                                            <TableCell>
                                                <Badge variant={variants[state]}>
                                                    {state === 'failed' && staleServing
                                                        ? 'Refresh failed'
                                                        : labels[state]}
                                                </Badge>
                                            </TableCell>
                                            <TableCell className="digest">
                                                <code title={image.base_image_reference || ''}>
                                                    {image.base_image_reference?.split('@')[1]?.slice(0, 19) ||
                                                        'Unrecorded'}
                                                </code>
                                                <div>
                                                    <code title={image.base_image_refresh_reference || ''}>
                                                        {image.base_image_refresh_reference
                                                            ? `→ ${image.base_image_refresh_reference.split('@')[1]?.slice(0, 19)}`
                                                            : 'No pending target'}
                                                    </code>
                                                </div>
                                            </TableCell>
                                            <TableCell>
                                                <Button
                                                    variant="outline"
                                                    size="sm"
                                                    disabled={!!inspecting}
                                                    loading={inspecting === image.id}
                                                    onClick={() => onInspect(image.id)}
                                                    data-attr="infra-inspect-image"
                                                >
                                                    Inspect
                                                </Button>
                                            </TableCell>
                                        </TableRow>
                                    )
                                })}
                            </TableBody>
                        </Table>
                    )}
                </>
            )}
        </Card>
    )
}
