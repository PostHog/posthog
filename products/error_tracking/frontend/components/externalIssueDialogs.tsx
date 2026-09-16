import { useActions, useValues } from 'kea'

import { LemonDialog, LemonInput, LemonInputSelect, LemonTextArea } from '@posthog/lemon-ui'

import { GitHubRepositoryPicker, GitHubRepositorySelectField } from 'lib/integrations/GitHubIntegrationHelpers'
import { JiraProjectSelectField } from 'lib/integrations/JiraIntegrationHelpers'
import { LinearTeamSelectField } from 'lib/integrations/LinearIntegrationHelpers'
import { LemonField } from 'lib/lemon-ui/LemonField'

import { ErrorTrackingRelationalIssue } from '~/queries/schema/schema-general'

import {
    ErrorTrackingExternalIssueResultApi,
    ErrorTrackingExternalIssueResultApiExternalContext,
} from '../generated/api.schemas'
import { ErrorTrackingIntegration, ErrorTrackingIntegrationKind, PROVIDER_LABELS } from './errorTrackingIntegrations'
import { externalIssueSearchLogic } from './externalIssueSearchLogic'

type onSubmitFormType = (integrationId: number, config: Record<string, string>) => void
type onSubmitLinkType = (
    integrationId: number,
    externalContext: ErrorTrackingExternalIssueResultApiExternalContext
) => void

const POSTHOG_HTML_LINE_BREAKS = '\n<br/>\n<br/>\n'

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

export function openCreateIssueDialog(
    issue: ErrorTrackingRelationalIssue,
    issueUrl: string,
    integration: ErrorTrackingIntegration,
    onSubmit: onSubmitFormType
): void {
    EXTERNAL_REFERENCE_FORM_BUILDERS[integration.kind]?.(issue, issueUrl, integration, onSubmit)
}

export function openLinkIssueDialog(integration: ErrorTrackingIntegration, onSubmit: onSubmitLinkType): void {
    const label = PROVIDER_LABELS[integration.kind]
    LemonDialog.openForm({
        title: `Link existing ${label} issue`,
        shouldAwaitSubmit: true,
        initialValues: { externalIssue: null as ErrorTrackingExternalIssueResultApi | null },
        content: (
            <LemonField name="externalIssue" label="Issue">
                <ExistingIssueSelect integrationId={integration.id} kind={integration.kind} />
            </LemonField>
        ),
        errors: {
            externalIssue: (externalIssue) => (!externalIssue ? 'You must select an issue' : undefined),
        },
        onSubmit: ({ externalIssue }) => {
            if (externalIssue) {
                onSubmit(integration.id, { ...externalIssue.external_context, title: externalIssue.title })
            }
        },
    })
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

// Searchable picker of existing provider issues. Search state lives in externalIssueSearchLogic;
// this component only bridges the LemonField value/onChange to the selected issue.
function ExistingIssueSelect({
    integrationId,
    kind,
    value,
    onChange,
}: {
    integrationId: number
    kind: ErrorTrackingIntegrationKind
    value?: ErrorTrackingExternalIssueResultApi | null
    onChange?: (value: ErrorTrackingExternalIssueResultApi | null) => void
}): JSX.Element {
    const requiresRepository = kind === 'github'
    const logic = externalIssueSearchLogic({ integrationId, requiresRepository })
    const { repository, results, resultsLoading } = useValues(logic)
    const { setRepository, inputChanged, issueSelected } = useActions(logic)

    const optionKey = (result: ErrorTrackingExternalIssueResultApi): string => result.url || `${result.id}`
    const selectedKey = value ? optionKey(value) : null
    const options = results.map((result) => ({
        key: optionKey(result),
        label: `${result.title} ${formatExternalIssueId(result.id, kind)}`,
        labelComponent: externalIssueOptionLabel(result, kind),
    }))
    // A results refresh must not visually drop a valid selection, so the selected
    // issue stays in the options even when the fresh results no longer include it.
    if (value && selectedKey && !options.some((option) => option.key === selectedKey)) {
        options.push({
            key: selectedKey,
            label: `${value.title} ${formatExternalIssueId(value.id, kind)}`,
            labelComponent: externalIssueOptionLabel(value, kind),
        })
    }

    return (
        <div className="flex flex-col gap-y-2">
            {requiresRepository && (
                <GitHubRepositoryPicker
                    integrationId={integrationId}
                    value={repository}
                    onChange={(newRepository) => {
                        setRepository(newRepository ?? '')
                        onChange?.(null)
                    }}
                />
            )}
            <LemonInputSelect
                mode="single"
                data-attr="select-existing-issue"
                popoverClassName="[&_.LemonButton__content>span]:grow [&_.LemonButton__content>span]:min-w-0"
                placeholder={
                    requiresRepository && !repository ? 'Select a repository first...' : 'Search for an issue...'
                }
                disabled={requiresRepository && !repository}
                loading={resultsLoading}
                // Results are already filtered by the provider; the client-side fuzzy filter
                // would hide valid matches whose titles don't contain the raw query text.
                disableFiltering
                options={options}
                value={selectedKey ? [selectedKey] : []}
                onInputChange={(query) => {
                    inputChanged(query)
                    // Typing a new query invalidates the current pick - submitting while results
                    // refresh must not link the previously selected issue.
                    if (query.trim() && value) {
                        onChange?.(null)
                    }
                }}
                onChange={(selection) => {
                    const key = selection[0] ?? null
                    const selected =
                        results.find((result) => optionKey(result) === key) ??
                        (key !== null && key === selectedKey ? value : null)
                    if (selected) {
                        issueSelected()
                    }
                    onChange?.(selected ?? null)
                }}
            />
        </div>
    )
}

function externalIssueOptionLabel(
    issue: ErrorTrackingExternalIssueResultApi,
    kind: ErrorTrackingIntegrationKind
): JSX.Element {
    return (
        <span className="flex items-center justify-between gap-2 min-w-0 w-full">
            <span className="truncate">{issue.title}</span>
            <span className="text-muted flex-shrink-0">{formatExternalIssueId(issue.id, kind)}</span>
        </span>
    )
}

function formatExternalIssueId(id: string, kind: ErrorTrackingIntegrationKind): string {
    return (kind === 'github' || kind === 'gitlab') && !id.startsWith('#') ? `#${id}` : id
}
