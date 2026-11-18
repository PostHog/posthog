import { Card, DataTable, Text } from '@posthog/quill'
import type { DataTableProps } from '@posthog/quill'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonTable } from 'lib/lemon-ui/LemonTable'

import type {
    ExperimentSetupLibActivityApi,
    ExperimentSetupSdkLibApi,
    ExperimentSetupSdkProfileSectionApi,
} from 'products/experiments/frontend/generated/api.schemas'

import { SetupContextSection } from '../SetupContextSection'
import { SetupFactsTable } from '../SetupFactsTable'
import { formatCount, formatShare, formatTimestamp, formatYesNo } from '../setupInspectorUtils'

const NO_FLAG_CALLS = 'No multivariate flag calls in the window.'

const SDK_LIB_COLUMNS: DataTableProps<ExperimentSetupSdkLibApi, unknown>['columns'] = [
    { id: 'sdk', header: 'SDK', accessorFn: (lib) => lib.lib ?? 'unknown' },
    { id: 'category', header: 'Category', accessorFn: (lib) => lib.category },
    {
        id: 'calls',
        header: 'Calls',
        meta: { align: 'right' },
        accessorFn: (lib) => lib.calls,
        cell: ({ row }) => formatCount(row.original.calls),
    },
    {
        id: 'distinct_ids',
        header: 'Distinct IDs',
        meta: { align: 'right' },
        accessorFn: (lib) => lib.distinct_ids,
        cell: ({ row }) => formatCount(row.original.distinct_ids),
    },
    {
        id: 'local',
        header: 'Evaluated locally',
        meta: { align: 'right' },
        accessorFn: (lib) => lib.locally_evaluated_share,
        cell: ({ row }) => formatShare(row.original.locally_evaluated_share),
    },
    {
        id: 'anonymous',
        header: 'Anonymous',
        meta: { align: 'right' },
        accessorFn: (lib) => lib.anonymous_share,
        cell: ({ row }) => formatShare(row.original.anonymous_share),
    },
    {
        id: 'device_id',
        header: 'Device ID',
        meta: { align: 'right' },
        accessorFn: (lib) => lib.device_id_share,
        cell: ({ row }) => formatShare(row.original.device_id_share),
    },
]

const LIB_ACTIVITY_COLUMNS: DataTableProps<ExperimentSetupLibActivityApi, unknown>['columns'] = [
    { id: 'sdk', header: 'SDK', accessorFn: (lib) => lib.lib ?? 'unknown' },
    { id: 'category', header: 'Category', accessorFn: (lib) => lib.category },
    {
        id: 'events',
        header: 'Events',
        meta: { align: 'right' },
        accessorFn: (lib) => lib.events,
        cell: ({ row }) => formatCount(row.original.events),
    },
    {
        id: 'distinct_ids',
        header: 'Distinct IDs',
        meta: { align: 'right' },
        accessorFn: (lib) => lib.distinct_ids,
        cell: ({ row }) => formatCount(row.original.distinct_ids),
    },
]

function QuillSdkTable<T extends { lib?: string | null }>({
    columns,
    data,
    empty,
}: {
    columns: DataTableProps<T, unknown>['columns']
    data: T[]
    empty?: string
}): JSX.Element {
    return (
        <Card size="sm" flush className="pt-0">
            <DataTable
                columns={columns}
                data={data}
                fullWidth
                size="sm"
                getRowId={(lib, index) => lib.lib ?? `unknown-${index}`}
                empty={
                    empty ? (
                        <Text size="xs" variant="muted">
                            {empty}
                        </Text>
                    ) : undefined
                }
            />
        </Card>
    )
}

export function SdkProfileSection({
    section,
    skippedMessage,
}: {
    section: ExperimentSetupSdkProfileSectionApi
    /** Names why the section was skipped, when a caller skips it for another reason than a missing input. */
    skippedMessage?: string
}): JSX.Element {
    const data = section.data
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')
    const resultsRedesign = useFeatureFlag('EXPERIMENTS_RESULTS_REDESIGN')
    const quillView = todayRailNav && resultsRedesign
    return (
        <SetupContextSection
            title="SDK profile"
            description="Which SDKs send multivariate flag calls across the whole project, and how they evaluate flags."
            status={section.status}
            skippedMessage={skippedMessage}
        >
            {data && (
                <>
                    <SetupFactsTable
                        facts={[
                            { label: 'Source event', value: data.source_event },
                            { label: 'Window', value: `Last ${data.window_days} days` },
                            { label: 'Flags seen', value: formatCount(data.flags_seen) },
                            {
                                label: 'Same flag evaluated on a server and on the web',
                                value: `${formatYesNo(data.evaluated_on_server_and_web)} (${formatCount(data.flags_evaluated_on_server_and_web)} flags)`,
                                help: 'The same flag decided on the server and read in the browser can put one user in two variants.',
                            },
                            { label: 'Computed at', value: formatTimestamp(data.computed_at) },
                        ]}
                    />
                    {quillView ? (
                        <QuillSdkTable columns={SDK_LIB_COLUMNS} data={data.libs} empty={NO_FLAG_CALLS} />
                    ) : (
                        <LemonTable<ExperimentSetupSdkLibApi>
                            size="small"
                            rowKey={(lib, index) => lib.lib ?? `unknown-${index}`}
                            dataSource={data.libs}
                            emptyState={NO_FLAG_CALLS}
                            columns={[
                                { title: 'SDK', render: (_, lib) => lib.lib ?? 'unknown' },
                                { title: 'Category', dataIndex: 'category' },
                                { title: 'Calls', align: 'right', render: (_, lib) => formatCount(lib.calls) },
                                {
                                    title: 'Distinct IDs',
                                    align: 'right',
                                    render: (_, lib) => formatCount(lib.distinct_ids),
                                },
                                {
                                    title: 'Evaluated locally',
                                    align: 'right',
                                    render: (_, lib) => formatShare(lib.locally_evaluated_share),
                                },
                                {
                                    title: 'Anonymous',
                                    align: 'right',
                                    render: (_, lib) => formatShare(lib.anonymous_share),
                                },
                                {
                                    title: 'Device ID',
                                    align: 'right',
                                    render: (_, lib) => formatShare(lib.device_id_share),
                                },
                            ]}
                        />
                    )}
                    {data.libs_truncated && (
                        <p className="text-secondary text-sm mb-0">More SDKs sent flag calls than the list shows.</p>
                    )}
                    {data.libs_on_any_event && (
                        <>
                            <p className="text-sm mb-0">
                                No flag calls yet. These SDKs sent events of any kind over the last day:
                            </p>
                            {quillView ? (
                                <QuillSdkTable columns={LIB_ACTIVITY_COLUMNS} data={data.libs_on_any_event} />
                            ) : (
                                <LemonTable<ExperimentSetupLibActivityApi>
                                    size="small"
                                    rowKey={(lib, index) => lib.lib ?? `unknown-${index}`}
                                    dataSource={data.libs_on_any_event}
                                    columns={[
                                        { title: 'SDK', render: (_, lib) => lib.lib ?? 'unknown' },
                                        { title: 'Category', dataIndex: 'category' },
                                        {
                                            title: 'Events',
                                            align: 'right',
                                            render: (_, lib) => formatCount(lib.events),
                                        },
                                        {
                                            title: 'Distinct IDs',
                                            align: 'right',
                                            render: (_, lib) => formatCount(lib.distinct_ids),
                                        },
                                    ]}
                                />
                            )}
                        </>
                    )}
                </>
            )}
        </SetupContextSection>
    )
}
