import { useActions, useValues } from 'kea'

import { LemonDialog, LemonSegmentedButton, Link } from '@posthog/lemon-ui'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'
import { urls } from 'scenes/urls'

import type { EventsRetentionWindowEnumApi } from 'products/product_analytics/frontend/generated/api.schemas'

import { eventsRetentionSettingsLogic } from './eventsRetentionSettingsLogic'

const LONGEST_RETENTION_MONTHS = 84

export function EventsRetentionSettings(): JSX.Element | null {
    const { eventsRetention, eventsRetentionLoading, retentionOptions } = useValues(eventsRetentionSettingsLogic)
    const { updateEventsRetention } = useActions(eventsRetentionSettingsLogic)
    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })

    // Both are null until retention applies to this project, so the setting stays hidden until then.
    if (eventsRetention?.retention_months == null || eventsRetention.max_retention_months == null) {
        return null
    }
    const currentMonths = eventsRetention.retention_months

    const handleChange = (retentionMonths: EventsRetentionWindowEnumApi): void => {
        if (retentionMonths === currentMonths) {
            return
        }
        const label = retentionOptions.find((option) => option.value === retentionMonths)?.label ?? ''
        LemonDialog.open({
            title: `Change events retention to ${label}?`,
            description:
                'This changes how far back insights, dashboards, and SQL queries can read events in this project.',
            primaryButton: {
                children: `Change to ${label}`,
                onClick: () => updateEventsRetention(retentionMonths),
            },
            secondaryButton: { children: 'Cancel' },
        })
    }

    return (
        <div>
            <h2 id="events-retention" className="text-base font-semibold mb-0">
                Events retention
            </h2>
            <p className="max-w-160 text-sm text-secondary mb-4">
                Choose how long events stay queryable in this project. The longest window depends on your plan.{' '}
                <Link to={eventsRetention.docs_url} target="_blank">
                    Learn more
                </Link>
            </p>
            <LemonSegmentedButton
                value={currentMonths as EventsRetentionWindowEnumApi}
                onChange={handleChange}
                options={retentionOptions.map((option) => ({
                    ...option,
                    'data-attr': `events-retention-button-${option.value}`,
                }))}
                disabledReason={eventsRetentionLoading ? 'Saving...' : (restrictedReason ?? undefined)}
            />
            {eventsRetention.max_retention_months < LONGEST_RETENTION_MONTHS && (
                <p className="mt-4">
                    Need a longer window? <Link to={urls.organizationBilling()}>Upgrade your plan</Link>.
                </p>
            )}
        </div>
    )
}
