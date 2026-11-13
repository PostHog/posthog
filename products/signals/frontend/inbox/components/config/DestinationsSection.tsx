import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LinkedHogFunctions } from 'scenes/hog-functions/list/LinkedHogFunctions'
import { urls } from 'scenes/urls'

import { SettingsSection } from '../tabs/SettingsSection'

export function DestinationsSection(): JSX.Element | null {
    const destinationsEnabled = useFeatureFlag('INBOX_REPORT_DESTINATIONS')

    if (!destinationsEnabled) {
        return null
    }

    return (
        <SettingsSection
            title="Destinations"
            description="Send each new report to a webhook or another destination when it reaches your Inbox. A report can arrive more than once, so deduplicate on its report_id."
        >
            <LinkedHogFunctions
                type="internal_destination"
                subTemplateIds={['inbox-report-ready']}
                emptyText="No destinations yet"
                queryParams={{ returnTo: urls.inbox('settings') }}
            />
        </SettingsSection>
    )
}
