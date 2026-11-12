import { useLocalSearchParams } from 'expo-router'
import type { ReactElement } from 'react'

import { LiveCountriesScreen } from '@/features/live/LiveCountriesScreen'

export default function LiveCountriesRoute(): ReactElement {
    const { country } = useLocalSearchParams<{ country?: string }>()
    // The screen drops a code that is not in its first countries, so a stale code selects nothing.
    const code = typeof country === 'string' && /^[a-z]{2}$/i.test(country) ? country.toUpperCase() : null
    return <LiveCountriesScreen country={code} />
}
