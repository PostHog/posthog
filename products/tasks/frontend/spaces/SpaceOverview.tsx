import { useActions, useValues } from 'kea'

import {
    IconPlus,
    IconPin,
    IconPinFilled,
    IconTrash,
    IconPalette,
    IconDashboard,
    IconDocument,
    IconFolder,
} from '@posthog/icons'
import {
    Button,
    Card,
    CardHeader,
    CardTitle,
    CardDescription,
    CardContent,
    Heading,
    Text,
    Skeleton,
    Empty,
    EmptyHeader,
    EmptyTitle,
    EmptyDescription,
    Select,
    SelectTrigger,
    SelectValue,
    SelectContent,
    SelectItem,
    Table,
    TableHeader,
    TableRow,
    TableHead,
    TableBody,
    TableCell,
} from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { splitPath } from '~/layout/panel-layout/ProjectTree/utils'

import { SpaceCanvasCard } from './SpaceCanvasCard'
import { SpaceCanvasPreview } from './SpaceCanvasPreview'
import { SpaceResourcePicker } from './SpaceResourcePicker'
import { spaceResourcesLogic } from './spaceResourcesLogic'
import { spaceSceneLogic } from './spaceSceneLogic'

export function SpaceOverview({ id }: { id: string }): JSX.Element {
    const { config, configLoading, configUnavailable, filesLoading, filesUnavailable, fileById } = useValues(
        spaceResourcesLogic({ id })
    )
    const { loadConfig, loadFiles, setPickerOpen, togglePinned, removeFile, featureCanvas } = useActions(
        spaceResourcesLogic({ id })
    )
    const { canvases, canvasesLoading, canvasesUnavailable } = useValues(spaceSceneLogic({ id }))
    const { loadCanvases } = useActions(spaceSceneLogic({ id }))
    if (!config && configLoading) {
        return (
            <div className="flex flex-col gap-4 pt-4" aria-busy>
                <Skeleton className="h-64 w-full" />
                <Skeleton className="h-40 w-full" />
            </div>
        )
    }
    if (!config || configUnavailable) {
        return (
            <Empty>
                <EmptyHeader>
                    <EmptyTitle>This space’s files didn’t load</EmptyTitle>
                    <EmptyDescription>Try again to see its featured canvas and analysis.</EmptyDescription>
                </EmptyHeader>
                <Button loading={configLoading} onClick={() => loadConfig()}>
                    Try again
                </Button>
            </Empty>
        )
    }
    const featured = canvases?.find((canvas) => canvas.id === config.featured_canvas)
    const pinned = config.resources.filter((item) => item.pinned)
    return (
        <div className="@container/space-overview flex flex-col gap-6 pt-4" data-quill>
            <div className="flex flex-wrap items-start justify-between gap-3">
                <Text variant="muted">A shared home for your dashboards, insights, and canvases.</Text>
                <div className="flex flex-wrap gap-2">
                    <Button variant="outline" nativeButton={false} render={<LinkPrimitive to={urls.canvasNew(id)} />}>
                        <IconPalette />
                        New canvas
                    </Button>
                    <Button variant="primary" onClick={() => setPickerOpen(true)} loading={configLoading}>
                        <IconPlus />
                        Add to space
                    </Button>
                </div>
            </div>
            <Card size="sm">
                <CardHeader>
                    <div className="flex flex-wrap items-center justify-between gap-3">
                        <div className="flex flex-col gap-1">
                            <CardTitle>Featured canvas</CardTitle>
                            <CardDescription>
                                Give this space a starting point with context, charts, and notes.
                            </CardDescription>
                        </div>
                        <Select
                            items={[
                                { value: 'none', label: 'Choose later' },
                                ...(canvases ?? []).map((canvas) => ({ value: canvas.id, label: canvas.name })),
                            ]}
                            value={config.featured_canvas ?? 'none'}
                            onValueChange={(value) => featureCanvas(value === 'none' ? null : value)}
                            disabled={configLoading || canvasesLoading || canvasesUnavailable}
                        >
                            <SelectTrigger aria-label="Featured canvas" className="w-56 max-w-full">
                                <SelectValue placeholder="Choose a canvas" />
                            </SelectTrigger>
                            <SelectContent>
                                <SelectItem value="none">Choose later</SelectItem>
                                {canvases?.map((canvas) => (
                                    <SelectItem key={canvas.id} value={canvas.id}>
                                        {canvas.name}
                                    </SelectItem>
                                ))}
                            </SelectContent>
                        </Select>
                    </div>
                </CardHeader>
                <CardContent>
                    {canvasesLoading && !canvases ? (
                        <Skeleton className="h-36 w-full" />
                    ) : canvasesUnavailable ? (
                        <Button loading={canvasesLoading} onClick={() => loadCanvases()}>
                            Try loading canvases again
                        </Button>
                    ) : featured ? (
                        <div className="flex flex-col gap-3">
                            {featured.published_build_id ? (
                                <SpaceCanvasPreview spaceId={id} canvas={featured} />
                            ) : (
                                <Text size="xs" variant="muted">
                                    Open this canvas to publish it and show its preview here.
                                </Text>
                            )}
                            <div className="flex flex-wrap items-center justify-between gap-2">
                                <Heading size="sm">{featured.name}</Heading>
                                <Button
                                    variant="outline"
                                    nativeButton={false}
                                    render={<LinkPrimitive to={urls.canvasDetail(featured.id)} />}
                                >
                                    Open canvas
                                </Button>
                            </div>
                            {featured.description && <Text variant="muted">{featured.description}</Text>}
                        </div>
                    ) : (
                        <Empty>
                            <EmptyHeader>
                                <EmptyTitle>
                                    {config.featured_canvas
                                        ? 'Featured canvas unavailable'
                                        : 'Set the scene for this space'}
                                </EmptyTitle>
                                <EmptyDescription>
                                    Choose a canvas above or create one for the overview, goals, and context your team
                                    needs.
                                </EmptyDescription>
                            </EmptyHeader>
                            <Button
                                variant="outline"
                                nativeButton={false}
                                render={<LinkPrimitive to={urls.canvasNew(id)} />}
                            >
                                Create a canvas
                            </Button>
                        </Empty>
                    )}
                </CardContent>
            </Card>
            {filesUnavailable && (
                <div className="flex flex-wrap items-center gap-2">
                    <Text>Some file details didn’t load.</Text>
                    <Button loading={filesLoading} onClick={() => loadFiles()}>
                        Try again
                    </Button>
                </div>
            )}
            {pinned.length > 0 && (
                <section className="flex flex-col gap-3" aria-label="Pinned analysis">
                    <Heading size="sm">Pinned analysis</Heading>
                    <div className="grid grid-cols-1 gap-3 @min-[44rem]/space-overview:grid-cols-2">
                        {pinned.map((item) => {
                            const file = fileById[item.file_id]
                            return (
                                <Card key={item.file_id} size="sm">
                                    <CardHeader>
                                        <CardTitle className="truncate">
                                            {file
                                                ? splitPath(file.path).at(-1)
                                                : filesLoading
                                                  ? 'Loading…'
                                                  : 'Unavailable file'}
                                        </CardTitle>
                                        <CardDescription>{file?.type ?? 'Access may have changed'}</CardDescription>
                                    </CardHeader>
                                    <CardContent>
                                        <div className="flex flex-wrap gap-2">
                                            {file?.href && (
                                                <Button
                                                    variant="outline"
                                                    nativeButton={false}
                                                    render={<LinkPrimitive to={file.href} />}
                                                >
                                                    Open {file.type}
                                                </Button>
                                            )}
                                            <Button
                                                variant="default"
                                                loading={configLoading}
                                                onClick={() => togglePinned(item.file_id)}
                                            >
                                                <IconPinFilled />
                                                Unpin
                                            </Button>
                                        </div>
                                    </CardContent>
                                </Card>
                            )
                        })}
                    </div>
                </section>
            )}
            <section className="flex flex-col gap-3" aria-label="Files in this space">
                <Heading size="sm">Files in this space</Heading>
                {config.resources.length ? (
                    <Table fullWidth>
                        <TableHeader>
                            <TableRow>
                                <TableHead expand>Name</TableHead>
                                <TableHead>Type</TableHead>
                                <TableHead>
                                    <span className="sr-only">Actions</span>
                                </TableHead>
                            </TableRow>
                        </TableHeader>
                        <TableBody>
                            {config.resources.map((item) => {
                                const file = fileById[item.file_id]
                                const Icon =
                                    file?.type === 'dashboard'
                                        ? IconDashboard
                                        : file?.type === 'folder'
                                          ? IconFolder
                                          : IconDocument
                                return (
                                    <TableRow key={item.file_id}>
                                        <TableCell expand>
                                            <div className="flex min-w-0 items-center gap-2">
                                                <Icon className="size-4 shrink-0" />
                                                {file?.href ? (
                                                    <LinkPrimitive to={file.href} className="truncate">
                                                        {splitPath(file.path).at(-1)}
                                                    </LinkPrimitive>
                                                ) : (
                                                    <Text variant="muted">
                                                        {filesLoading ? 'Loading…' : 'Unavailable file'}
                                                    </Text>
                                                )}
                                            </div>
                                        </TableCell>
                                        <TableCell>
                                            <Text size="xs" variant="muted">
                                                {file?.type}
                                            </Text>
                                        </TableCell>
                                        <TableCell>
                                            <div className="flex gap-1">
                                                <Button
                                                    size="icon-sm"
                                                    variant="default"
                                                    aria-label={item.pinned ? 'Unpin resource' : 'Pin resource'}
                                                    loading={configLoading}
                                                    disabled={!file}
                                                    onClick={() => togglePinned(item.file_id)}
                                                >
                                                    {item.pinned ? <IconPinFilled /> : <IconPin />}
                                                </Button>
                                                <Button
                                                    size="icon-sm"
                                                    variant="default"
                                                    aria-label="Remove from space"
                                                    loading={configLoading}
                                                    onClick={() => removeFile(item.file_id)}
                                                >
                                                    <IconTrash />
                                                </Button>
                                            </div>
                                        </TableCell>
                                    </TableRow>
                                )
                            })}
                        </TableBody>
                    </Table>
                ) : (
                    <Empty>
                        <EmptyHeader>
                            <EmptyTitle>Bring your analysis together</EmptyTitle>
                            <EmptyDescription>
                                Add existing dashboards, insights, notebooks, or folders. Pin the ones people should
                                start with.
                            </EmptyDescription>
                        </EmptyHeader>
                        <Button variant="outline" onClick={() => setPickerOpen(true)}>
                            Add your first resource
                        </Button>
                    </Empty>
                )}
            </section>
            {!!canvases?.some((canvas) => canvas.id !== featured?.id) && (
                <section className="flex flex-col gap-3">
                    <Heading size="sm">Canvases</Heading>
                    <div className="grid grid-cols-1 gap-3 @min-[44rem]/space-overview:grid-cols-3">
                        {canvases
                            .filter((canvas) => canvas.id !== featured?.id)
                            .map((canvas) => (
                                <SpaceCanvasCard key={canvas.id} spaceId={id} canvas={canvas} />
                            ))}
                    </div>
                </section>
            )}
            <SpaceResourcePicker id={id} />
        </div>
    )
}
