import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { Scene } from 'scenes/sceneTypes'
import { sceneConfigurations } from 'scenes/scenes'

import { PRODUCT_KEY, PRODUCT_THING_NAME } from '../RevenueAnalyticsScene'
import { InlineSetup, InlineSetupView } from './InlineSetup'

interface OnboardingProps {
    closeOnboarding: () => void
    initialSetupView?: InlineSetupView // NOTE: This should NOT be used except for testing purposes (storybook)
}

export const Onboarding = ({ initialSetupView, closeOnboarding }: OnboardingProps): JSX.Element => {
    return (
        <div className="space-y-6">
            <ProductIntroduction
                isEmpty
                productName={sceneConfigurations[Scene.RevenueAnalytics].name || ''}
                productKey={PRODUCT_KEY}
                thingName={PRODUCT_THING_NAME}
                description={sceneConfigurations[Scene.RevenueAnalytics].description || ''}
                titleOverride="Get started with Revenue Analytics"
            />

            <InlineSetup initialSetupView={initialSetupView} closeOnboarding={closeOnboarding} />
        </div>
    )
}
