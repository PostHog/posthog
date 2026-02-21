import { useActions, useValues } from 'kea'

import { HogFunctionIcon } from 'scenes/hog-functions/configuration/HogFunctionIcon'

import { WizardDestination, errorTrackingAlertWizardLogic } from '../errorTrackingAlertWizardLogic'
import { WizardCard } from './WizardCard'

export function DestinationStep(): JSX.Element {
    const { destinations, usedDestinationKeys, existingAlertsLoading } = useValues(errorTrackingAlertWizardLogic)
    const { setDestinationKey } = useActions(errorTrackingAlertWizardLogic)

    if (existingAlertsLoading) {
        return (
            <div className="space-y-4">
                <div>
                    <h2 className="text-xl font-semibold mb-1">Where should we send alerts?</h2>
                    <p className="text-secondary text-sm">Choose your preferred notification channel</p>
                </div>
                <div className="space-y-3">
                    {[1, 2, 3].map((i) => (
                        <div
                            key={i}
                            className="group relative text-left rounded-lg border border-border bg-bg-light p-5 w-full animate-pulse"
                        >
                            <div className="flex items-center gap-4">
                                <div className="shrink-0 w-10 h-10 rounded bg-border" />
                                <div>
                                    <h3 className="font-semibold text-base mb-0.5 relative">
                                        <span className="invisible">Placeholder</span>
                                        <span className="absolute inset-y-0 left-0 flex items-center">
                                            <span className="h-3 w-24 rounded bg-border block" />
                                        </span>
                                    </h3>
                                    <p className="text-sm mb-0 relative">
                                        <span className="invisible">Placeholder description</span>
                                        <span className="absolute inset-y-0 left-0 flex items-center">
                                            <span className="h-2.5 w-48 rounded bg-border block" />
                                        </span>
                                    </p>
                                </div>
                            </div>
                        </div>
                    ))}
                </div>
            </div>
        )
    }

    return (
        <div className="space-y-4">
            <div>
                <h2 className="text-xl font-semibold mb-1">Where should we send alerts?</h2>
                <p className="text-secondary text-sm">Choose your preferred notification channel</p>
            </div>
            <div className="space-y-3">
                {destinations.map((destination: WizardDestination) => (
                    <WizardCard
                        key={destination.key}
                        icon={<HogFunctionIcon src={destination.icon} size="medium" />}
                        name={destination.name}
                        description={destination.description}
                        badge={usedDestinationKeys.has(destination.key) ? 'Previously used' : undefined}
                        onClick={() => setDestinationKey(destination.key)}
                    />
                ))}
            </div>
        </div>
    )
}
