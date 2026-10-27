import { useActions, useValues } from 'kea'

import { LemonButton, LemonInput } from '@posthog/lemon-ui'

import { WizardCard } from 'lib/components/Alerting/AlertWizard/steps/WizardCard'
import { LemonField } from 'lib/lemon-ui/LemonField'

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
            <div className="flex flex-col gap-3">
                <WizardCard
                    name="Sentry cloud"
                    description="sentry.io, in the US or EU region"
                    badge={hosting === 'cloud' ? 'Selected' : undefined}
                    onClick={() => selectHosting('cloud')}
                    data-attr="error-tracking-import-sentry-cloud"
                />
                <WizardCard
                    name="Self-hosted"
                    description="Your own Sentry server"
                    badge={hosting === 'self_hosted' ? 'Selected' : undefined}
                    onClick={() => selectHosting('self_hosted')}
                    data-attr="error-tracking-import-sentry-self-hosted"
                />
            </div>
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
                    <LemonField.Pure label="Sentry URL" help="Use the address you open Sentry at.">
                        <LemonInput
                            value={baseUrl}
                            onChange={setBaseUrl}
                            placeholder="https://sentry.example.com"
                            data-attr="error-tracking-import-sentry-url"
                        />
                    </LemonField.Pure>
                    <div>
                        <LemonButton type="primary" htmlType="submit" disabledReason={urlProblem}>
                            Continue
                        </LemonButton>
                    </div>
                </form>
            )}
        </>
    )
}
