import type { ReactElement } from 'react'
import { type StyleProp, Text, type TextStyle } from 'react-native'

import { parseBold } from '@/lib/richText'

interface RichTextProps {
    text: string
    style?: StyleProp<TextStyle>
    boldStyle?: StyleProp<TextStyle>
}

export function RichText({ text, style, boldStyle }: RichTextProps): ReactElement {
    return (
        <Text style={style}>
            {parseBold(text).map((segment, index) =>
                segment.bold ? (
                    // biome-ignore lint/suspicious/noArrayIndexKey: segments are positional and never reorder
                    <Text key={index} style={boldStyle}>
                        {segment.text}
                    </Text>
                ) : (
                    segment.text
                )
            )}
        </Text>
    )
}
