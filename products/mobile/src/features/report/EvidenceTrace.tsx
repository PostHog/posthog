import type { ReactElement } from 'react'
import { StyleSheet, Text, View } from 'react-native'

import type { EvidenceBlock } from '@/model/types'
import { colors, radii, type } from '@/ui/tokens'

type TraceBlock = Extract<EvidenceBlock, { kind: 'trace' }>

export function EvidenceTrace({ block }: { block: TraceBlock }): ReactElement {
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

const styles = StyleSheet.create({
    card: {
        backgroundColor: colors.ink,
        borderRadius: radii.card,
        paddingVertical: 14,
        paddingHorizontal: 16,
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
        color: colors.disabled,
    },
    firstFn: {
        color: colors.background,
    },
    footer: {
        color: colors.disabled,
        paddingTop: 8,
        borderTopWidth: 1,
        borderTopColor: colors.darkDivider,
    },
})
