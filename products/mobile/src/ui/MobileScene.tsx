import { type ReactElement, type ReactNode, useMemo } from 'react'
import { useReservedRegions } from 'react-native-reserved-regions'
import { SafeAreaView, useSafeAreaInsets } from 'react-native-safe-area-context'

import { DisplayRegionContext } from './displayRegionContext'
import { OverlayHost } from './OverlayPortal'
import { SceneFrame } from './SceneFrame'

export function MobileScene({ children }: { children: ReactNode }): ReactElement {
    const regions = useReservedRegions()
    const { left } = useSafeAreaInsets()
    // Measure outside navigator transitions; a translated scene can otherwise retain an offset fold frame.
    const localRegions = useMemo(
        () => regions.map((region) => ({ ...region, frame: { ...region.frame, x: region.frame.x - left } })),
        [regions, left]
    )
    return (
        <SafeAreaView edges={['left', 'right']} style={{ flex: 1 }}>
            <DisplayRegionContext.Provider value={localRegions}>
                <SceneFrame>
                    <OverlayHost>{children}</OverlayHost>
                </SceneFrame>
            </DisplayRegionContext.Provider>
        </SafeAreaView>
    )
}
