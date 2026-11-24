import { useActions, useValues } from 'kea'

import { LemonButton, LemonInput } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

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
                <LemonField.Pure
                    label="Sentry auth token"
                    help={
                        <>
                            PostHog uses the token only to read your Sentry settings from{' '}
                            <span translate="no">{baseUrl}</span> and doesn't store it.
                        </>
                    }
                >
                    <LemonInput
                        type="password"
                        value={authToken}
                        onChange={setAuthToken}
                        autoComplete="off"
                        data-attr="error-tracking-sentry-migration-token"
                    />
                </LemonField.Pure>
                <div>
                    <LemonButton
                        type="primary"
                        htmlType="submit"
                        loading={projectsLoading}
                        disabledReason={disabledReason}
                        data-attr="error-tracking-sentry-migration-connect"
                    >
                        Connect to Sentry
                    </LemonButton>
                </div>
            </form>
        </>
    )
}
