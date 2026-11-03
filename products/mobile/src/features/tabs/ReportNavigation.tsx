import { useRouter } from 'expo-router'
import type { ReactElement } from 'react'

import { useMobileProductFlags } from '@/lib/featureFlags'
import { BottomBar } from './BottomBar'
import { useNavPins } from './navPinStore'

export function ReportNavigation(): ReactElement {
    const router = useRouter()
    const pins = useNavPins()
    const flags = useMobileProductFlags()
    return (
        <BottomBar
            selected="home"
            pins={pins.filter((pin) => flags[pin])}
            onHome={() => router.navigate('/inbox')}
            onChats={() => router.navigate('/chats')}
            onViews={() => router.navigate('/views')}
            onPin={(pin) => router.navigate(pin === 'errors' ? '/errors' : '/replay')}
        />
    )
}
