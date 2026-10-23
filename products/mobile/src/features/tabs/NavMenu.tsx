import { type ComponentType, type ReactElement, useEffect, useState } from 'react'
import { Text, useWindowDimensions, View } from 'react-native'

import { useAuthStore } from '@/auth/authStore'
import { ProjectSheet } from '@/features/projects/ProjectSheet'
import { track } from '@/lib/analytics'
import { FloatingCard } from '@/ui/FloatingCard'
import { ChevronUpDownIcon } from '@/ui/icons/ChevronUpDownIcon'
import { ExternalLinkIcon } from '@/ui/icons/ExternalLinkIcon'
import { GripIcon } from '@/ui/icons/GripIcon'
import { PinIcon } from '@/ui/icons/PinIcon'
import { SettingsIcon } from '@/ui/icons/SettingsIcon'
import { SignOutIcon } from '@/ui/icons/SignOutIcon'
import type { IconProps } from '@/ui/icons/types'
import { Pressable44 } from '@/ui/Pressable44'
import { createStyles, useColors } from '@/ui/theme'
import { iconSizes, radii, type } from '@/ui/tokens'
import { topOffset, useScreenInsets } from '@/ui/useScreenInsets'

import { SignOutConfirm } from '../settings/SignOutConfirm'
import type { TabHeaderSlot } from './tabHeaderStore'

interface NavMenuProps {
    visible: boolean
    projectName: string
    /** The focused tab's Edit pins row, in its own section above Settings. Null leaves the section out. */
    editPins: TabHeaderSlot['editPins']
    /** A pinned list's rows, at the top while its tab is focused. Null leaves the section out. */
    navList: { onUnpin: () => void; onOpenWeb: (() => void) | null } | null
    onClose: () => void
    onSettings: () => void
    onSignOut: () => void
    /** Replaces the rows with the sign-out confirmation. */
    confirmingSignOut: boolean
    signOutPending: boolean
    signOutError: string | null
    onCancelSignOut: () => void
    onConfirmSignOut: () => void
}

interface MenuRowProps {
    label: string
    Icon: ComponentType<IconProps>
    disabled?: boolean
    onPress: () => void
    testID: string
}

function MenuRow({ label, Icon, disabled = false, onPress, testID }: MenuRowProps): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    return (
        <Pressable44
            onPress={onPress}
            disabled={disabled}
            accessibilityLabel={label}
            accessibilityState={{ disabled }}
            pressedBackground={colors.sunken}
            style={styles.row}
            testID={testID}
        >
            <Icon size={iconSizes.control} color={disabled ? colors.disabled : undefined} />
            <Text style={[styles.rowLabel, disabled && styles.rowLabelDisabled]}>{label}</Text>
        </Pressable44>
    )
}

export function NavMenu({
    visible,
    projectName,
    editPins,
    navList,
    onClose,
    onSettings,
    onSignOut,
    confirmingSignOut,
    signOutPending,
    signOutError,
    onCancelSignOut,
    onConfirmSignOut,
}: NavMenuProps): ReactElement {
    const colors = useColors()
    const styles = useStyles()
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
    const openSettings = (): void => {
        track('mobile_settings_opened', { from: 'nav_menu' })
        onSettings()
    }
    const switchProject = (projectId: number): void => {
        useAuthStore.getState().selectProject(projectId, 'nav_menu')
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
                        from="nav_menu"
                        pending={signOutPending}
                        error={signOutError}
                        onCancel={onCancelSignOut}
                        onConfirm={onConfirmSignOut}
                        style={styles.confirm}
                        testIDPrefix="nav"
                    />
                ) : (
                    <>
                        {navList ? (
                            <>
                                <MenuRow
                                    label="Unpin from navigation"
                                    Icon={PinIcon}
                                    onPress={navList.onUnpin}
                                    testID="nav-list-unpin"
                                />
                                {navList.onOpenWeb ? (
                                    <MenuRow
                                        label="Open on web"
                                        Icon={ExternalLinkIcon}
                                        onPress={navList.onOpenWeb}
                                        testID="nav-list-open-web"
                                    />
                                ) : null}
                                <View style={[styles.divider, styles.sectionDivider]} />
                            </>
                        ) : null}
                        {editPins ? (
                            <>
                                <MenuRow
                                    label="Edit pins"
                                    Icon={GripIcon}
                                    onPress={editPins.onPress}
                                    disabled={editPins.disabled}
                                    testID="views-edit-pins"
                                />
                                <View style={[styles.divider, styles.sectionDivider]} />
                            </>
                        ) : null}
                        <MenuRow label="Settings" Icon={SettingsIcon} onPress={openSettings} testID="nav-settings" />
                        <MenuRow label="Sign out" Icon={SignOutIcon} onPress={onSignOut} testID="nav-sign-out" />
                    </>
                )}
            </FloatingCard>
            <ProjectSheet visible={visible && pickingProject} onClose={onClose} onSelect={switchProject} />
        </>
    )
}

const useStyles = createStyles(({ colors }) => ({
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
    sectionDivider: {
        marginTop: 6,
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
    rowLabel: {
        ...type.menuRow,
        color: colors.ink,
        flex: 1,
    },
    rowLabelDisabled: {
        color: colors.disabled,
    },
    confirm: {
        paddingHorizontal: 14,
        paddingTop: 8,
    },
}))
