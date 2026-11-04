import type { ReactNode } from 'react'
import { Platform } from 'react-native'

import { MobileScene } from '@/ui/MobileScene'

import { TabsChrome } from './TabsChrome'

export function TabScene({ children }: { children: ReactNode }): ReactNode {
    return Platform.OS === 'ios' ? (
        <MobileScene>
            {children}
            <TabsChrome />
        </MobileScene>
    ) : (
        children
    )
}
