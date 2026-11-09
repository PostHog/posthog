import { useRouter } from 'expo-router'
import type { ReactElement } from 'react'

import { useMobileProductFlags } from '@/lib/featureFlags'
import { BottomBar } from './BottomBar'
import { openNavTarget } from './navPinRoutes'
import { useNavPins } from './navPinStore'
import { navPinEnabled } from './visibleNavPins'

export function ReportNavigation(): ReactElement {
    const router = useRouter()
    const pins = useNavPins()
    const flags = useMobileProductFlags()
    return (
        <BottomBar
            selected="home"
            pins={pins.filter((pin) => navPinEnabled(pin, flags))}
            onHome={() => router.navigate('/inbox')}
            onChats={() => router.navigate('/chats')}
            onViews={() => router.navigate('/views')}
            onPin={(pin) => openNavTarget(router, pin, true)}
        />
    )
}
