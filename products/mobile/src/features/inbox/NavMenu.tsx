import { type ComponentType, type ReactElement, useEffect, useState } from 'react'
import { StyleSheet, Text, useWindowDimensions, View } from 'react-native'

import { useAuthStore } from '@/auth/authStore'
import { ProjectSheet } from '@/features/projects/ProjectSheet'
import { track } from '@/lib/analytics'
import { FloatingCard } from '@/ui/FloatingCard'
import { ChevronUpDownIcon } from '@/ui/icons/ChevronUpDownIcon'
import { InboxIcon } from '@/ui/icons/InboxIcon'
import { SettingsIcon } from '@/ui/icons/SettingsIcon'
import { SignOutIcon } from '@/ui/icons/SignOutIcon'
import type { IconProps } from '@/ui/icons/types'
import { Pressable44 } from '@/ui/Pressable44'
import { colors, iconSizes, radii, type } from '@/ui/tokens'
import { topOffset, useScreenInsets } from '@/ui/useScreenInsets'

import { SignOutConfirm } from '../settings/SignOutConfirm'

interface NavMenuProps {
    visible: boolean
    unreadCount?: number
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
    count?: number
    Icon: ComponentType<IconProps>
    selected?: boolean
    onPress: () => void
    testID: string
}

function MenuRow({ label, count = 0, Icon, selected = false, onPress, testID }: MenuRowProps): ReactElement {
    return (
        <Pressable44
            onPress={onPress}
            accessibilityState={{ selected }}
            accessibilityLabel={count > 0 ? `${label}, ${count} unread` : label}
            pressedBackground={colors.sunken}
            style={[styles.row, selected && styles.selected]}
            testID={testID}
        >
            <Icon size={iconSizes.control} />
            <Text style={styles.rowLabel}>{label}</Text>
            {count > 0 ? (
                <Text style={styles.unreadCount} testID="nav-inbox-unread">
                    {count}
                </Text>
            ) : null}
        </Pressable44>
    )
}

export function NavMenu({
    visible,
    unreadCount = 0,
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
    const [pickingProject, setPickingProject] = useState(false)

    useEffect(() => {
        if (!visible) {
            setPickingProject(false)
        }
    }, [visible])

    const openPicker = (): void => {
        track('mobile_project_picker_opened')
        setPickingProject(true)
    }
    const switchProject = (projectId: number): void => {
        useAuthStore.getState().selectProject(projectId)
        onClose()
    }

    return (
        <>
            <FloatingCard
                visible={visible && !pickingProject}
                onClose={onClose}
                transformOrigin="top right"
                accessibilityLabel="Menu"
                testID="nav-menu"
                style={[styles.card, { top: topOffset(insets, 60), width }]}
            >
                <Pressable44
                    onPress={openPicker}
                    disabled={signOutPending}
                    accessibilityLabel={projectName}
                    accessibilityHint="Switch project"
                    pressedBackground={colors.sunken}
                    style={styles.header}
                    testID="nav-project"
                >
                    <Text style={styles.project} numberOfLines={1}>
                        {projectName}
                    </Text>
                    <ChevronUpDownIcon size={iconSizes.small} color={colors.tertiary} />
                </Pressable44>
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
                        <MenuRow
                            count={unreadCount}
                            label="Inbox"
                            Icon={InboxIcon}
                            selected
                            onPress={onClose}
                            testID="nav-inbox"
                        />
                        <MenuRow label="Settings" Icon={SettingsIcon} onPress={onSettings} testID="nav-settings" />
                        <MenuRow label="Sign out" Icon={SignOutIcon} onPress={onSignOut} testID="nav-sign-out" />
                    </>
                )}
            </FloatingCard>
            <ProjectSheet visible={visible && pickingProject} onClose={onClose} onSelect={switchProject} />
        </>
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
        minHeight: 52,
        paddingVertical: 12,
        flexDirection: 'row',
        alignItems: 'center',
        gap: 8,
        paddingHorizontal: 14,
        borderRadius: radii.menuRow,
    },
    project: {
        ...type.bodyStrong,
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
        minHeight: 52,
        paddingVertical: 12,
        flexDirection: 'row',
        alignItems: 'center',
        gap: 16,
        paddingHorizontal: 14,
        borderRadius: radii.menuRow,
    },
    selected: {
        backgroundColor: colors.sunken,
    },
    unreadCount: { ...type.meta, color: colors.secondary },
    rowLabel: {
        ...type.menuRow,
        color: colors.ink,
        flex: 1,
    },
    confirm: {
        paddingHorizontal: 14,
        paddingTop: 8,
    },
})
