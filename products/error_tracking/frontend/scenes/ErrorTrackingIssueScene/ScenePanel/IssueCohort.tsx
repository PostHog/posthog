import { useAsyncActions } from 'kea'
import { useCallback } from 'react'

import { LemonDialog, LemonInput, LemonTextArea, Link, lemonToast } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { urls } from 'scenes/urls'

import { ScenePanelLabel } from '~/layout/scenes/SceneLayout'
import { ErrorTrackingIssueCohort, ErrorTrackingRelationalIssue } from '~/queries/schema/schema-general'

import { issueActionsLogic } from 'products/error_tracking/frontend/components/IssueActions/issueActionsLogic'

export function IssueCohort({ issue }: { issue: ErrorTrackingRelationalIssue }): JSX.Element {
    const cohort = issue.cohort
    return (
        <ScenePanelLabel title="Cohort">
            {cohort ? <IssueCohortDisplay issueId={issue.id} cohort={cohort} /> : <IssueCohortCreate issue={issue} />}
        </ScenePanelLabel>
    )
}

function IssueCohortCreate({ issue }: { issue: ErrorTrackingRelationalIssue }): JSX.Element {
    const { createIssueCohort } = useAsyncActions(issueActionsLogic)

    const onCreate = useCallback(
        async (name, description) => {
            await createIssueCohort(issue.id, name, description)
            lemonToast.success(`Cohort created`)
        },
        [issue, createIssueCohort]
    )
    return (
        <ButtonPrimitive variant="panel" fullWidth onClick={() => createIssueCohortForm(issue, onCreate)}>
            Create Cohort
        </ButtonPrimitive>
    )
}

type IssueCohortFormHandler = (name: string, description?: string) => void

function createIssueCohortForm(issue: ErrorTrackingRelationalIssue, onSubmit: IssueCohortFormHandler): void {
    LemonDialog.openForm({
        title: 'Create Cohort',
        shouldAwaitSubmit: true,
        initialValues: {
            cohortName: `Impacted by Issue #${issue.id.substring(0, 8)}`,
            cohortDescription: `${issue.name}: ${issue.description ? issue.description.substring(0, 200) : undefined}`,
        },
        content: (
            <div className="flex flex-col gap-y-2 w-[600px]">
                <LemonField name="cohortName" label="Cohort Name">
                    <LemonInput data-attr="cohort-name" placeholder="Cohort name" size="small" />
                </LemonField>
                <LemonField name="cohortDescription" label="Cohort Description">
                    <LemonTextArea data-attr="cohort-description" placeholder="Cohort description" />
                </LemonField>
            </div>
        ),
        errors: {
            cohortName: (name) => (!name ? 'You must enter a title' : undefined),
        },
        onSubmit: ({ cohortName, cohortDescription }) => {
            return onSubmit(cohortName, cohortDescription)
        },
    })
}

function IssueCohortDisplay({ cohort }: { issueId: string; cohort: ErrorTrackingIssueCohort }): JSX.Element {
    return (
        <Link to={urls.cohort(cohort.id)} tooltip="Edit Cohort" target="_blank">
            <ButtonPrimitive variant="panel" fullWidth>
                {cohort.name}
            </ButtonPrimitive>
        </Link>
    )
}
