import type { ExtensionContextValue } from '@stripe/ui-extension-sdk/context'

import BrandIcon from './views/logomark.svg'

export const BRAND_COLOR = '#F7A501'

export interface AppConstants {
    POSTHOG_US_BASE_URL: string
    POSTHOG_EU_BASE_URL: string
    POSTHOG_DASHBOARD_URL: string
    POSTHOG_NEW_SOURCE_URL: string
}

export function getConstants(environment: ExtensionContextValue['environment']): AppConstants {
    return environment.constants as unknown as AppConstants
}

export { BrandIcon }
