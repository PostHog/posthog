import { type ReactElement, useState } from 'react'
import { Text, type TextLayoutEvent, View } from 'react-native'

import { ChevronDownIcon } from '@/ui/icons/ChevronDownIcon'
import { ChevronUpIcon } from '@/ui/icons/ChevronUpIcon'
import { Pressable44 } from '@/ui/Pressable44'
import { createStyles, useColors } from '@/ui/theme'
import { iconSizes, radii, type } from '@/ui/tokens'

const CLAMP_LINES = 2

interface HypothesisCardProps {
    text: string
    expanded: boolean
    onToggle: () => void
}

/**
 * The experiment's `description`, which the web labels Hypothesis. Two lines with an ellipsis; a tap shows it all. A
 * text that fits in two lines has nothing to expand, so the card stops being a button.
 */
export function HypothesisCard({ text, expanded, onToggle }: HypothesisCardProps): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    const [lines, setLines] = useState<number | null>(null)
    // The full text renders once, hidden, so the line count does not depend on the clamp.
    const onMeasure = (event: TextLayoutEvent): void => {
        setLines(event.nativeEvent.lines.length)
    }
    const expandable = lines === null || lines > CLAMP_LINES
    const body = (
        <>
            <View style={styles.top}>
                <Text style={styles.label}>Hypothesis</Text>
                {expandable ? (
                    <View style={styles.more}>
                        <Text style={styles.moreText}>{expanded ? 'Less' : 'More'}</Text>
                        {expanded ? (
                            <ChevronUpIcon size={iconSizes.inline} color={colors.secondary} />
                        ) : (
                            <ChevronDownIcon size={iconSizes.inline} color={colors.secondary} />
                        )}
                    </View>
                ) : null}
            </View>
            <View>
                <Text
                    style={[styles.text, styles.measure]}
                    onTextLayout={onMeasure}
                    accessibilityElementsHidden
                    importantForAccessibility="no-hide-descendants"
                >
                    {text}
                </Text>
                <Text
                    style={styles.text}
                    numberOfLines={expanded ? undefined : CLAMP_LINES}
                    testID="experiment-hypothesis-text"
                >
                    {text}
                </Text>
            </View>
        </>
    )
    if (!expandable) {
        return (
            <View style={styles.card} testID="experiment-hypothesis">
                {body}
            </View>
        )
    }
    return (
        <Pressable44
            onPress={onToggle}
            accessibilityRole="button"
            accessibilityLabel={`Hypothesis: ${text}`}
            accessibilityHint={expanded ? 'Shows less' : 'Shows all of it'}
            accessibilityState={{ expanded }}
            pressedBackground={colors.pressed}
            style={styles.card}
            testID="experiment-hypothesis"
        >
            {body}
        </Pressable44>
    )
}

const useStyles = createStyles(({ colors }) => ({
    card: {
        marginTop: 16,
        paddingHorizontal: 14,
        paddingTop: 12,
        paddingBottom: 14,
        borderRadius: radii.card,
        borderWidth: 1,
        borderColor: colors.hairline,
        backgroundColor: colors.surface,
        gap: 6,
    },
    top: {
        flexDirection: 'row',
        alignItems: 'center',
        justifyContent: 'space-between',
        gap: 8,
    },
    label: {
        ...type.meta,
        fontWeight: '600',
        color: colors.secondary,
    },
    more: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: 2,
    },
    moreText: {
        ...type.meta,
        fontWeight: '600',
        color: colors.secondary,
    },
    text: {
        ...type.bodySmall,
        color: colors.ink,
    },
    measure: {
        position: 'absolute',
        left: 0,
        right: 0,
        opacity: 0,
    },
}))
