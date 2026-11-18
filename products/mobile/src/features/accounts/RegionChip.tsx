import type { ReactElement } from 'react'
import { Text, View } from 'react-native'

import type { StoredAccount } from '@/auth/authStore'
import { createStyles } from '@/ui/theme'
import { fonts, letterSpacing, radii } from '@/ui/tokens'

import { regionText } from './accountLabel'

interface RegionChipProps {
    account: Pick<StoredAccount, 'host' | 'region'>
}

/** "US" or "EU" for PostHog Cloud, the host name in mono for a self-hosted instance. A long host truncates. */
export function RegionChip({ account }: RegionChipProps): ReactElement {
    const styles = useStyles()
    const custom = account.region === 'custom'
    return (
        <View style={[styles.chip, custom && styles.hostChip]}>
            <Text style={[styles.text, custom && styles.hostText]} numberOfLines={1} ellipsizeMode="middle">
                {regionText(account)}
            </Text>
        </View>
    )
}

const useStyles = createStyles(({ colors }) => ({
    chip: {
        height: 20,
        justifyContent: 'center',
        paddingHorizontal: 7,
        borderRadius: radii.pill,
        borderWidth: 1,
        borderColor: colors.hairline,
        backgroundColor: colors.sunken,
        flexShrink: 0,
    },
    hostChip: {
        flexShrink: 1,
        minWidth: 0,
    },
    text: {
        fontSize: 11,
        lineHeight: 16,
        fontWeight: '600',
        letterSpacing: letterSpacing(11, 0.04),
        color: colors.muted,
    },
    hostText: {
        fontFamily: fonts.mono,
        fontWeight: '500',
        letterSpacing: 0,
    },
}))
