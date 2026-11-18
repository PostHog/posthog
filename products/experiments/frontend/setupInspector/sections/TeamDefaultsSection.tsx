import type { ExperimentSetupTeamDefaultsSectionApi } from 'products/experiments/frontend/generated/api.schemas'

import { SetupContextSection } from '../SetupContextSection'
import { SetupFactsTable } from '../SetupFactsTable'
import { formatYesNo } from '../setupInspectorUtils'

function withProductDefault(value: string | number | null, productDefault: string | number): string {
    return value === null ? `Not set, product default ${productDefault}` : String(value)
}

export function TeamDefaultsSection({ section }: { section: ExperimentSetupTeamDefaultsSectionApi }): JSX.Element {
    const data = section.data
    return (
        <SetupContextSection
            title="Team defaults"
            description="The defaults a new experiment in this project starts from."
            status={section.status}
        >
            {data && (
                <SetupFactsTable
                    facts={[
                        {
                            label: 'Stats method',
                            value: withProductDefault(data.stats_method, data.product_default_stats_method),
                        },
                        {
                            label: 'Confidence level',
                            value: withProductDefault(data.confidence_level, data.product_default_confidence_level),
                        },
                        {
                            label: 'Minimum detectable effect',
                            value: withProductDefault(
                                data.minimum_detectable_effect === null ? null : `${data.minimum_detectable_effect}%`,
                                `${data.product_default_minimum_detectable_effect}%`
                            ),
                        },
                        { label: 'Only count matured users', value: formatYesNo(data.only_count_matured_users) },
                        { label: 'CUPED', value: formatYesNo(data.cuped_enabled) },
                        { label: 'Sequential testing', value: formatYesNo(data.sequential_testing_enabled) },
                        {
                            label: 'Persist flags across authentication',
                            value: formatYesNo(data.flags_persistence_default),
                            help: 'Becomes ensure_experience_continuity on a flag the experiment creates.',
                        },
                        { label: 'Test account filters', value: String(data.test_account_filter_count) },
                        {
                            label: 'New experiments filter test accounts',
                            value: formatYesNo(data.new_experiments_filter_test_accounts),
                        },
                        { label: 'Default exposure event', value: data.default_exposure_event },
                    ]}
                />
            )}
        </SetupContextSection>
    )
}
