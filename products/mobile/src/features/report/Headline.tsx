import type { ReactElement, ReactNode } from 'react'
import { type LayoutChangeEvent, Text, View } from 'react-native'

import type { Accent, Headline as HeadlineModel } from '@/model/types'
import { createStyles } from '@/ui/theme'
import { prettyWrap, type } from '@/ui/tokens'

import { HeadlineTitle } from './HeadlineTitle'

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
    const styles = useStyles()
    const onLayout = (event: LayoutChangeEvent): void => onHeadlineHeight?.(event.nativeEvent.layout.height)
    return (
        <View>
            <HeadlineTitle headline={headline} accent={accent} onLayout={onLayout} />
            {meta}
            <Text style={[styles.lede, prettyWrap]} lineBreakStrategyIOS="standard">
                {lede}
            </Text>
        </View>
    )
}

const useStyles = createStyles(({ colors }) => ({
    lede: {
        ...type.body,
        marginTop: 14,
        color: colors.muted,
    },
}))
