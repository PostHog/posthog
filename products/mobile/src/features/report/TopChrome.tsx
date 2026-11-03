import type { ReactElement } from 'react'
import { ActivityIndicator, View } from 'react-native'
import Animated, { FadeIn, FadeOut } from 'react-native-reanimated'
import { ChevronLeftIcon } from '@/ui/icons/ChevronLeftIcon'
import { ChevronRightIcon } from '@/ui/icons/ChevronRightIcon'
import { ScreenChrome } from '@/ui/ScreenChrome'
import { SegmentedPill } from '@/ui/SegmentedPill'
import { SCREEN_CHROME_BOTTOM, SCREEN_CONTENT_TOP, screenLayout } from '@/ui/screenLayout'
import { createStyles, useColors } from '@/ui/theme'
import { iconSizes, motion } from '@/ui/tokens'
import type { ScrollTitle } from '@/ui/useScrollTitle'

export const HEADLINE_GAP = SCREEN_CONTENT_TOP - SCREEN_CHROME_BOTTOM

interface TopChromeProps {
    onBack: () => void
    onPrevious?: () => void
    onNext?: () => void
    title?: ScrollTitle
    refreshing?: boolean
    /** False leaves out the Previous and Next pill, for a screen that is not one report of the inbox list. */
    withPager?: boolean
}

export function TopChrome({
    onBack,
    onPrevious,
    onNext,
    title,
    refreshing = false,
    withPager = true,
}: TopChromeProps): ReactElement {
    const styles = useStyles()
    const colors = useColors()
    return (
        <ScreenChrome
            onBack={onBack}
            backTestID="report-back"
            title={title}
            right={
                <View style={styles.actions}>
                    <View style={styles.refreshSlot}>
                        {refreshing ? (
                            <Animated.View
                                entering={FadeIn.duration(motion.fade)}
                                exiting={FadeOut.duration(motion.fade)}
                            >
                                <ActivityIndicator
                                    size="small"
                                    color={colors.muted}
                                    accessibilityLabel="Refreshing report"
                                    testID="report-refreshing"
                                />
                            </Animated.View>
                        ) : null}
                    </View>
                    {withPager ? (
                        <SegmentedPill
                            height={screenLayout.rowHeight}
                            raised
                            segmentWidth={44}
                            segments={[
                                {
                                    key: 'previous',
                                    accessibilityLabel: 'Previous report',
                                    onPress: () => onPrevious?.(),
                                    disabled: !onPrevious,
                                    testID: 'report-previous',
                                    children: <ChevronLeftIcon size={iconSizes.control} />,
                                },
                                {
                                    key: 'next',
                                    accessibilityLabel: 'Next report',
                                    onPress: () => onNext?.(),
                                    disabled: !onNext,
                                    testID: 'report-next',
                                    children: <ChevronRightIcon size={iconSizes.control} />,
                                },
                            ]}
                        />
                    ) : null}
                </View>
            }
        />
    )
}

const useStyles = createStyles(() => ({
    actions: {
        flexDirection: 'row',
        alignItems: 'center',
    },
    refreshSlot: {
        width: 20,
        height: 20,
        marginRight: 8,
        alignItems: 'center',
        justifyContent: 'center',
        pointerEvents: 'none',
    },
}))
