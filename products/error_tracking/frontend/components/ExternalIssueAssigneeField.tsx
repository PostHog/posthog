import { BuiltLogic, useActions, useValues } from 'kea'
import { FormContext } from 'kea-forms'
import { useContext, useEffect } from 'react'

import { LemonInputSelect } from '@posthog/lemon-ui'

import api from 'lib/api'
import { useIntegrationManagementRestriction } from 'lib/integrations/integrationPermissions'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { Link } from 'lib/lemon-ui/Link'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'

import { ExternalIssueAssigneeKind, externalIssueAssigneesLogic } from './externalIssueAssigneesLogic'

// The form field holding the team, repository, or project that decides who can be assigned.
const SCOPE_FIELDS: Record<ExternalIssueAssigneeKind, { field: string; placeholder: string } | null> = {
    linear: { field: 'teamIds', placeholder: 'Choose a team first' },
    github: { field: 'repositories', placeholder: 'Choose a repository first' },
    jira: { field: 'projectKeys', placeholder: 'Choose a project first' },
    gitlab: null,
}

export function ExternalIssueAssigneeField({
    integrationId,
    kind,
}: {
    integrationId: number
    kind: ExternalIssueAssigneeKind
}): JSX.Element {
    const { logic: formLogic, formKey } = useContext(FormContext)
    const formValues: Record<string, any> = useValues(formLogic as BuiltLogic)[formKey] ?? {}
    const scopeField = SCOPE_FIELDS[kind]
    const scope: string | null = scopeField ? (formValues[scopeField.field]?.[0] ?? null) : null

    const assigneesLogic = externalIssueAssigneesLogic({ integrationId, kind, scope })
    const { assignees, assigneesLoading, knownUserNames } = useValues(assigneesLogic)
    const { setSearch } = useActions(assigneesLogic)
    const { reportIntegrationConnectClicked } = useActions(eventUsageLogic)
    const restrictedReason = useIntegrationManagementRestriction()

    // Someone assignable in one team or repository may not be assignable in the next one.
    useEffect(() => {
        ;(formLogic as BuiltLogic).actions.setFormValue('assignees', [])
    }, [formLogic, scope])

    const reconnectRequired = !!assignees?.reconnect_required
    const selectedId: string | undefined = formValues.assignees?.[0]
    const options = (assignees?.users ?? []).map((user) => ({ key: user.id, label: user.name }))
    if (selectedId && !options.some((option) => option.key === selectedId) && knownUserNames[selectedId]) {
        options.unshift({ key: selectedId, label: knownUserNames[selectedId] })
    }
    const placeholder =
        scopeField && !scope
            ? scopeField.placeholder
            : reconnectRequired
              ? 'Reconnect to choose an assignee'
              : !assigneesLoading && assignees === null
                ? "Couldn't load users"
                : 'Unassigned'

    return (
        <LemonField
            name="assignees"
            label="Assignee"
            showOptional
            help={
                reconnectRequired ? (
                    restrictedReason ? (
                        'Ask a project admin to reconnect this integration so it can list users.'
                    ) : (
                        <>
                            This connection can't list users.{' '}
                            <Link
                                to={api.integrations.authorizeUrl({ kind, next: window.location.pathname })}
                                disableClientSideRouting
                                onClick={() => reportIntegrationConnectClicked(kind, kind, 'missing_scopes_reconnect')}
                            >
                                Reconnect
                            </Link>{' '}
                            to grant access.
                        </>
                    )
                ) : undefined
            }
        >
            <LemonInputSelect
                mode="single"
                data-attr="external-issue-assignee"
                placeholder={placeholder}
                options={options}
                onInputChange={setSearch}
                disableFiltering
                loading={assigneesLoading}
                disabled={(!!scopeField && !scope) || reconnectRequired}
            />
        </LemonField>
    )
}
