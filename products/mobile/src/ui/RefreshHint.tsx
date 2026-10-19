import type { ReactElement } from 'react'
import { type StyleProp, StyleSheet, Text, type TextStyle } from 'react-native'

import { colors } from './tokens'

interface RefreshHintProps {
    text: string
    style?: StyleProp<TextStyle>
    testID?: string
}

/**
 * The inline hint under the status line. Place it so that showing it does not move the layout, for example
 * absolutely positioned in the header's bottom padding.
 */
export function RefreshHint({ text, style, testID = 'views-refresh-hint' }: RefreshHintProps): ReactElement {
    return (
        <Text
            style={[styles.hint, style]}
            numberOfLines={1}
            accessibilityLiveRegion="polite"
            accessibilityRole="text"
            testID={testID}
        >
            {text}
        </Text>
    )
}

const styles = StyleSheet.create({
    hint: {
        fontSize: 13,
        lineHeight: 16,
        fontWeight: '600',
        color: colors.muted,
    },
})
