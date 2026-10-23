import type { ReactElement } from 'react'
import { View } from 'react-native'

import { Avatar } from '@/ui/Avatar'
import { PersonIcon } from '@/ui/icons/PersonIcon'
import { TeamsIcon } from '@/ui/icons/TeamsIcon'
import { createStyles, useColors } from '@/ui/theme'

import type { IssueAssignee } from './issueModel'

/**
 * The viewer's own initials, or a plain glyph for a teammate or a role: the app cannot read the member list (that
 * needs `organization_member:read`), so it cannot name them.
 */
export function AssigneeAvatar({
    assignee,
    myName,
    size,
}: {
    assignee: IssueAssignee
    myName: string
    size: number
}): ReactElement | null {
    const colors = useColors()
    const styles = useStyles()
    if (assignee.kind === 'none') {
        return null
    }
    if (assignee.kind === 'me') {
        return <Avatar name={myName || 'You'} size={size} fontSize={Math.round(size * 0.42)} />
    }
    const Icon = assignee.kind === 'role' ? TeamsIcon : PersonIcon
    return (
        <View
            style={[styles.glyph, { width: size, height: size, borderRadius: size / 2 }]}
            accessibilityLabel={assignee.kind === 'role' ? 'Assigned to a role' : 'Assigned to a teammate'}
            accessibilityRole="image"
        >
            <Icon size={Math.round(size * 0.68)} color={colors.white} />
        </View>
    )
}

const useStyles = createStyles(({ colors }) => ({
    glyph: {
        backgroundColor: colors.avatarNeutral,
        alignItems: 'center',
        justifyContent: 'center',
    },
}))
