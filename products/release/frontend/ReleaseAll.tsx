import type { ColumnDef } from '@tanstack/react-table'
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useCallback, useEffect, useRef } from 'react'

import { IconList } from '@posthog/icons'
import { Badge, Button, Card, DataTable, Input, Skeleton, Text } from '@posthog/quill'

import { TZLabel } from 'lib/components/TZLabel'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { SceneExport } from 'scenes/sceneTypes'

import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'
import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { FileSystemIconType } from '~/queries/schema/schema-general'

import { ReleaseAllFilter, ReleaseAllRow, ReleaseAllType, releaseAllLogic } from './releaseAllLogic'
import { releaseLogic } from './releaseLogic'
import { ReleasesGate } from './ReleasesGate'

export const scene: SceneExport = {
    component: ReleaseAll,
    logic: releaseLogic,
}

const LOOKAHEAD = '600px'

const TYPE_LABEL: Record<ReleaseAllType, string> = {
    release: 'Release',
    feature_flag: 'Feature flag',
    experiment: 'Experiment',
    early_access_feature: 'Early access',
}

const TYPE_ICON: Record<ReleaseAllType, string> = {
    release: 'feature_flag',
    feature_flag: 'feature_flag',
    experiment: 'experiment',
    early_access_feature: 'early_access_feature',
}

const FILTERS: [ReleaseAllFilter, string][] = [
    ['all', 'All'],
    ['release', 'Releases'],
    ['feature_flag', 'Feature flags'],
    ['experiment', 'Experiments'],
    ['early_access_feature', 'Early access'],
]

const COLUMNS: ColumnDef<ReleaseAllRow>[] = [
    {
        id: 'name',
        header: 'Name',
        accessorKey: 'name',
        meta: { expand: true },
        enableSorting: false,
        cell: ({ row }) => (
            <LinkPrimitive
                to={row.original.href}
                className="flex min-w-0 items-center gap-2 text-foreground"
                data-attr="release-all-name"
            >
                <span className="flex size-4 shrink-0 items-center justify-center [&_svg]:size-4">
                    {iconForType(TYPE_ICON[row.original.type] as FileSystemIconType)}
                </span>
                <span className="truncate">{row.original.name}</span>
            </LinkPrimitive>
        ),
    },
    {
        id: 'type',
        header: 'Type',
        enableSorting: false,
        cell: ({ row }) => <Badge variant="default">{TYPE_LABEL[row.original.type]}</Badge>,
    },
    {
        id: 'status',
        header: 'Status',
        enableSorting: false,
        cell: ({ row }) => <Text size="xs">{row.original.status}</Text>,
    },
    {
        id: 'created',
        header: 'Created',
        enableSorting: false,
        cell: ({ row }) =>
            row.original.createdAt ? <TZLabel time={row.original.createdAt} formatDate="D MMM YYYY" /> : null,
    },
]

function useLoadMoreSentinel(onVisible: () => void, watch: unknown): (node: Element | null) => void {
    const observer = useRef<IntersectionObserver | null>(null)
    const target = useRef<Element | null>(null)
    const callback = useRef(onVisible)
    callback.current = onVisible

    const sentinel = useCallback((node: Element | null) => {
        observer.current?.disconnect()
        target.current = node
        if (!node) {
            return
        }
        observer.current = new IntersectionObserver(
            (entries) => entries.some((entry) => entry.isIntersecting) && callback.current(),
            { rootMargin: LOOKAHEAD }
        )
        observer.current.observe(node)
    }, [])

    useEffect(() => {
        const node = target.current
        if (node && observer.current) {
            observer.current.unobserve(node)
            observer.current.observe(node)
        }
    }, [watch])

    useEffect(() => () => observer.current?.disconnect(), [])

    return sentinel
}

function ReleaseAllContent(): JSX.Element {
    const { displayRows, filter, search, hasMore, loading, showSkeleton, failedTypes } = useValues(releaseAllLogic)
    const { setFilter, setSearch, loadMore, retry } = useActions(releaseAllLogic)
    const sentinel = useLoadMoreSentinel(loadMore, loading)

    return (
        <SceneContent>
            <SceneTitleSection
                name="View all"
                description="Every release, feature flag, experiment and early access feature, newest first."
                resourceType={{ type: 'release', forceIcon: <IconList /> }}
            />
            <div data-quill className="flex flex-col gap-3">
                <div className="flex flex-wrap items-center gap-2">
                    <Input
                        className="max-w-64"
                        placeholder="Search by name or key"
                        aria-label="Search releases, flags, experiments and early access features"
                        value={search}
                        onChange={(event) => setSearch(event.target.value)}
                        data-attr="release-all-search"
                    />
                    {FILTERS.map(([value, label]) => (
                        <Button
                            key={value}
                            size="sm"
                            variant={filter === value ? 'default' : 'outline'}
                            onClick={() => setFilter(value)}
                            data-attr={`release-all-filter-${value}`}
                        >
                            {label}
                        </Button>
                    ))}
                </div>
                {failedTypes.length > 0 && (
                    <div className="flex items-center gap-2" data-attr="release-all-failed">
                        <Text size="xs" variant="muted">
                            {`Some ${failedTypes.map((type) => TYPE_LABEL[type].toLowerCase()).join(' and ')} items could not load.`}
                        </Text>
                        <Button size="sm" variant="outline" onClick={() => retry()} data-attr="release-all-retry">
                            Try again
                        </Button>
                    </div>
                )}
                {showSkeleton ? (
                    <div className="flex flex-col gap-2" data-attr="release-all-loading">
                        {Array.from({ length: 8 }, (_, index) => (
                            <Skeleton key={index} className="h-9 w-full" />
                        ))}
                    </div>
                ) : (
                    <Card size="sm" flush className="pt-0" data-attr="release-all-table">
                        <DataTable
                            columns={COLUMNS}
                            data={displayRows}
                            fullWidth
                            size="sm"
                            getRowId={(row) => row.key}
                            onRowClick={(row) => router.actions.push(row.href)}
                            empty={
                                <Text size="xs" variant="muted">
                                    {search.trim() ? 'Nothing matches that search.' : 'Nothing here yet.'}
                                </Text>
                            }
                        />
                        {hasMore && <div ref={sentinel} />}
                        {loading && displayRows.length > 0 && <Skeleton className="m-2 h-9" />}
                    </Card>
                )}
            </div>
        </SceneContent>
    )
}

export function ReleaseAll(): JSX.Element {
    return (
        <ReleasesGate>
            <ReleaseAllContent />
        </ReleasesGate>
    )
}
