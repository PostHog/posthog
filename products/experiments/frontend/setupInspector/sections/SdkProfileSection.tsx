import { LemonTable } from 'lib/lemon-ui/LemonTable'

import type {
    ExperimentSetupLibActivityApi,
    ExperimentSetupSdkLibApi,
    ExperimentSetupSdkProfileSectionApi,
} from 'products/experiments/frontend/generated/api.schemas'

import { SetupContextSection } from '../SetupContextSection'
import { SetupFactsTable } from '../SetupFactsTable'
import { formatCount, formatShare, formatTimestamp, formatYesNo } from '../setupInspectorUtils'

export function SdkProfileSection({ section }: { section: ExperimentSetupSdkProfileSectionApi }): JSX.Element {
    const data = section.data
    return (
        <SetupContextSection
            title="SDK profile"
            description="Which SDKs send multivariate flag calls across the whole project, and how they evaluate flags."
            status={section.status}
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
                    <LemonTable<ExperimentSetupSdkLibApi>
                        size="small"
                        rowKey={(lib, index) => lib.lib ?? `unknown-${index}`}
                        dataSource={data.libs}
                        emptyState="No multivariate flag calls in the window."
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
                    {data.libs_truncated && (
                        <p className="text-secondary text-sm mb-0">More SDKs sent flag calls than the list shows.</p>
                    )}
                    {data.libs_on_any_event && (
                        <>
                            <p className="text-sm mb-0">
                                No flag calls yet. These SDKs sent events of any kind over the last day:
                            </p>
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
                        </>
                    )}
                </>
            )}
        </SetupContextSection>
    )
}
