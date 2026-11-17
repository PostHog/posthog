import type { ReactElement, ReactNode } from 'react'
import { Text, type TextStyle, View } from 'react-native'

import type { StoredAccount } from '@/auth/authStore'
import { createStyles } from '@/ui/theme'

import { AccountAvatar } from './AccountAvatar'
import { RegionChip } from './RegionChip'

type IdentitySize = 'compact' | 'regular' | 'large'

const AVATAR_SIZES: Record<IdentitySize, number> = { compact: 28, regular: 36, large: 44 }

interface AccountIdentityProps {
    account: StoredAccount
    size: IdentitySize
    /** Follows the region chip on the second line, such as "Active" or "Session ended". */
    status?: ReactNode
}

/** Avatar, email and region chip: how the switcher, Settings and the session-ended screen show one account. */
export function AccountIdentity({ account, size, status }: AccountIdentityProps): ReactElement {
    const styles = useStyles()
    return (
        <View style={styles.row}>
            <AccountAvatar account={account} size={AVATAR_SIZES[size]} />
            <View style={styles.text}>
                <Text style={[styles.email, styles[size]]} numberOfLines={1} ellipsizeMode="middle">
                    {account.user?.email ?? 'Saved account'}
                </Text>
                <View style={styles.meta}>
                    <RegionChip account={account} />
                    {status}
                </View>
            </View>
        </View>
    )
}

const EMAIL_TYPE: Record<IdentitySize, TextStyle> = {
    compact: { fontSize: 15, lineHeight: 21, fontWeight: '600' },
    regular: { fontSize: 15, lineHeight: 21, fontWeight: '500' },
    large: { fontSize: 16, lineHeight: 22, fontWeight: '600' },
}

const useStyles = createStyles(({ colors }) => ({
    row: {
        flex: 1,
        minWidth: 0,
        flexDirection: 'row',
        alignItems: 'center',
        gap: 12,
    },
    text: {
        flex: 1,
        minWidth: 0,
        gap: 3,
    },
    email: {
        color: colors.ink,
    },
    ...EMAIL_TYPE,
    // The status moves to its own line when it does not fit beside the chip, and a host longer than the line truncates.
    meta: {
        flexDirection: 'row',
        flexWrap: 'wrap',
        alignItems: 'center',
        columnGap: 6,
        rowGap: 2,
        minWidth: 0,
    },
}))
