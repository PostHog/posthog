import type { ReactElement, ReactNode } from 'react'
import { type LayoutChangeEvent, StyleSheet, Text, type TextStyle, View } from 'react-native'

import type { Accent, Headline as HeadlineModel } from '@/model/types'
import { accentColor, colors, prettyWrap, type } from '@/ui/tokens'

interface HeadlineProps {
    headline: HeadlineModel
    accent: Accent
    lede: string
    meta: ReactNode
    onHeadlineHeight?: (height: number) => void
}

export function headlineText(headline: HeadlineModel): string {
    return headline.number ? `${headline.number} ${headline.rest}` : headline.rest
}

export function Headline({ headline, accent, lede, meta, onHeadlineHeight }: HeadlineProps): ReactElement {
    const onLayout = (event: LayoutChangeEvent): void => onHeadlineHeight?.(event.nativeEvent.layout.height)
    return (
        <View>
            <Text
                style={[styles.headline, prettyWrap]}
                accessibilityRole="header"
                lineBreakStrategyIOS="standard"
                onLayout={onLayout}
            >
                {headline.number ? <Text style={NUMBER_STYLES[accent]}>{headline.number} </Text> : null}
                {headline.rest}
            </Text>
            {meta}
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
        marginTop: 14,
        color: colors.muted,
    },
})
