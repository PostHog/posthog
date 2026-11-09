import { useRouter } from 'expo-router'
import { type ReactElement, type ReactNode, useCallback } from 'react'
import { View } from 'react-native'

import { currentDefaultPageHref } from '@/features/settings/defaultPageStore'
import { ChartSelectionProvider } from '@/ui/chart/selection/ChartSelectionProvider'
import { OverlayHost } from '@/ui/OverlayPortal'
import { createStyles } from '@/ui/theme'

import { ChartSheetsProvider } from '../pointSheet/ChartSheetsProvider'

interface ViewScreenFrameProps {
    children: ReactNode
    /** The floating top chrome. It sits inside the chart selection, so a tap on it closes a pinned tooltip. */
    chrome: ReactNode
    /** False for a screen drawn as a navigation tab, which already sits under the tabs layout's overlay host. */
    overlayHost?: boolean
}

/**
 * The frame of a dashboard, insight or web analytics screen. View screens are pushed above the tabs, outside the tab
 * bar's overlay host, so the frame brings its own host for sheets and toasts. The sheets draw outside the chart
 * selection, so the pinned tooltip stays behind an open Point sheet.
 */
export function ViewScreenFrame({ children, chrome, overlayHost = true }: ViewScreenFrameProps): ReactElement {
    const styles = useStyles()
    const screen = (
        <View style={styles.screen} testID="view-screen">
            <ChartSheetsProvider>
                <ChartSelectionProvider>
                    {children}
                    {chrome}
                </ChartSelectionProvider>
            </ChartSheetsProvider>
        </View>
    )
    return overlayHost ? <OverlayHost>{screen}</OverlayHost> : screen
}

/** Back to the previous screen, or to the default page when a deep link opened the view. */
export function useViewBack(): () => void {
    const router = useRouter()
    return useCallback(() => {
        if (router.canGoBack()) {
            router.back()
        } else {
            router.replace(currentDefaultPageHref())
        }
    }, [router])
}

const useStyles = createStyles(({ colors }) => ({
    screen: {
        flex: 1,
        backgroundColor: colors.background,
    },
}))
