import type { ReactElement, ReactNode } from 'react'
import { ReservedRegionsProvider } from 'react-native-reserved-regions'
import { SafeAreaView } from 'react-native-safe-area-context'

import { OverlayHost } from './OverlayPortal'
import { SceneFrame } from './SceneFrame'

export function MobileScene({ children }: { children: ReactNode }): ReactElement {
    return (
        <SafeAreaView edges={['left', 'right']} style={{ flex: 1 }}>
            <ReservedRegionsProvider style={{ flex: 1 }}>
                <SceneFrame>
                    <OverlayHost>{children}</OverlayHost>
                </SceneFrame>
            </ReservedRegionsProvider>
        </SafeAreaView>
    )
}
