import { useActions, useValues } from 'kea'
import { useEffect, useRef, useState } from 'react'
import posthog from 'posthog-js'

import { IconLink, IconPlus } from '@posthog/icons'
import { LemonDialog, LemonInput, LemonInputSelect, LemonTextArea, Link } from '@posthog/lemon-ui'

import api, { ExternalIssueSearchResult } from 'lib/api'
import { ErrorTrackingFingerprint } from 'lib/components/Errors/types'
import { GitHubRepositoryPicker, GitHubRepositorySelectField } from 'lib/integrations/GitHubIntegrationHelpers'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { JiraProjectSelectField } from 'lib/integrations/JiraIntegrationHelpers'
import { LinearTeamSelectField } from 'lib/integrations/LinearIntegrationHelpers'
import { ICONS } from 'lib/integrations/utils'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuGroup,
    DropdownMenuItem,
    DropdownMenuTrigger,
} from 'lib/ui/DropdownMenu/DropdownMenu'
import { WrappingLoadingSkeleton } from 'lib/ui/WrappingLoadingSkeleton/WrappingLoadingSkeleton'
import { addProjectIdIfMissing } from 'lib/utils/kea-router'
import { urls } from 'scenes/urls'

import { ErrorTrackingExternalReference, ErrorTrackingRelationalIssue } from '~/queries/schema/schema-general'
import { IntegrationKind, IntegrationType } from '~/types'

import { errorTrackingIssueSceneLogic } from '../scenes/ErrorTrackingIssueScene/errorTrackingIssueSceneLogic'

const ERROR_TRACKING_INTEGRATIONS = ['linear', 'github', 'gitlab', 'jira'] as const satisfies readonly IntegrationKind[]

type onSubmitFormType = (integrationId: number, config: Record<string, string>) => void
type onSubmitLinkType = (integrationId: number, externalContext: Record<string, string | number>) => void
type ErrorTrackingIntegrationKind = (typeof ERROR_TRACKING_INTEGRATIONS)[number]
type ErrorTrackingIntegration = IntegrationType & { kind: ErrorTrackingIntegrationKind }

const POSTHOG_HTML_LINE_BREAKS = '\n<br/>\n<br/>\n'

const PROVIDER_LABELS: Record<ErrorTrackingIntegrationKind, string> = {
    github: 'GitHub',
    gitlab: 'GitLab',
    linear: 'Linear',
    jira: 'Jira',
}

const EXTERNAL_REFERENCE_FORM_BUILDERS: Record<
    ErrorTrackingIntegrationKind,
    (
        issue: ErrorTrackingRelationalIssue,
        issueUrl: string,
        integration: ErrorTrackingIntegration,
        onSubmit: onSubmitFormType
    ) => void
> = {
    github: createGitHubIssueForm,
    gitlab: createGitLabIssueForm,
    linear: createLinearIssueForm,
    jira: createJiraIssueForm,
}

export const ExternalReferences = (): JSX.Element | null => {
    const { issue, issueLoading, issueFingerprints } = useValues(errorTrackingIssueSceneLogic)
    const { createExternalReference, linkExternalReference } = useActions(errorTrackingIssueSceneLogic)
    const { getIntegrationsByKind, integrationsLoading } = useValues(integrationsLogic)

    if (!issue || integrationsLoading) {
        return (
            <WrappingLoadingSkeleton fullWidth>
                <ButtonPrimitive menuItem aria-hidden>
                    Loading
                </ButtonPrimitive>
            </WrappingLoadingSkeleton>
        )
    }

    const errorTrackingIntegrations = getIntegrationsByKind([...ERROR_TRACKING_INTEGRATIONS])
    const externalReferences = issue.external_issues ?? []
    const busy = !!issue && issueLoading

    const onClickCreateIssue = (integration: IntegrationType): void => {
        const buildForm = EXTERNAL_REFERENCE_FORM_BUILDERS[integration.kind as ErrorTrackingIntegrationKind]

        if (buildForm) {
            buildForm(
                issue,
                getIssueUrl(issueFingerprints),
                integration as ErrorTrackingIntegration,
                createExternalReference
            )
        }
    }

    const onClickLinkIssue = (integration: IntegrationType): void => {
        linkExistingIssueForm(integration as ErrorTrackingIntegration, linkExternalReference)
    }

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
                        <IntegrationIcon kind={reference.integration.kind} />
                        {reference.integration.display_name}
                    </ButtonPrimitive>
                </Link>
            ))}
            {errorTrackingIntegrations.length === 0 ? (
                <SetupIntegrationsButton />
            ) : (
                <>
                    <IntegrationActionButton
                        integrations={errorTrackingIntegrations}
                        icon={<IconPlus />}
                        label="Create issue"
                        busyLabel="Creating issue..."
                        busy={busy}
                        onSelect={onClickCreateIssue}
                    />
                    <IntegrationActionButton
                        integrations={errorTrackingIntegrations}
                        icon={<IconLink />}
                        label="Link existing issue"
                        busyLabel="Linking issue..."
                        busy={busy}
                        onSelect={onClickLinkIssue}
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
    integrations: IntegrationType[]
    icon: JSX.Element
    label: string
    busyLabel: string
    busy: boolean
    onSelect: (integration: IntegrationType) => void
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
                    {integrations.map((integration: IntegrationType) => (
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

// Link through the fingerprint redirect page when possible — it resolves to whatever issue the
// fingerprint belongs to at click time, so external issue links survive merges. Fingerprints are
// listed oldest-first; the oldest one is the stable, canonical one for an issue.
function getIssueUrl(fingerprints: ErrorTrackingFingerprint[]): string {
    const canonicalFingerprint = fingerprints[0]?.fingerprint
    if (canonicalFingerprint) {
        return `${window.location.origin}${addProjectIdIfMissing(urls.errorTrackingFingerprint(canonicalFingerprint))}`
    }
    return `${window.location.origin}${window.location.pathname}`
}

function getIssueMarkdownBody(issue: ErrorTrackingRelationalIssue, issueUrl: string): string {
    return `${issue.description ?? ''}${POSTHOG_HTML_LINE_BREAKS}**PostHog issue:** ${issueUrl}`
}

function getIssuePlaintextBody(issue: ErrorTrackingRelationalIssue, issueUrl: string): string {
    return `${issue.description ?? ''}\n\nPostHog issue: ${issueUrl}`
}

function createGitHubIssueForm(
    issue: ErrorTrackingRelationalIssue,
    issueUrl: string,
    integration: ErrorTrackingIntegration,
    onSubmit: onSubmitFormType
): void {
    LemonDialog.openForm({
        title: 'Create GitHub issue',
        shouldAwaitSubmit: true,
        initialValues: {
            title: issue.name,
            body: getIssueMarkdownBody(issue, issueUrl),
            integrationId: integration.id,
            repositories: [],
        },
        content: (
            <div className="flex flex-col gap-y-2">
                <GitHubRepositorySelectField integrationId={integration.id} />
                <LemonField name="title" label="Title">
                    <LemonInput data-attr="issue-title" placeholder="Issue title" size="small" />
                </LemonField>
                <LemonField name="body" label="Body">
                    <LemonTextArea data-attr="issue-body" placeholder="Start typing..." />
                </LemonField>
            </div>
        ),
        errors: {
            title: (title) => (!title ? 'You must enter a title' : undefined),
            repositories: (repositories) =>
                repositories && repositories.length === 0 ? 'You must choose a repository' : undefined,
        },
        onSubmit: ({ title, body, repositories }) => {
            onSubmit(integration.id, { repository: repositories[0], title, body })
        },
    })
}

function createGitLabIssueForm(
    issue: ErrorTrackingRelationalIssue,
    issueUrl: string,
    integration: ErrorTrackingIntegration,
    onSubmit: onSubmitFormType
): void {
    LemonDialog.openForm({
        title: 'Create GitLab issue',
        shouldAwaitSubmit: true,
        initialValues: {
            title: issue.name,
            body: getIssueMarkdownBody(issue, issueUrl),
            integrationId: integration.id,
        },
        content: (
            <div className="flex flex-col gap-y-2">
                <LemonField name="title" label="Title">
                    <LemonInput data-attr="issue-title" placeholder="Issue title" size="small" />
                </LemonField>
                <LemonField name="body" label="Body">
                    <LemonTextArea data-attr="issue-body" placeholder="Start typing..." />
                </LemonField>
            </div>
        ),
        errors: {
            title: (title) => (!title ? 'You must enter a title' : undefined),
        },
        onSubmit: ({ title, body }) => {
            onSubmit(integration.id, { title, body })
        },
    })
}

function createLinearIssueForm(
    issue: ErrorTrackingRelationalIssue,
    _issueUrl: string,
    integration: ErrorTrackingIntegration,
    onSubmit: onSubmitFormType
): void {
    LemonDialog.openForm({
        title: 'Create Linear issue',
        shouldAwaitSubmit: true,
        initialValues: {
            title: issue.name,
            description: issue.description,
            integrationId: integration.id,
            teamIds: [],
        },
        content: (
            <div className="flex flex-col gap-y-2">
                <LinearTeamSelectField integrationId={integration.id} />
                <LemonField name="title" label="Title">
                    <LemonInput data-attr="issue-title" placeholder="Issue title" size="small" />
                </LemonField>
                <LemonField name="description" label="Description">
                    <LemonTextArea data-attr="issue-description" placeholder="Start typing..." />
                </LemonField>
            </div>
        ),
        errors: {
            title: (title) => (!title ? 'You must enter a title' : undefined),
            teamIds: (teamIds) => (teamIds && teamIds.length === 0 ? 'You must choose a team' : undefined),
        },
        onSubmit: ({ title, description, teamIds }) => {
            onSubmit(integration.id, { team_id: teamIds[0], title, description })
        },
    })
}

function createJiraIssueForm(
    issue: ErrorTrackingRelationalIssue,
    issueUrl: string,
    integration: ErrorTrackingIntegration,
    onSubmit: onSubmitFormType
): void {
    LemonDialog.openForm({
        title: 'Create Jira issue',
        shouldAwaitSubmit: true,
        initialValues: {
            title: issue.name,
            description: getIssuePlaintextBody(issue, issueUrl),
            integrationId: integration.id,
            projectKeys: [],
        },
        content: (
            <div className="flex flex-col gap-y-2">
                <JiraProjectSelectField integrationId={integration.id} />
                <LemonField name="title" label="Summary">
                    <LemonInput data-attr="jira-issue-title" placeholder="Issue summary" size="small" />
                </LemonField>
                <LemonField name="description" label="Description">
                    <LemonTextArea data-attr="jira-issue-description" placeholder="Start typing..." />
                </LemonField>
            </div>
        ),
        errors: {
            title: (title) => (!title ? 'You must enter a summary' : undefined),
            projectKeys: (projectKeys) =>
                projectKeys && projectKeys.length === 0 ? 'You must choose a project' : undefined,
        },
        onSubmit: ({ title, description, projectKeys }) => {
            onSubmit(integration.id, { project_key: projectKeys[0], title, description })
        },
    })
}

function linkExistingIssueForm(integration: ErrorTrackingIntegration, onSubmit: onSubmitLinkType): void {
    const label = PROVIDER_LABELS[integration.kind]
    LemonDialog.openForm({
        title: `Link existing ${label} issue`,
        shouldAwaitSubmit: true,
        initialValues: { externalContext: null as Record<string, string | number> | null },
        content: (
            <LemonField name="externalContext" label="Issue">
                <ExistingIssueSelect integrationId={integration.id} kind={integration.kind} />
            </LemonField>
        ),
        errors: {
            externalContext: (externalContext) => (!externalContext ? 'You must select an issue' : undefined),
        },
        onSubmit: ({ externalContext }) => {
            if (externalContext) {
                onSubmit(integration.id, externalContext)
            }
        },
    })
}

// Searchable picker of existing provider issues. Designed to sit inside a LemonField, so it takes the
// field's value/onChange and emits the selected issue's external_context (the payload the backend stores).
function ExistingIssueSelect({
    integrationId,
    kind,
    onChange,
}: {
    integrationId: number
    kind: ErrorTrackingIntegrationKind
    value?: Record<string, string | number> | null
    onChange?: (value: Record<string, string | number> | null) => void
}): JSX.Element {
    const requiresRepository = kind === 'github'
    const [repository, setRepository] = useState<string>('')
    const [results, setResults] = useState<ExternalIssueSearchResult[]>([])
    const [loading, setLoading] = useState<boolean>(false)
    const [selectedKey, setSelectedKey] = useState<string | null>(null)
    const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)

    const runSearch = (query: string): void => {
        if (requiresRepository && !repository) {
            return
        }
        if (debounceRef.current) {
            clearTimeout(debounceRef.current)
        }
        debounceRef.current = setTimeout(() => {
            setLoading(true)
            api.errorTracking
                .searchExternalIssues(integrationId, query, requiresRepository ? repository : undefined)
                .then(({ issues }) => setResults(issues))
                .catch(() => setResults([]))
                .finally(() => setLoading(false))
        }, 300)
    }

    // Populate an initial list (and refresh it when the GitHub repository changes) without waiting for input.
    useEffect(() => {
        if (!requiresRepository || repository) {
            runSearch('')
        }
        return () => {
            if (debounceRef.current) {
                clearTimeout(debounceRef.current)
            }
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [repository])

    const optionKey = (result: ExternalIssueSearchResult): string => result.url || `${result.id}`
    const options = results.map((result) => ({
        key: optionKey(result),
        label: result.title,
    }))

    return (
        <div className="flex flex-col gap-y-2">
            {requiresRepository && (
                <GitHubRepositoryPicker
                    integrationId={integrationId}
                    value={repository}
                    onChange={(value) => {
                        setRepository(value ?? '')
                        setResults([])
                        setSelectedKey(null)
                        onChange?.(null)
                    }}
                />
            )}
            <LemonInputSelect
                mode="single"
                data-attr="select-existing-issue"
                placeholder={
                    requiresRepository && !repository ? 'Select a repository first...' : 'Search for an issue...'
                }
                disabled={requiresRepository && !repository}
                loading={loading}
                options={options}
                value={selectedKey ? [selectedKey] : []}
                onInputChange={runSearch}
                onChange={(value) => {
                    const key = value[0] ?? null
                    setSelectedKey(key)
                    const selected = results.find((result) => optionKey(result) === key)
                    onChange?.(selected ? selected.external_context : null)
                }}
            />
        </div>
    )
}

const IntegrationIcon = ({ kind }: { kind: IntegrationKind }): JSX.Element => {
    return <img src={ICONS[kind]} className="w-5 h-5 rounded-sm" />
}
