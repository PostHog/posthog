import type { ReactElement } from 'react'
import { Text, View } from 'react-native'

import { createStyles } from '@/ui/theme'
import { radii, type } from '@/ui/tokens'

/** A fenced block, such as a stack trace or a query, on the same dark card as the report screen's trace. */
export function MonoBlock({ code }: { code: string }): ReactElement {
    const styles = useStyles()
    return (
        <View style={styles.card}>
            <Text style={styles.code} selectable>
                {code}
            </Text>
        </View>
    )
}

const useStyles = createStyles(({ colors }) => ({
    card: {
        backgroundColor: colors.terminal,
        borderRadius: radii.card,
        // The 1pt outline comes out of the padding, so the card keeps its size in both schemes.
        borderWidth: 1,
        borderColor: colors.terminalBorder,
        paddingVertical: 13,
        paddingHorizontal: 15,
        marginBottom: 10,
        overflow: 'hidden',
    },
    code: {
        ...type.mono,
        color: colors.onTerminalMuted,
    },
}))
