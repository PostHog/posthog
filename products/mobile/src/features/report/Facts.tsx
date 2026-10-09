import type { ReactElement } from 'react'
import { StyleSheet, Text, type TextStyle, View } from 'react-native'

import type { Fact } from '@/model/types'
import { colors, fonts, lineHeight } from '@/ui/tokens'

const TONE_STYLES = StyleSheet.create<Record<Fact['tone'], TextStyle>>({
    default: { color: colors.ink },
    alert: { color: colors.orange },
    agent: { color: colors.blue },
})

export function Facts({ facts }: { facts: Fact[] }): ReactElement | null {
    if (facts.length === 0) {
        return null
    }
    return (
        <View style={styles.list}>
            {facts.map((fact, index) => (
                <View key={fact.key}>
                    <Text style={styles.key}>{fact.key}</Text>
                    <View style={[styles.value, index === facts.length - 1 && styles.last]}>
                        <Text style={[styles.title, TONE_STYLES[fact.tone]]}>{fact.title}</Text>
                        {fact.sub ? <Text style={styles.sub}>{fact.sub}</Text> : null}
                    </View>
                </View>
            ))}
        </View>
    )
}

const styles = StyleSheet.create({
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
})
