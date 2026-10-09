import type { ReactElement } from 'react'
import { StyleSheet, Text, View } from 'react-native'

import { LogoMark } from '@/ui/icons/LogoMark'
import { MoreIcon } from '@/ui/icons/MoreIcon'
import { RefreshIcon } from '@/ui/icons/RefreshIcon'
import { PillControl } from '@/ui/PillControl'
import { Pressable44 } from '@/ui/Pressable44'
import { colors, type } from '@/ui/tokens'

interface InboxHeaderProps {
    onRefresh: () => void
    refreshing: boolean
    onOpenMenu: () => void
}

export function InboxHeader({ onRefresh, refreshing, onOpenMenu }: InboxHeaderProps): ReactElement {
    return (
        <View style={styles.row}>
            <View style={styles.titleGroup}>
                <LogoMark />
                <Text style={styles.title} accessibilityRole="header">
                    Inbox
                </Text>
            </View>
            <PillControl>
                <Pressable44
                    onPress={onRefresh}
                    disabled={refreshing}
                    accessibilityLabel="Refresh"
                    accessibilityState={{ busy: refreshing }}
                    pressedBackground={colors.background}
                    style={styles.button}
                    testID="inbox-refresh"
                >
                    <RefreshIcon size={22} color={refreshing ? colors.tertiary : colors.ink} />
                </Pressable44>
                <Pressable44
                    onPress={onOpenMenu}
                    accessibilityLabel="More"
                    pressedBackground={colors.background}
                    style={styles.button}
                    testID="inbox-more"
                >
                    <MoreIcon size={22} />
                </Pressable44>
            </PillControl>
        </View>
    )
}

const styles = StyleSheet.create({
    row: {
        flexDirection: 'row',
        alignItems: 'center',
        justifyContent: 'space-between',
    },
    titleGroup: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: 12,
    },
    title: {
        ...type.screenTitle,
        color: colors.ink,
    },
    button: {
        width: 56,
        height: 46,
        borderRadius: 999,
        alignItems: 'center',
        justifyContent: 'center',
    },
})
