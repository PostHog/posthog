import { useActions } from 'kea'

import { CardGroup } from '@posthog/quill'

import { QuillWizardCard } from 'lib/components/Alerting/AlertWizard/steps/QuillWizardCard'

import { QuillImportWizardStepHeading } from './QuillImportWizardStepHeading'
import { sentryMigrationLogic } from './sentryMigrationLogic'

export function QuillImportSourceStep(): JSX.Element {
    const { selectSource } = useActions(sentryMigrationLogic)

    return (
        <>
            <QuillImportWizardStepHeading
                title="Which tool are you moving from?"
                description="PostHog reads that tool's settings and shows what each one becomes before you import anything."
            />
            <CardGroup size="sm">
                <QuillWizardCard
                    icon={<img src="/static/services/sentry.png" alt="" className="size-8" />}
                    name="Sentry"
                    description="Inbound filters and client key rate limits"
                    onClick={() => selectSource('sentry')}
                    data-attr="error-tracking-import-source-sentry"
                />
            </CardGroup>
        </>
    )
}
