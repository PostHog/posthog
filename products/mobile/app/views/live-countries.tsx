import { useLocalSearchParams } from 'expo-router'
import type { ReactElement } from 'react'

import { LiveCountriesScreen } from '@/features/live/LiveCountriesScreen'

export default function LiveCountriesRoute(): ReactElement {
    const { country } = useLocalSearchParams<{ country?: string }>()
    // The screen ignores a code that has no visitors, so any value is safe to pass.
    return <LiveCountriesScreen country={typeof country === 'string' && country !== '' ? country : null} />
}
