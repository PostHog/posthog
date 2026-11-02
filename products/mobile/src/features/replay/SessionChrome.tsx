import type { ReactElement } from 'react'
import { View } from 'react-native'
import { ExternalLinkIcon } from '@/ui/icons/ExternalLinkIcon'
import { MoreIcon } from '@/ui/icons/MoreIcon'
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
    onMore?: (() => void) | null
}

export function SessionChrome({ onBack, onOpenFull, onMore, title }: SessionChromeProps): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    return (
        <ScreenChrome
            onBack={onBack}
            backTestID="replay-back"
            title={title}
            right={
                <PillControl height={screenLayout.rowHeight}>
                    {onOpenFull !== undefined ? (
                        <>
                            <Pressable44
                                onPress={() => onOpenFull?.()}
                                disabled={!onOpenFull}
                                accessibilityRole="link"
                                accessibilityLabel="Open full replay"
                                pressedBackground={colors.background}
                                style={styles.full}
                                testID="session-open-full"
                            >
                                <ExternalLinkIcon
                                    size={iconSizes.control}
                                    color={onOpenFull ? colors.ink : colors.disabled}
                                />
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
