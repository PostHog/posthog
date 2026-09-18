import { useValues } from 'kea'
import posthog from 'posthog-js'

import { IconPlus } from '@posthog/icons'
import { Link } from '@posthog/lemon-ui'

import { IconLink } from 'lib/lemon-ui/icons'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuGroup,
    DropdownMenuItem,
    DropdownMenuTrigger,
} from 'lib/ui/DropdownMenu/DropdownMenu'
import { WrappingLoadingSkeleton } from 'lib/ui/WrappingLoadingSkeleton/WrappingLoadingSkeleton'
import { urls } from 'scenes/urls'

import { ErrorTrackingExternalReference } from '~/queries/schema/schema-general'

import { errorTrackingIssueSceneLogic } from '../scenes/ErrorTrackingIssueScene/errorTrackingIssueSceneLogic'
import {
    ErrorTrackingIntegration,
    ErrorTrackingIntegrationKind,
    IntegrationIcon,
    PROVIDER_LABELS,
} from './errorTrackingIntegrations'
import { useExternalReferenceActions } from './useExternalReferenceActions'

export const ExternalReferences = (): JSX.Element | null => {
    const { issue, issueLoading } = useValues(errorTrackingIssueSceneLogic)
    const { integrations, loading, busy, createIssue, linkIssue } = useExternalReferenceActions('scene_panel')

    if (!issue || loading) {
        return (
            <WrappingLoadingSkeleton fullWidth>
                <ButtonPrimitive menuItem aria-hidden>
                    Loading
                </ButtonPrimitive>
            </WrappingLoadingSkeleton>
        )
    }

    const externalReferences = issue.external_issues ?? []

    return (
        <div className="flex flex-col gap-y-1">
            {externalReferences.map((reference: ErrorTrackingExternalReference) => (
                <Link
                    key={reference.id}
                    to={reference.external_url}
                    target="_blank"
                    onClick={() => {
                        posthog.capture('error_tracking_external_issue_clicked', {
                            issue_id: issue.id,
                            integration_kind: reference.integration.kind,
                        })
                    }}
                >
                    <ButtonPrimitive fullWidth disabled={issueLoading}>
                        <div className="flex items-center gap-2 min-w-0 w-full">
                            <IntegrationIcon kind={reference.integration.kind} />
                            <span className="truncate min-w-0 flex-1 text-left">
                                {reference.title ||
                                    PROVIDER_LABELS[reference.integration.kind as ErrorTrackingIntegrationKind]}
                            </span>
                            {reference.external_id && (
                                <span className="text-sm text-muted flex-shrink-0 ml-auto">
                                    {reference.external_id}
                                </span>
                            )}
                        </div>
                    </ButtonPrimitive>
                </Link>
            ))}
            {integrations.length === 0 ? (
                <SetupIntegrationsButton />
            ) : (
                <>
                    <IntegrationActionButton
                        integrations={integrations}
                        icon={<IconPlus />}
                        label="Create issue"
                        busyLabel="Creating issue..."
                        busy={busy}
                        onSelect={createIssue}
                    />
                    <IntegrationActionButton
                        integrations={integrations}
                        icon={<IconLink />}
                        label="Link existing issue"
                        busyLabel="Linking issue..."
                        busy={busy}
                        onSelect={linkIssue}
                    />
                </>
            )}
        </div>
    )
}

// Renders one action (create / link) as a single button for one integration, or a dropdown to pick
// the integration when several are connected.
function IntegrationActionButton({
    integrations,
    icon,
    label,
    busyLabel,
    busy,
    onSelect,
}: {
    integrations: ErrorTrackingIntegration[]
    icon: JSX.Element
    label: string
    busyLabel: string
    busy: boolean
    onSelect: (integration: ErrorTrackingIntegration) => void
}): JSX.Element {
    if (integrations.length === 1) {
        return (
            <ButtonPrimitive fullWidth onClick={() => onSelect(integrations[0])} disabled={busy}>
                {icon}
                {busy ? busyLabel : label}
            </ButtonPrimitive>
        )
    }

    return (
        <DropdownMenu>
            <DropdownMenuTrigger asChild>
                <ButtonPrimitive fullWidth disabled={busy}>
                    {icon}
                    {busy ? busyLabel : label}
                </ButtonPrimitive>
            </DropdownMenuTrigger>

            <DropdownMenuContent loop matchTriggerWidth>
                <DropdownMenuGroup>
                    {integrations.map((integration: ErrorTrackingIntegration) => (
                        <DropdownMenuItem key={integration.id} asChild>
                            <ButtonPrimitive menuItem onClick={() => onSelect(integration)}>
                                <IntegrationIcon kind={integration.kind} />
                                {integration.display_name}
                            </ButtonPrimitive>
                        </DropdownMenuItem>
                    ))}
                </DropdownMenuGroup>
            </DropdownMenuContent>
        </DropdownMenu>
    )
}

function SetupIntegrationsButton(): JSX.Element {
    return (
        <Link
            to={urls.settings('environment-error-tracking', 'error-tracking-integrations')}
            buttonProps={{ variant: 'panel', fullWidth: true, menuItem: true }}
            tooltip="Go to integrations configuration"
            target="_blank"
        >
            Set up integrations
        </Link>
    )
}
