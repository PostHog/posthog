import type { ReactElement } from 'react'
import { type LayoutChangeEvent, StyleSheet, Text, type TextStyle } from 'react-native'

import type { Accent, Headline } from '@/model/types'
import { accentColor, colors, prettyWrap, type } from '@/ui/tokens'

interface HeadlineTitleProps {
    headline: Headline
    accent: Accent
    onLayout?: (event: LayoutChangeEvent) => void
}

/** The report headline, with its leading number in the accent color. */
export function HeadlineTitle({ headline, accent, onLayout }: HeadlineTitleProps): ReactElement {
    return (
        <Text
            style={[styles.headline, prettyWrap]}
            accessibilityRole="header"
            lineBreakStrategyIOS="standard"
            onLayout={onLayout}
        >
            {headline.number ? <Text style={NUMBER_STYLES[accent]}>{headline.number} </Text> : null}
            {headline.rest}
        </Text>
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
})
