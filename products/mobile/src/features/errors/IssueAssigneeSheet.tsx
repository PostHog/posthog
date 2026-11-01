import type { ReactElement } from 'react'
import { ActivityIndicator, Text, View } from 'react-native'

import { Avatar } from '@/ui/Avatar'
import { BottomSheet } from '@/ui/BottomSheet'
import { CloseIcon } from '@/ui/icons/CloseIcon'
import { ExternalLinkIcon } from '@/ui/icons/ExternalLinkIcon'
import { Pressable44 } from '@/ui/Pressable44'
import { createStyles, useColors } from '@/ui/theme'
import { iconSizes, radii, type } from '@/ui/tokens'

import type { IssueAssignee } from './issueModel'

interface IssueAssigneeSheetProps {
    visible: boolean
    assignee: IssueAssignee
    myName: string
    pending: boolean
    canAssign: boolean
    error: string | null
    onClose: () => void
    onAssignMe: (assign: boolean) => void
    /** Undefined in demo mode, which has no project on the web. */
    onOpenWeb?: () => void
}

/**
 * Take the issue or give it back. Teammates need the organization's member list, which needs a scope the app does not
 * request, so passing an issue to someone else stays on the web.
 */
export function IssueAssigneeSheet({
    visible,
    assignee,
    myName,
    pending,
    canAssign,
    error,
    onClose,
    onAssignMe,
    onOpenWeb,
}: IssueAssigneeSheetProps): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    const mine = assignee.kind === 'me'
    const current =
        assignee.kind === 'user'
            ? 'Assigned to a teammate.'
            : assignee.kind === 'role'
              ? 'Assigned to a role.'
              : assignee.kind === 'none'
                ? 'Nobody owns this issue yet.'
                : null
    return (
        <BottomSheet
            visible={visible}
            onClose={onClose}
            accessibilityLabel="Assign this issue"
            testID="issue-assign-sheet"
        >
            <Text style={styles.title} accessibilityRole="header">
                Assign this issue
            </Text>
            {current ? <Text style={styles.description}>{current}</Text> : null}
            {error ? (
                <Text style={styles.error} accessibilityRole="alert" testID="issue-assign-error">
                    {error}
                </Text>
            ) : null}
            <View style={styles.rows}>
                <Pressable44
                    onPress={() => onAssignMe(!mine)}
                    disabled={pending || !canAssign}
                    accessibilityRole="button"
                    accessibilityLabel={mine ? 'Unassign me' : 'Assign to me'}
                    accessibilityState={{ disabled: pending || !canAssign, busy: pending }}
                    pressedBackground={colors.background}
                    style={styles.row}
                    testID={mine ? 'issue-unassign-me' : 'issue-assign-me'}
                >
                    {mine ? (
                        <View style={styles.iconSlot}>
                            <CloseIcon size={iconSizes.control} color={colors.ink} />
                        </View>
                    ) : (
                        <Avatar name={myName || 'You'} size={36} fontSize={14} />
                    )}
                    <View style={styles.rowText}>
                        <Text style={[styles.label, !canAssign && styles.disabled]}>
                            {mine ? 'Unassign me' : 'Assign to me'}
                        </Text>
                        {myName && !mine ? <Text style={styles.sub}>{myName}</Text> : null}
                    </View>
                    {pending ? <ActivityIndicator size="small" color={colors.muted} /> : null}
                </Pressable44>
                <Pressable44
                    onPress={() => {
                        onClose()
                        onOpenWeb?.()
                    }}
                    disabled={!onOpenWeb}
                    accessibilityRole="button"
                    accessibilityLabel="Assign a teammate on the web"
                    pressedBackground={colors.background}
                    style={styles.row}
                    testID="issue-assign-web"
                >
                    <View style={styles.iconSlot}>
                        <ExternalLinkIcon size={iconSizes.control} color={onOpenWeb ? colors.ink : colors.disabled} />
                    </View>
                    <View style={styles.rowText}>
                        <Text style={[styles.label, !onOpenWeb && styles.disabled]}>Assign a teammate on the web</Text>
                        <Text style={styles.sub}>The app can't list your teammates yet.</Text>
                    </View>
                </Pressable44>
            </View>
        </BottomSheet>
    )
}

const useStyles = createStyles(({ colors }) => ({
    title: {
        ...type.sheetTitle,
        color: colors.ink,
        marginTop: 18,
        paddingHorizontal: 4,
    },
    description: {
        ...type.metaSmall,
        color: colors.muted,
        marginTop: 6,
        paddingHorizontal: 4,
    },
    error: {
        ...type.metaSmall,
        color: colors.orange,
        marginTop: 6,
        paddingHorizontal: 4,
    },
    rows: {
        marginTop: 12,
    },
    row: {
        minHeight: 60,
        flexDirection: 'row',
        alignItems: 'center',
        gap: 14,
        paddingHorizontal: 4,
        paddingVertical: 8,
        borderRadius: radii.menuRow,
    },
    iconSlot: {
        width: 36,
        height: 36,
        borderRadius: 18,
        backgroundColor: colors.sunken,
        alignItems: 'center',
        justifyContent: 'center',
    },
    rowText: {
        flex: 1,
        minWidth: 0,
        gap: 2,
    },
    label: {
        ...type.body,
        color: colors.ink,
    },
    disabled: {
        color: colors.disabled,
    },
    sub: {
        ...type.meta,
        color: colors.tertiary,
    },
}))
