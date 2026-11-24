import { useActions, useValues } from 'kea'

import { Button, CardGroup, Field, FieldDescription, FieldLabel, Input } from '@posthog/quill'

import { QuillWizardCard } from 'lib/components/Alerting/AlertWizard/steps/QuillWizardCard'

import { QuillImportWizardStepHeading } from './QuillImportWizardStepHeading'
import { sentryMigrationLogic } from './sentryMigrationLogic'

export function QuillSentryLocationStep(): JSX.Element {
    const { hosting, baseUrl } = useValues(sentryMigrationLogic)
    const { selectHosting, setBaseUrl, confirmLocation } = useActions(sentryMigrationLogic)
    const urlProblem = baseUrl.trim().startsWith('https://') ? undefined : 'Enter a URL that starts with https://'

    return (
        <>
            <QuillImportWizardStepHeading
                title="Where does your Sentry run?"
                description="PostHog reads your Sentry settings from this address."
            />
            <CardGroup size="sm">
                <QuillWizardCard
                    name="Sentry cloud"
                    description="sentry.io, in the US or EU region"
                    badge={hosting === 'cloud' ? 'Selected' : undefined}
                    onClick={() => selectHosting('cloud')}
                    data-attr="error-tracking-import-sentry-cloud"
                />
                <QuillWizardCard
                    name="Self-hosted"
                    description="Your own Sentry server"
                    badge={hosting === 'self_hosted' ? 'Selected' : undefined}
                    onClick={() => selectHosting('self_hosted')}
                    data-attr="error-tracking-import-sentry-self-hosted"
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
                        <FieldLabel htmlFor="error-tracking-import-sentry-url">Sentry URL</FieldLabel>
                        <Input
                            id="error-tracking-import-sentry-url"
                            value={baseUrl}
                            onChange={(event) => setBaseUrl(event.target.value)}
                            placeholder="https://sentry.example.com"
                            data-attr="error-tracking-import-sentry-url"
                        />
                        <FieldDescription>Use the address you open Sentry at.</FieldDescription>
                    </Field>
                    <div>
                        <Button variant="primary" type="submit" disabledReason={urlProblem}>
                            Continue
                        </Button>
                    </div>
                </form>
            )}
        </>
    )
}
