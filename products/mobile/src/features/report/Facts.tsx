import type { ReactElement } from 'react'
import { Text, type TextStyle, View } from 'react-native'

import type { Fact } from '@/model/types'
import { createStyles } from '@/ui/theme'
import { fonts, lineHeight } from '@/ui/tokens'

const useToneStyles = createStyles<Record<Fact['tone'], TextStyle>>(({ colors }) => ({
    default: { color: colors.ink },
    alert: { color: colors.orange },
    agent: { color: colors.blue },
}))

export function Facts({ facts }: { facts: Fact[] }): ReactElement | null {
    const styles = useStyles()
    const toneStyles = useToneStyles()
    if (facts.length === 0) {
        return null
    }
    return (
        <View style={styles.list}>
            {facts.map((fact, index) => (
                <View key={fact.key}>
                    <Text style={styles.key}>{fact.key}</Text>
                    <View style={[styles.value, index === facts.length - 1 && styles.last]}>
                        <Text style={[styles.title, toneStyles[fact.tone]]}>{fact.title}</Text>
                        {fact.sub ? <Text style={styles.sub}>{fact.sub}</Text> : null}
                    </View>
                </View>
            ))}
        </View>
    )
}

const useStyles = createStyles(({ colors }) => ({
    list: {
        marginTop: 24,
        borderTopWidth: 1,
        borderTopColor: colors.border,
    },
    key: {
        paddingTop: 14,
        paddingBottom: 6,
        fontFamily: fonts.mono,
        fontSize: 12,
        lineHeight: lineHeight(12),
        color: colors.tertiary,
    },
    value: {
        paddingBottom: 14,
        borderBottomWidth: 1,
        borderBottomColor: colors.rowDivider,
    },
    last: {
        borderBottomColor: 'transparent',
    },
    title: {
        fontSize: 15,
        lineHeight: lineHeight(15),
        fontWeight: '600',
    },
    sub: {
        fontSize: 14,
        lineHeight: lineHeight(14),
        color: colors.muted,
        marginTop: 2,
    },
}))
