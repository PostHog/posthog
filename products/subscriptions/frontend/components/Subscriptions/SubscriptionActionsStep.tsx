import { useActions, useValues } from 'kea'

import { ProactiveSubscriptionFields } from './ProactiveSubscriptionFields'
import { subscriptionLogic } from './subscriptionLogic'
import type { SubscriptionForm, SubscriptionLogicProps } from './subscriptionLogic'

interface SubscriptionActionsStepProps {
    logicProps: SubscriptionLogicProps
    subscription: SubscriptionForm
}

export function SubscriptionActionsStep({ logicProps, subscription }: SubscriptionActionsStepProps): JSX.Element {
    const {
        proactiveConfigurationOptions,
        proactiveConfigurationOptionsLoading,
        proactiveConfigurationOptionsLoadFailed,
    } = useValues(subscriptionLogic(logicProps))
    const { loadProactiveConfigurationOptions, selectProactiveRepository } = useActions(subscriptionLogic(logicProps))

    return (
        <ProactiveSubscriptionFields
            proactiveConfig={subscription.proactive_config}
            options={proactiveConfigurationOptions}
            optionsLoading={proactiveConfigurationOptionsLoading}
            optionsLoadFailed={proactiveConfigurationOptionsLoadFailed}
            show={Boolean(logicProps.proactiveSettingsEnabled)}
            onSelectRepository={selectProactiveRepository}
            onRetry={loadProactiveConfigurationOptions}
        />
    )
}
