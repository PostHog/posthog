import { useActions, useValues } from 'kea'

import { LemonBanner, Link } from '@posthog/lemon-ui'

import { useRestrictedArea } from 'lib/components/RestrictedArea'
import { OrganizationMembershipLevel } from 'lib/constants'
import { urls } from 'scenes/urls'

import { planDeletionDateLabel } from 'products/product_analytics/frontend/insights/dataRetention/planDeletionDateLabel'

import { eventsRetentionSettingsLogic } from './eventsRetentionSettingsLogic'
import { EventsRetentionWindowForm } from './EventsRetentionWindowForm'

export function ProjectEventsRetentionSetting(): JSX.Element | null {
    const { projectRetention, projectRetentionLoading } = useValues(eventsRetentionSettingsLogic)
    const { updateProjectRetention } = useActions(eventsRetentionSettingsLogic)
    const restrictionReason = useRestrictedArea({ minimumAccessLevel: OrganizationMembershipLevel.Admin })

    if (!projectRetention) {
        return null
    }

    const organizationMonths = projectRetention.organization_retention_months
    const planMonths = projectRetention.plan_retention_months
    const fallback =
        organizationMonths !== null
            ? `the organization's window of ${organizationMonths} months`
            : `your plan's window of ${planMonths} months`
    const deletionDateLabel = planDeletionDateLabel(projectRetention)

    return (
        <div>
            {deletionDateLabel && (
                <LemonBanner
                    type="warning"
                    className="max-w-160 mb-4"
                    action={{ children: 'Upgrade plan', to: urls.organizationBilling() }}
                >
                    {`Events older than your plan's window of ${planMonths} months will be deleted starting ${deletionDateLabel}, and then every 3 months. Deleted events can't be restored.`}
                </LemonBanner>
            )}
            <p className="max-w-160 text-sm text-secondary mb-4">
                Choose how long this project keeps events. This replaces the window set in{' '}
                <Link to={urls.settings('organization-details', 'organization-events-retention')}>
                    organization settings
                </Link>
                . {projectRetention.project_retention_months === null && `This project uses ${fallback}. `}
                <Link to={projectRetention.docs_url} target="_blank">
                    Learn more
                </Link>
            </p>
            <EventsRetentionWindowForm
                retentionMonths={projectRetention.project_retention_months}
                minMonths={projectRetention.min_retention_months}
                maxMonths={projectRetention.max_retention_months}
                planMonths={planMonths}
                keptBy="This project"
                removedDescription={
                    organizationMonths !== null
                        ? `This project will use ${fallback}. Older events are deleted at the next monthly cleanup and can't be restored.`
                        : `This project will keep events for ${fallback}.`
                }
                saving={projectRetentionLoading}
                restrictionReason={restrictionReason}
                onSave={updateProjectRetention}
                dataAttr="project-events-retention"
            />
        </div>
    )
}
