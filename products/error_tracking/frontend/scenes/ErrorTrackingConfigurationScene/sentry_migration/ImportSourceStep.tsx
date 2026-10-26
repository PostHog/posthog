import { useActions } from 'kea'

import { CardGroup } from '@posthog/quill'

import { ImportWizardOption } from './ImportWizardOption'
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
            <CardGroup size="sm">
                <ImportWizardOption
                    title="Sentry"
                    description="Inbound filters and client key rate limits"
                    icon={<img src="/static/services/sentry.png" alt="" className="size-8 shrink-0" />}
                    onClick={() => selectSource('sentry')}
                    dataAttr="error-tracking-import-source-sentry"
                />
            </CardGroup>
        </>
    )
}
