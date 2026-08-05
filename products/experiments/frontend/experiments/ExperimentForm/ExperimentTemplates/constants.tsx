import { IconBell, IconBox, IconGraph, IconTarget, IconTrending, IconUser } from '@posthog/icons'

export const EXPERIMENT_TEMPLATE_IDS = {
    CHECKOUT_FLOW: 'checkout-flow',
    PRICING_PAGE: 'pricing-page',
    ONBOARDING: 'onboarding',
    PRODUCT_PAGE: 'product-page',
    FEATURE_ADOPTION: 'feature-adoption',
    MESSAGING: 'messaging',
} as const

export type ExperimentTemplateId = (typeof EXPERIMENT_TEMPLATE_IDS)[keyof typeof EXPERIMENT_TEMPLATE_IDS]

export type ExperimentTemplate = {
    id: ExperimentTemplateId
    name: string
    description: string
    experimentGoal: string
    icon: React.ReactNode
    metrics: { name: string }[]
}

export const EXPERIMENT_TEMPLATES: ExperimentTemplate[] = [
    {
        id: EXPERIMENT_TEMPLATE_IDS.CHECKOUT_FLOW,
        name: 'Checkout Flow Optimization',
        description: 'Increase purchase completion rate',
        experimentGoal: 'Optimize conversion from checkout start to completed purchase',
        icon: <IconTrending className="text-2xl" />,
        metrics: [
            { name: 'Conversion rate' },
            { name: 'Average order value' },
            { name: 'Checkout abandonment rate' },
            { name: 'Time to purchase' },
        ],
    },
    {
        id: EXPERIMENT_TEMPLATE_IDS.PRICING_PAGE,
        name: 'Pricing Page Testing',
        description: 'Optimize plan selection and signup rate',
        experimentGoal: 'Increase conversion from pricing page view to completed signup',
        icon: <IconGraph className="text-2xl" />,
        metrics: [
            { name: 'Click-through rate' },
            { name: 'Plan selection rate' },
            { name: 'Conversion to signup' },
            { name: 'Revenue per visitor' },
        ],
    },
    {
        id: EXPERIMENT_TEMPLATE_IDS.ONBOARDING,
        name: 'Onboarding Activation',
        description: 'Increase trial-to-paid conversion',
        experimentGoal: 'Optimize activation flow and trial-to-paid conversion',
        icon: <IconUser className="text-2xl" />,
        metrics: [
            { name: 'Activation rate' },
            { name: 'Time to first value' },
            { name: 'Trial-to-paid conversion' },
            { name: 'Feature adoption' },
        ],
    },
    {
        id: EXPERIMENT_TEMPLATE_IDS.PRODUCT_PAGE,
        name: 'Product Page Conversion',
        description: 'Increase add-to-cart and purchase rates',
        experimentGoal: 'Optimize product page to drive add-to-cart and purchases',
        icon: <IconBox className="text-2xl" />,
        metrics: [
            { name: 'Add-to-cart rate' },
            { name: 'Purchase conversion rate' },
            { name: 'Revenue per visitor' },
            { name: 'Bounce rate' },
        ],
    },
    {
        id: EXPERIMENT_TEMPLATE_IDS.FEATURE_ADOPTION,
        name: 'Feature Adoption',
        description: 'Drive engagement with new/core features',
        experimentGoal: 'Increase discovery and usage of key features',
        icon: <IconTarget className="text-2xl" />,
        metrics: [
            { name: 'Feature adoption rate' },
            { name: 'Repeat usage rate' },
            { name: 'Time to first use' },
            { name: 'User retention' },
        ],
    },
    {
        id: EXPERIMENT_TEMPLATE_IDS.MESSAGING,
        name: 'In-App Messaging & Notification Testing',
        description: 'Optimize engagement with notifications',
        experimentGoal: 'Maximize engagement with notifications, tooltips, and CTAs',
        icon: <IconBell className="text-2xl" />,
        metrics: [
            { name: 'Click-through rate' },
            { name: 'Engagement rate' },
            { name: 'Dismissal rate' },
            { name: 'Time to action' },
            { name: 'Conversion from notification' },
        ],
    },
]
