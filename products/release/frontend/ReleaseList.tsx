import type { ColumnDef } from '@tanstack/react-table'
import { useValues } from 'kea'
import { router } from 'kea-router'

import { IconFlag } from '@posthog/icons'
import { Badge, Button, Card, DataTable, Skeleton, Text } from '@posthog/quill'

import { TZLabel } from 'lib/components/TZLabel'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { NewReleaseButton, NewReleaseDialog, ReleaseFilters } from './ReleaseFilters'
import { ReleaseLoadError } from './ReleaseLoadError'
import { releaseLogic } from './releaseLogic'
import { ReleasePartialLoadWarning } from './ReleasePartialLoadWarning'
import { ReleasesGate } from './ReleasesGate'
import { ReleaseRow, STAGE_LABEL, STAGE_TONE } from './releaseUtils'

export const scene: SceneExport = {
    component: ReleaseList,
    logic: releaseLogic,
}

const COLUMNS: ColumnDef<ReleaseRow>[] = [
    {
        id: 'name',
        header: 'Release',
        accessorKey: 'name',
        minSize: 256,
        meta: { expand: true },
        cell: ({ row }) => (
            <div className="flex min-w-0 flex-col items-start">
                <Button
                    variant="link-foreground"
                    size="sm"
                    nativeButton={false}
                    left
                    render={<LinkPrimitive to={urls.release(row.original.id)} />}
                    className="min-w-0 max-w-full"
                    data-attr="release-table-name"
                >
                    <span className="truncate">{row.original.name}</span>
                </Button>
                <Text size="xs" variant="muted" className="px-2">
                    {row.original.status}
                </Text>
            </div>
        ),
    },
    {
        id: 'stage',
        header: 'Stage',
        accessorKey: 'stage',
        cell: ({ row }) => <Badge variant={STAGE_TONE[row.original.stage]}>{STAGE_LABEL[row.original.stage]}</Badge>,
    },
    {
        id: 'audience',
        header: 'Who gets it',
        enableSorting: false,
        cell: ({ row }) => (
            <Text size="xs" variant="muted">
                {row.original.audience}
            </Text>
        ),
    },
    {
        id: 'owner',
        header: 'Owner',
        accessorFn: (row) => row.owner?.first_name ?? '',
        cell: ({ row }) => (
            <Text size="xs" variant={row.original.owner ? 'default' : 'muted'}>
                {row.original.owner?.first_name ?? 'No owner'}
            </Text>
        ),
    },
    {
        id: 'nextDate',
        header: 'Next date',
        accessorFn: (row) => row.nextDate ?? '9999',
        cell: ({ row }) =>
            row.original.nextDate ? (
                <Text size="xs" variant="muted" render={<span />}>
                    <TZLabel time={row.original.nextDate} formatDate="D MMM YYYY" formatTime="" />
                </Text>
            ) : (
                <Text size="xs" variant="muted">
                    –
                </Text>
            ),
    },
    {
        id: 'nextStep',
        header: 'Next step',
        enableSorting: false,
        meta: { align: 'right' },
        cell: ({ row }) =>
            row.original.needsDecision && row.original.nextStep ? (
                <Button
                    variant="outline"
                    size="sm"
                    nativeButton={false}
                    render={<LinkPrimitive to={row.original.nextStep.to ?? urls.release(row.original.id)} />}
                    tooltip={row.original.nextStep.title}
                    data-attr="release-next-step"
                >
                    {row.original.nextStep.label ?? row.original.nextStep.title}
                </Button>
            ) : (
                <Text size="xs" variant="muted">
                    {row.original.nextStep?.title ?? 'Nothing to do'}
                </Text>
            ),
    },
]

function ReleaseListContent(): JSX.Element {
    const { filteredRows, dataLoading, loadFailed } = useValues(releaseLogic)

    return (
        <SceneContent>
            <SceneTitleSection
                name="Releases"
                description="Each release with its stage, its audience and its next step."
                resourceType={{ type: 'release', forceIcon: <IconFlag /> }}
                actions={
                    <div data-quill>
                        <NewReleaseButton />
                    </div>
                }
            />
            <div data-quill className="flex flex-col gap-3">
                <ReleaseFilters />
                <ReleasePartialLoadWarning />
                {loadFailed ? (
                    <ReleaseLoadError title="Releases could not load" />
                ) : dataLoading && !filteredRows.length ? (
                    <Skeleton className="h-64 w-full" />
                ) : (
                    <Card size="sm" flush className="pt-0" data-attr="release-table">
                        <DataTable
                            columns={COLUMNS}
                            pageSize={50}
                            data={filteredRows}
                            fullWidth
                            size="sm"
                            onRowClick={(row) => router.actions.push(urls.release(row.id))}
                            empty={
                                <Text size="xs" variant="muted">
                                    No release matches these filters.
                                </Text>
                            }
                        />
                    </Card>
                )}
                <NewReleaseDialog />
            </div>
        </SceneContent>
    )
}

export function ReleaseList(): JSX.Element {
    return (
        <ReleasesGate>
            <ReleaseListContent />
        </ReleasesGate>
    )
}
