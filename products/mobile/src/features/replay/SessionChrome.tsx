import { Stack } from 'expo-router'
import type { ReactElement } from 'react'
import { Platform, View } from 'react-native'
import { ExternalLinkIcon } from '@/ui/icons/ExternalLinkIcon'
import { MoreIcon } from '@/ui/icons/MoreIcon'
import { nativeIcons } from '@/ui/icons/nativeIcons'
import { PlayIcon } from '@/ui/icons/PlayIcon'
import { PillControl } from '@/ui/PillControl'
import { Pressable44 } from '@/ui/Pressable44'
import { ScreenChrome } from '@/ui/ScreenChrome'
import { screenLayout } from '@/ui/screenLayout'
import { createStyles, useColors } from '@/ui/theme'
import { iconSizes } from '@/ui/tokens'
import type { ScrollTitle } from '@/ui/useScrollTitle'

interface SessionChromeProps {
    title?: ScrollTitle
    onBack: () => void
    /** "Open full replay". Absent on a list, and disabled in the demo. */
    onOpenFull?: (() => void) | null
    /** The full-replay button plays the video in the app instead of opening the web player. */
    watchInApp?: boolean
    onMore?: (() => void) | null
}

export function SessionChrome({
    onBack,
    onOpenFull,
    watchInApp = false,
    onMore,
    title,
}: SessionChromeProps): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    const openLabel = watchInApp ? 'Watch replay' : 'Open full replay'
    const OpenIcon = watchInApp ? PlayIcon : ExternalLinkIcon
    return (
        <ScreenChrome
            onBack={onBack}
            backTestID="replay-back"
            title={title}
            nativeActions={
                Platform.OS === 'ios' ? (
                    <>
                        {onOpenFull !== undefined ? (
                            <Stack.Toolbar.Button
                                iconRenderingMode="template"
                                icon={watchInApp ? nativeIcons.play : nativeIcons.external}
                                accessibilityLabel={openLabel}
                                disabled={!onOpenFull}
                                onPress={() => onOpenFull?.()}
                            />
                        ) : null}
                        <Stack.Toolbar.Button
                            iconRenderingMode="template"
                            icon={nativeIcons.more}
                            accessibilityLabel="More"
                            disabled={!onMore}
                            onPress={() => onMore?.()}
                        />
                    </>
                ) : null
            }
            right={
                <PillControl height={screenLayout.rowHeight}>
                    {onOpenFull !== undefined ? (
                        <>
                            <Pressable44
                                onPress={() => onOpenFull?.()}
                                disabled={!onOpenFull}
                                accessibilityRole={watchInApp ? 'button' : 'link'}
                                accessibilityLabel={openLabel}
                                pressedBackground={colors.background}
                                style={styles.full}
                                testID="session-open-full"
                            >
                                <OpenIcon size={iconSizes.control} color={onOpenFull ? colors.ink : colors.disabled} />
                            </Pressable44>
                            <View style={styles.divider} />
                        </>
                    ) : null}
                    <Pressable44
                        onPress={() => onMore?.()}
                        disabled={!onMore}
                        accessibilityLabel="More"
                        pressedBackground={colors.background}
                        style={styles.more}
                        testID="replay-more"
                    >
                        <MoreIcon size={22} color={onMore ? colors.ink : colors.disabled} />
                    </Pressable44>
                </PillControl>
            }
        />
    )
}

const useStyles = createStyles(({ colors }) => ({
    full: {
        height: 36,
        flexDirection: 'row',
        alignItems: 'center',
        gap: 8,
        width: 44,
        justifyContent: 'center',
        borderRadius: 999,
    },
    divider: {
        width: 1,
        height: 24,
        backgroundColor: colors.hairline,
    },
    more: {
        width: 52,
        height: 36,
        borderRadius: 999,
        alignItems: 'center',
        justifyContent: 'center',
    },
}))
