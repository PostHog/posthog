import { useActions, useValues } from 'kea'

import { Button, CardGroup, Field, FieldDescription, FieldLabel, Input } from '@posthog/quill'

import { ImportWizardOption } from './ImportWizardOption'
import { ImportWizardStepHeading } from './ImportWizardStepHeading'
import { sentryMigrationLogic } from './sentryMigrationLogic'

export function SentryLocationStep(): JSX.Element {
    const { hosting, baseUrl } = useValues(sentryMigrationLogic)
    const { selectHosting, setBaseUrl, confirmLocation } = useActions(sentryMigrationLogic)
    const urlProblem = baseUrl.trim().startsWith('https://') ? undefined : 'Enter a URL that starts with https://'

    return (
        <>
            <ImportWizardStepHeading
                title="Where does your Sentry run?"
                description="PostHog reads your Sentry settings from this address."
            />
            <CardGroup size="sm">
                <ImportWizardOption
                    title="Sentry cloud"
                    description="sentry.io, in the US or EU region"
                    selected={hosting === 'cloud'}
                    onClick={() => selectHosting('cloud')}
                    dataAttr="error-tracking-import-sentry-cloud"
                />
                <ImportWizardOption
                    title="Self-hosted"
                    description="Your own Sentry server"
                    selected={hosting === 'self_hosted'}
                    onClick={() => selectHosting('self_hosted')}
                    dataAttr="error-tracking-import-sentry-self-hosted"
                />
            </CardGroup>
            {hosting === 'self_hosted' && (
                <form
                    className="flex flex-col gap-4"
                    onSubmit={(event) => {
                        event.preventDefault()
                        if (!urlProblem) {
                            confirmLocation()
                        }
                    }}
                >
                    <Field>
                        <FieldLabel htmlFor="sentry-migration-url">Sentry URL</FieldLabel>
                        <Input
                            id="sentry-migration-url"
                            value={baseUrl}
                            onChange={(event) => setBaseUrl(event.target.value)}
                            placeholder="https://sentry.example.com"
                            data-attr="error-tracking-import-sentry-url"
                        />
                        <FieldDescription>Use the address you open Sentry at.</FieldDescription>
                    </Field>
                    <div>
                        <Button type="submit" variant="primary" disabledReason={urlProblem}>
                            Continue
                        </Button>
                    </div>
                </form>
            )}
        </>
    )
}
