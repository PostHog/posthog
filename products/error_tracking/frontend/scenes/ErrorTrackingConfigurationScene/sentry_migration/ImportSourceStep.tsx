import { useActions } from 'kea'

import { WizardCard } from 'lib/components/Alerting/AlertWizard/steps/WizardCard'

import { ImportWizardStepHeading } from './ImportWizardStepHeading'
import { sentryMigrationLogic } from './sentryMigrationLogic'

export function ImportSourceStep(): JSX.Element {
    const { selectSource } = useActions(sentryMigrationLogic)

    return (
        <>
            <ImportWizardStepHeading
                title="Which tool are you moving from?"
                description="PostHog reads that tool's settings and shows what each one becomes before you import anything."
            />
            <WizardCard
                icon={<img src="/static/services/sentry.png" alt="" className="size-8" />}
                name="Sentry"
                description="Inbound filters and client key rate limits"
                onClick={() => selectSource('sentry')}
                data-attr="error-tracking-import-source-sentry"
            />
        </>
    )
}
