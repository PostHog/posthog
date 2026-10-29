import type { ReactElement } from 'react'
import { type LayoutChangeEvent, Text, type TextStyle } from 'react-native'

import type { Accent, Headline } from '@/model/types'
import { createStyles } from '@/ui/theme'
import { prettyWrap, type } from '@/ui/tokens'

interface HeadlineTitleProps {
    headline: Headline
    accent: Accent
    onLayout?: (event: LayoutChangeEvent) => void
}

/** The report headline, with its leading number in the accent color. */
export function HeadlineTitle({ headline, accent, onLayout }: HeadlineTitleProps): ReactElement {
    const styles = useStyles()
    const numberStyles = useNumberStyles()
    return (
        <Text
            style={[styles.headline, prettyWrap]}
            accessibilityRole="header"
            lineBreakStrategyIOS="standard"
            onLayout={onLayout}
        >
            {headline.number ? <Text style={numberStyles[accent]}>{headline.number} </Text> : null}
            {headline.rest}
        </Text>
    )
}

const useNumberStyles = createStyles<Record<Accent, TextStyle>>(({ accentColor }) => ({
    alert: { color: accentColor.alert },
    opportunity: { color: accentColor.opportunity },
    resolved: { color: accentColor.resolved },
}))

const useStyles = createStyles(({ colors }) => ({
    headline: {
        ...type.headline,
        color: colors.ink,
    },
}))
