import type { ReactElement } from 'react'
import { View } from 'react-native'

import type { StoredAccount } from '@/auth/authStore'
import { Avatar } from '@/ui/Avatar'
import { PersonIcon } from '@/ui/icons/PersonIcon'
import { createStyles, useColors } from '@/ui/theme'

interface AccountAvatarProps {
    account: Pick<StoredAccount, 'key' | 'user'>
    size: number
}

/**
 * The account's initials, colored from its key so one login keeps its color and the same person on two hosts gets
 * two. An account whose details have not loaded yet shows a neutral person glyph.
 */
export function AccountAvatar({ account, size }: AccountAvatarProps): ReactElement {
    const styles = useStyles()
    const colors = useColors()
    if (!account.user) {
        return (
            <View
                style={[styles.placeholder, { width: size, height: size, borderRadius: size / 2 }]}
                accessibilityElementsHidden
                importantForAccessibility="no-hide-descendants"
            >
                <PersonIcon size={Math.round(size * 0.55)} color={colors.secondary} />
            </View>
        )
    }
    return (
        <Avatar
            name={account.user.name || account.user.email}
            seed={account.key}
            size={size}
            fontSize={Math.max(9, Math.round(size * 0.37))}
        />
    )
}

const useStyles = createStyles(({ colors }) => ({
    placeholder: {
        alignItems: 'center',
        justifyContent: 'center',
        backgroundColor: colors.sunken,
        borderWidth: 1,
        borderColor: colors.hairline,
    },
}))
