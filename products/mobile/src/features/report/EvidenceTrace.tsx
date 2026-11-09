import type { ReactElement } from 'react'
import { Text, View } from 'react-native'

import type { EvidenceBlock } from '@/model/types'
import { createStyles } from '@/ui/theme'
import { radii, type } from '@/ui/tokens'

type TraceBlock = Extract<EvidenceBlock, { kind: 'trace' }>

export function EvidenceTrace({ block }: { block: TraceBlock }): ReactElement {
    const styles = useStyles()
    return (
        <View style={styles.card}>
            <Text style={[styles.mono, styles.error]}>{block.error}</Text>
            <View>
                {block.frames.map((frame, index) => (
                    <Text key={`${frame.fn}-${frame.loc}`} style={[styles.mono, styles.frame]}>
                        at <Text style={index === 0 ? styles.firstFn : undefined}>{frame.fn}</Text> ({frame.loc})
                    </Text>
                ))}
            </View>
            {block.footer ? <Text style={[styles.mono, styles.footer]}>{block.footer}</Text> : null}
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
        gap: 8,
        overflow: 'hidden',
    },
    mono: {
        ...type.mono,
    },
    error: {
        color: colors.orangeLight,
    },
    frame: {
        color: colors.onTerminalMuted,
    },
    firstFn: {
        color: colors.onTerminal,
    },
    footer: {
        color: colors.onTerminalMuted,
        paddingTop: 8,
        borderTopWidth: 1,
        borderTopColor: colors.darkDivider,
    },
}))
