import type { ReactElement } from 'react'
import { StyleSheet, Text, type TextStyle, View } from 'react-native'

import type { Accent, Headline as HeadlineModel } from '@/model/types'
import { accentColor, colors, prettyWrap, type } from '@/ui/tokens'

interface HeadlineProps {
    headline: HeadlineModel
    accent: Accent
    lede: string
}

export function Headline({ headline, accent, lede }: HeadlineProps): ReactElement {
    return (
        <View>
            <Text style={[styles.headline, prettyWrap]} accessibilityRole="header" lineBreakStrategyIOS="standard">
                {headline.number ? <Text style={NUMBER_STYLES[accent]}>{headline.number} </Text> : null}
                {headline.rest}
            </Text>
            <Text style={[styles.lede, prettyWrap]} lineBreakStrategyIOS="standard">
                {lede}
            </Text>
        </View>
    )
}

const NUMBER_STYLES = StyleSheet.create<Record<Accent, TextStyle>>({
    alert: { color: accentColor.alert },
    opportunity: { color: accentColor.opportunity },
    resolved: { color: accentColor.resolved },
})

const styles = StyleSheet.create({
    headline: {
        ...type.headline,
        color: colors.ink,
    },
    lede: {
        ...type.body,
        marginTop: 8,
        color: colors.muted,
    },
})
