import { Redirect } from 'expo-router'
import type { ReactElement } from 'react'

import { type FeatureFlagKey, useFeatureFlag } from '@/lib/featureFlags'

import { currentDefaultPageHref } from '../settings/defaultPageStore'

export function MobileProductGate({ flag, children }: { flag: FeatureFlagKey; children: ReactElement }): ReactElement {
    return useFeatureFlag(flag) ? children : <Redirect href={currentDefaultPageHref()} />
}
