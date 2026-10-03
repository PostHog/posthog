import { useMountedLogic } from 'kea'

import { audienceSetupLogic } from './audienceSetupLogic'
import { ApiKeyStep } from './steps/ApiKeyStep'
import { EngagementEventsStep } from './steps/EngagementEventsStep'
import { SendPreferencesStep } from './steps/SendPreferencesStep'

const SETUP_STEPS = [
    { key: 'api-key', Step: ApiKeyStep },
    { key: 'send-preferences', Step: SendPreferencesStep },
    { key: 'engagement-events', Step: EngagementEventsStep },
]

export function AudienceSetup(): JSX.Element {
    useMountedLogic(audienceSetupLogic)

    return (
        <div className="flex flex-col gap-6 max-w-3xl min-w-0" data-attr="audience-setup">
            <div className="flex flex-col gap-1">
                <h2 className="text-lg font-semibold m-0">Bring your recipients into PostHog</h2>
                <p className="text-secondary m-0">
                    Audience shows the email addresses you can send to. Send preferences from your backend, and each
                    address shows up here with its topics, its suppression state and the persons that hold it.
                </p>
            </div>
            <ol className="flex flex-col gap-4 list-none m-0 p-0">
                {SETUP_STEPS.map(({ key, Step }, index) => (
                    <li key={key} className="flex flex-col gap-2">
                        <span className="text-secondary text-xs font-semibold">Step {index + 1}</span>
                        <Step />
                    </li>
                ))}
            </ol>
        </div>
    )
}
