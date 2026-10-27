import type { ExperimentSetupProjectTrafficSectionApi } from 'products/experiments/frontend/generated/api.schemas'

import { SetupContextSection } from '../SetupContextSection'
import { SetupFactsTable } from '../SetupFactsTable'
import { formatCount, formatTimestamp, formatYesNo } from '../setupInspectorUtils'

export function ProjectTrafficSection({ section }: { section: ExperimentSetupProjectTrafficSectionApi }): JSX.Element {
    const data = section.data
    return (
        <SetupContextSection
            title="Project traffic"
            description="People who viewed a page or a screen anywhere in the project. Needs no input."
            status={section.status}
        >
            {data && (
                <SetupFactsTable
                    facts={[
                        {
                            label: 'Unique persons',
                            value: formatCount(data.unique_persons),
                            help: 'Persons who sent a $pageview or a $screen in the window.',
                        },
                        { label: 'Test accounts filtered', value: formatYesNo(data.test_accounts_filtered) },
                        { label: 'Window', value: `Last ${data.window_days} days` },
                        { label: 'Computed at', value: formatTimestamp(data.computed_at) },
                    ]}
                />
            )}
        </SetupContextSection>
    )
}
