import { useActions, useValues } from 'kea'

import { Button, Field, FieldDescription, FieldGroup, FieldLabel, Input } from '@posthog/quill'

import { errorTrackingEditAccessDisabledReason } from '../../../utils'
import { SENTRY_CLOUD_URL, sentryMigrationLogic } from './sentryMigrationLogic'

export function SentryMigrationConnectForm(): JSX.Element {
    const { authToken, baseUrl, projectsLoading } = useValues(sentryMigrationLogic)
    const { setAuthToken, setBaseUrl, loadProjects } = useActions(sentryMigrationLogic)
    const disabledReason =
        errorTrackingEditAccessDisabledReason() ?? (!authToken.trim() ? 'Enter a Sentry auth token' : undefined)

    return (
        <form
            className="flex w-full max-w-sm flex-col gap-4"
            onSubmit={(event) => {
                event.preventDefault()
                if (!disabledReason && !projectsLoading) {
                    loadProjects()
                }
            }}
        >
            <FieldGroup>
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
                        Create a personal token in Sentry under User settings &gt; Personal tokens, with the org:read
                        and project:read scopes. PostHog uses the token only to read your Sentry settings and doesn't
                        store it.
                    </FieldDescription>
                </Field>
                <Field>
                    <FieldLabel htmlFor="sentry-migration-url">Sentry URL</FieldLabel>
                    <Input
                        id="sentry-migration-url"
                        value={baseUrl}
                        onChange={(event) => setBaseUrl(event.target.value)}
                        placeholder={SENTRY_CLOUD_URL}
                    />
                    <FieldDescription>Change this only if you host Sentry yourself.</FieldDescription>
                </Field>
            </FieldGroup>
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
    )
}
