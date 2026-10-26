import { useActions, useValues } from 'kea'

import { LemonDialog, LemonSegmentedButton, Link } from '@posthog/lemon-ui'

import { useRestrictedArea } from 'lib/components/RestrictedArea'
import { OrganizationMembershipLevel } from 'lib/constants'
import { ORG_ADMIN_REQUIRED_TOOLTIP } from 'scenes/settings/organization/organizationSettingsConstants'
import { urls } from 'scenes/urls'

import type { EventsRetentionWindowEnumApi } from 'products/product_analytics/frontend/generated/api.schemas'

import { eventsRetentionSettingsLogic } from './eventsRetentionSettingsLogic'

const EVENTS_RETENTION_DOCS_URL = 'https://posthog.com/docs/data/events-retention'
const LONGEST_RETENTION_MONTHS = 84

export function EventsRetentionSettings(): JSX.Element | null {
    const {
        retentionEnforced,
        organizationRetention,
        organizationRetentionLoading,
        retentionOptions,
        selectedRetentionMonths,
    } = useValues(eventsRetentionSettingsLogic)
    const { updateOrganizationRetention } = useActions(eventsRetentionSettingsLogic)
    const restrictionReason = useRestrictedArea({
        minimumAccessLevel: OrganizationMembershipLevel.Admin,
    })

    // Hidden until retention applies to the current project, so the setting stays behind the rollout.
    if (!retentionEnforced || !organizationRetention) {
        return null
    }

    const handleChange = (retentionMonths: EventsRetentionWindowEnumApi): void => {
        if (retentionMonths === selectedRetentionMonths) {
            return
        }
        const label = retentionOptions.find((option) => option.value === retentionMonths)?.label ?? ''
        LemonDialog.open({
            title: `Change events retention to ${label}?`,
            description:
                'This changes how far back insights, dashboards, and SQL queries can read events in every project in this organization.',
            primaryButton: {
                children: `Change to ${label}`,
                onClick: () => updateOrganizationRetention(retentionMonths),
            },
            secondaryButton: { children: 'Cancel' },
        })
    }

    return (
        <div>
            <h2 id="organization-events-retention" className="text-base font-semibold mb-0">
                Events retention
            </h2>
            <p className="max-w-160 text-sm text-secondary mb-4">
                Choose how long events stay queryable in every project in this organization. The longest window depends
                on your plan.{' '}
                <Link to={EVENTS_RETENTION_DOCS_URL} target="_blank">
                    Learn more
                </Link>
            </p>
            <LemonSegmentedButton
                value={(selectedRetentionMonths ?? undefined) as EventsRetentionWindowEnumApi | undefined}
                onChange={handleChange}
                options={retentionOptions.map((option) => ({
                    ...option,
                    'data-attr': `events-retention-button-${option.value}`,
                }))}
                disabledReason={
                    organizationRetentionLoading
                        ? 'Saving...'
                        : restrictionReason
                          ? ORG_ADMIN_REQUIRED_TOOLTIP
                          : undefined
                }
            />
            {organizationRetention.max_retention_months < LONGEST_RETENTION_MONTHS && (
                <p className="mt-4">
                    Need a longer window? <Link to={urls.organizationBilling()}>Upgrade your plan</Link>.
                </p>
            )}
        </div>
    )
}
