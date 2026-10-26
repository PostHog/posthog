import { useActions, useValues } from 'kea'

import { Button, Field, FieldDescription, FieldLabel, Input } from '@posthog/quill'

import { errorTrackingEditAccessDisabledReason } from '../../../utils'
import { ImportWizardStepHeading } from './ImportWizardStepHeading'
import { sentryMigrationLogic } from './sentryMigrationLogic'

export function SentryTokenStep(): JSX.Element {
    const { authToken, baseUrl, projectsLoading } = useValues(sentryMigrationLogic)
    const { setAuthToken, loadProjects } = useActions(sentryMigrationLogic)
    const disabledReason =
        errorTrackingEditAccessDisabledReason() ?? (!authToken.trim() ? 'Enter a Sentry auth token' : undefined)

    return (
        <>
            <ImportWizardStepHeading
                title="Connect to Sentry"
                description={
                    <>
                        Create a personal token in Sentry under User settings &gt; Personal tokens, with the org:read
                        and project:read scopes.
                    </>
                }
            />
            <form
                className="flex flex-col gap-4"
                onSubmit={(event) => {
                    event.preventDefault()
                    if (!disabledReason && !projectsLoading) {
                        loadProjects()
                    }
                }}
            >
                <Field>
                    <FieldLabel htmlFor="sentry-migration-token">Sentry auth token</FieldLabel>
                    <Input
                        id="sentry-migration-token"
                        type="password"
                        value={authToken}
                        onChange={(event) => setAuthToken(event.target.value)}
                        autoComplete="off"
                        data-attr="error-tracking-sentry-migration-token"
                    />
                    <FieldDescription>
                        PostHog uses the token only to read your Sentry settings from{' '}
                        <span translate="no">{baseUrl}</span> and doesn't store it.
                    </FieldDescription>
                </Field>
                <div>
                    <Button
                        type="submit"
                        variant="primary"
                        loading={projectsLoading}
                        disabledReason={disabledReason}
                        data-attr="error-tracking-sentry-migration-connect"
                    >
                        Connect to Sentry
                    </Button>
                </div>
            </form>
        </>
    )
}
