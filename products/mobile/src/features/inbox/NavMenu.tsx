import type { ComponentType, ReactElement } from 'react'
import { StyleSheet, Text, useWindowDimensions, View } from 'react-native'

import { FloatingCard } from '@/ui/FloatingCard'
import { ChevronUpDownIcon } from '@/ui/icons/ChevronUpDownIcon'
import { InboxIcon } from '@/ui/icons/InboxIcon'
import { SettingsIcon } from '@/ui/icons/SettingsIcon'
import { SignOutIcon } from '@/ui/icons/SignOutIcon'
import type { IconProps } from '@/ui/icons/types'
import { Pressable44 } from '@/ui/Pressable44'
import { colors, radii, type } from '@/ui/tokens'
import { topOffset, useScreenInsets } from '@/ui/useScreenInsets'

import { SignOutConfirm } from '../settings/SignOutConfirm'

interface NavMenuProps {
    visible: boolean
    projectName: string
    onClose: () => void
    onSettings: () => void
    onSignOut: () => void
    /** Replaces the rows with the sign-out confirmation. */
    confirmingSignOut: boolean
    signOutPending: boolean
    onCancelSignOut: () => void
    onConfirmSignOut: () => void
}

interface MenuRowProps {
    label: string
    Icon: ComponentType<IconProps>
    selected?: boolean
    onPress: () => void
    testID: string
}

function MenuRow({ label, Icon, selected = false, onPress, testID }: MenuRowProps): ReactElement {
    return (
        <Pressable44
            onPress={onPress}
            accessibilityState={{ selected }}
            pressedBackground={colors.sunken}
            style={[styles.row, selected && styles.selected]}
            testID={testID}
        >
            <Icon size={22} />
            <Text style={styles.rowLabel}>{label}</Text>
        </Pressable44>
    )
}

export function NavMenu({
    visible,
    projectName,
    onClose,
    onSettings,
    onSignOut,
    confirmingSignOut,
    signOutPending,
    onCancelSignOut,
    onConfirmSignOut,
}: NavMenuProps): ReactElement {
    const insets = useScreenInsets()
    const { width: windowWidth } = useWindowDimensions()
    // The handoff's 75% width is the content box; padding and border add 22pt.
    const width = Math.round(windowWidth * 0.75) + 22
    return (
        <FloatingCard
            visible={visible}
            onClose={onClose}
            transformOrigin="top right"
            accessibilityLabel="Menu"
            testID="nav-menu"
            style={[styles.card, { top: topOffset(insets, 60), width }]}
        >
            <View style={styles.header}>
                <Text style={styles.project} numberOfLines={1}>
                    {projectName}
                </Text>
                <ChevronUpDownIcon size={14} color={colors.tertiary} />
            </View>
            <View style={styles.divider} />
            {confirmingSignOut ? (
                <SignOutConfirm
                    pending={signOutPending}
                    onCancel={onCancelSignOut}
                    onConfirm={onConfirmSignOut}
                    style={styles.confirm}
                    testIDPrefix="nav"
                />
            ) : (
                <>
                    <MenuRow label="Inbox" Icon={InboxIcon} selected onPress={onClose} testID="nav-inbox" />
                    <MenuRow label="Settings" Icon={SettingsIcon} onPress={onSettings} testID="nav-settings" />
                    <MenuRow label="Sign out" Icon={SignOutIcon} onPress={onSignOut} testID="nav-sign-out" />
                </>
            )}
        </FloatingCard>
    )
}

const styles = StyleSheet.create({
    card: {
        right: 14,
        borderWidth: 1,
        borderColor: colors.hairline,
        paddingTop: 8,
        paddingHorizontal: 10,
        paddingBottom: 12,
    },
    header: {
        height: 52,
        flexDirection: 'row',
        alignItems: 'center',
        gap: 8,
        paddingHorizontal: 14,
    },
    project: {
        fontSize: 18,
        lineHeight: 25.2,
        fontWeight: '600',
        letterSpacing: -0.18,
        color: colors.ink,
        flexShrink: 1,
    },
    divider: {
        height: 1,
        backgroundColor: colors.hairline,
        marginHorizontal: 4,
        marginBottom: 6,
    },
    row: {
        height: 52,
        flexDirection: 'row',
        alignItems: 'center',
        gap: 16,
        paddingHorizontal: 14,
        borderRadius: radii.menuRow,
    },
    selected: {
        backgroundColor: colors.sunken,
    },
    rowLabel: {
        ...type.menuRow,
        color: colors.ink,
    },
    confirm: {
        paddingHorizontal: 14,
        paddingTop: 8,
    },
})
