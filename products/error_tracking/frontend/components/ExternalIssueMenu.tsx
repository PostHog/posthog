import { router } from 'kea-router'

import { IconChevronDown, IconPlus } from '@posthog/icons'

import { IconLink } from 'lib/lemon-ui/icons'
import {
    Button,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuGroup,
    DropdownMenuItem,
    DropdownMenuLabel,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
} from 'lib/ui/quill'
import { urls } from 'scenes/urls'

import { ErrorTrackingIntegration, IntegrationIcon } from './errorTrackingIntegrations'
import { useExternalReferenceActions } from './useExternalReferenceActions'

// Issue header entry point for creating or linking a GitHub, GitLab, Linear or Jira issue. The
// same actions also sit in the scene context panel, which stays collapsed until a user opens it.
export function ExternalIssueMenu(): JSX.Element {
    const { integrations, loading, busy, createIssue, linkIssue } = useExternalReferenceActions('issue_header')

    return (
        <DropdownMenu>
            <DropdownMenuTrigger
                render={
                    <Button
                        variant="outline"
                        disabled={loading || busy}
                        data-attr="error-tracking-issue-external-issue-menu"
                    />
                }
            >
                Create issue
                <IconChevronDown />
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-auto min-w-56">
                {integrations.length === 0 ? (
                    <DropdownMenuItem
                        onClick={() =>
                            router.actions.push(
                                urls.settings('environment-error-tracking', 'error-tracking-integrations')
                            )
                        }
                        data-attr="error-tracking-issue-setup-integrations"
                    >
                        Set up integrations
                    </DropdownMenuItem>
                ) : integrations.length === 1 ? (
                    <>
                        <DropdownMenuItem
                            onClick={() => createIssue(integrations[0])}
                            data-attr="error-tracking-issue-create-external-issue"
                        >
                            <IconPlus />
                            Create issue
                        </DropdownMenuItem>
                        <DropdownMenuItem
                            onClick={() => linkIssue(integrations[0])}
                            data-attr="error-tracking-issue-link-external-issue"
                        >
                            <IconLink />
                            Link existing issue
                        </DropdownMenuItem>
                    </>
                ) : (
                    <>
                        <IntegrationGroup
                            label="Create issue"
                            integrations={integrations}
                            onSelect={createIssue}
                            dataAttr="error-tracking-issue-create-external-issue"
                        />
                        <DropdownMenuSeparator />
                        <IntegrationGroup
                            label="Link existing issue"
                            integrations={integrations}
                            onSelect={linkIssue}
                            dataAttr="error-tracking-issue-link-external-issue"
                        />
                    </>
                )}
            </DropdownMenuContent>
        </DropdownMenu>
    )
}

function IntegrationGroup({
    label,
    integrations,
    onSelect,
    dataAttr,
}: {
    label: string
    integrations: ErrorTrackingIntegration[]
    onSelect: (integration: ErrorTrackingIntegration) => void
    dataAttr: string
}): JSX.Element {
    return (
        <DropdownMenuGroup>
            <DropdownMenuLabel>{label}</DropdownMenuLabel>
            {integrations.map((integration: ErrorTrackingIntegration) => (
                <DropdownMenuItem key={integration.id} onClick={() => onSelect(integration)} data-attr={dataAttr}>
                    <IntegrationIcon kind={integration.kind} />
                    {integration.display_name}
                </DropdownMenuItem>
            ))}
        </DropdownMenuGroup>
    )
}
