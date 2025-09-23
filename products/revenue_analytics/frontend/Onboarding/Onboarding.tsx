import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'

import { PRODUCT_DESCRIPTION, PRODUCT_KEY, PRODUCT_NAME, PRODUCT_THING_NAME } from '../RevenueAnalyticsScene'
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
                productName={PRODUCT_NAME}
                productKey={PRODUCT_KEY}
                thingName={PRODUCT_THING_NAME}
                description={PRODUCT_DESCRIPTION}
                titleOverride="Get started with Revenue Analytics"
            />

            <InlineSetup initialSetupView={initialSetupView} closeOnboarding={closeOnboarding} />
        </div>
    )
}
