import { LemonTable } from 'lib/lemon-ui/LemonTable'

import type {
    ExperimentSetupLibReachApi,
    ExperimentSetupTargetSurfaceSectionApi,
} from 'products/experiments/frontend/generated/api.schemas'

import { SetupContextSection } from '../SetupContextSection'
import { SetupFactsTable } from '../SetupFactsTable'
import { formatCount, formatPropertyFilters, formatShare, formatTimestamp, formatYesNo } from '../setupInspectorUtils'

export function TargetSurfaceSection({ section }: { section: ExperimentSetupTargetSurfaceSectionApi }): JSX.Element {
    const data = section.data
    return (
        <SetupContextSection
            title="Target surface"
            description="Traffic on the surface under test."
            status={section.status}
            skippedMessage="Pick an event in step 1 above to read this section."
        >
            {data && (
                <>
                    <SetupFactsTable
                        facts={[
                            { label: 'Target event', value: data.source_event },
                            { label: 'URL contains', value: data.target_url_contains ?? 'None' },
                            { label: 'Property filters', value: formatPropertyFilters(data.target_properties) },
                            { label: 'Test accounts filtered', value: formatYesNo(data.test_accounts_filtered) },
                            { label: 'Unique persons', value: formatCount(data.unique_persons) },
                            {
                                label: 'Exposures per day, estimated',
                                value: formatCount(data.exposures_per_day_estimate),
                                help: 'Unique persons divided by the days in the window.',
                            },
                            { label: 'Anonymous share', value: formatShare(data.anonymous_share) },
                            { label: 'Device ID share', value: formatShare(data.device_id_share) },
                            { label: 'Window', value: `Last ${data.window_days} days` },
                            { label: 'Computed at', value: formatTimestamp(data.computed_at) },
                        ]}
                    />
                    <LemonTable<ExperimentSetupLibReachApi>
                        size="small"
                        rowKey={(lib, index) => lib.lib ?? `unknown-${index}`}
                        dataSource={data.libs}
                        emptyState="No SDK sent the target event in the window."
                        columns={[
                            { title: 'SDK', render: (_, lib) => lib.lib ?? 'unknown' },
                            { title: 'Category', dataIndex: 'category' },
                            {
                                title: 'Persons',
                                align: 'right',
                                render: (_, lib) => formatCount(lib.unique_persons),
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
                </>
            )}
        </SetupContextSection>
    )
}
