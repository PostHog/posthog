import { BuiltLogic, useValues } from 'kea'
import { FormContext } from 'kea-forms'
import { useContext, useEffect } from 'react'

import { LemonInputSelect } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

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

    const { users, usersLoading } = useValues(externalIssueAssigneesLogic({ integrationId, kind, scope }))

    // Someone assignable in one team or repository may not be assignable in the next one.
    useEffect(() => {
        ;(formLogic as BuiltLogic).actions.setFormValue('assignees', [])
    }, [formLogic, scope])

    const placeholder =
        scopeField && !scope
            ? scopeField.placeholder
            : !usersLoading && users === null
              ? "Couldn't load users"
              : 'Unassigned'

    return (
        <LemonField name="assignees" label="Assignee" showOptional>
            <LemonInputSelect
                mode="single"
                data-attr="external-issue-assignee"
                placeholder={placeholder}
                options={(users ?? []).map((user) => ({ key: user.id, label: user.name }))}
                loading={usersLoading}
                disabled={!!scopeField && !scope}
            />
        </LemonField>
    )
}
