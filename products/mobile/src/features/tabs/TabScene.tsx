import { useIsFocused } from 'expo-router'
import type { ReactElement, ReactNode } from 'react'
import { Platform } from 'react-native'
import { MobileScene } from '@/ui/MobileScene'
import { OverlayPortal } from '@/ui/OverlayPortal'
import { useNativeRail } from '@/ui/useNativeRail'
import { TabsChrome } from './TabsChrome'
import { TabsNavigation } from './TabsNavigation'
import { type TabKey, useTabHeaderStore } from './tabHeaderStore'

export function TabScene({ children, tab }: { children: ReactNode; tab: TabKey }): ReactElement {
    const routeFocused = useIsFocused()
    const nativeRail = useNativeRail()
    const selectedTab = useTabHeaderStore((state) => state.focused)
    const focused = routeFocused && selectedTab === tab
    if (Platform.OS !== 'ios') return <>{children}</>
    return (
        <MobileScene>
            {children}
            {focused ? <TabsChrome /> : null}
            {focused && !nativeRail ? (
                <OverlayPortal>
                    <TabsNavigation tab={tab} />
                </OverlayPortal>
            ) : null}
        </MobileScene>
    )
}
