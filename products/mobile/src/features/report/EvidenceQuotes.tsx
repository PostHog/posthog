import type { ReactElement } from 'react'
import { StyleSheet, Text, View } from 'react-native'

import type { EvidenceBlock } from '@/model/types'
import { MonoText } from '@/ui/MonoText'
import { colors, prettyWrap, radii, type } from '@/ui/tokens'

type QuotesBlock = Extract<EvidenceBlock, { kind: 'quotes' }>

export function EvidenceQuotes({ block }: { block: QuotesBlock }): ReactElement {
    return (
        <View style={styles.list}>
            {block.quotes.map((quote) => (
                <View key={`${quote.who}-${quote.text}`} style={styles.card}>
                    <Text style={[styles.text, prettyWrap]} lineBreakStrategyIOS="standard">
                        {quote.text}
                    </Text>
                    <MonoText size={11} color={colors.secondary}>
                        {quote.who}
                    </MonoText>
                </View>
            ))}
        </View>
    )
}

const styles = StyleSheet.create({
    list: {
        gap: 8,
    },
    card: {
        backgroundColor: colors.white,
        borderWidth: 1,
        borderColor: colors.border,
        borderRadius: radii.card,
        paddingVertical: 14,
        paddingHorizontal: 16,
        gap: 8,
    },
    text: {
        ...type.bodySmall,
        color: colors.ink,
    },
})
