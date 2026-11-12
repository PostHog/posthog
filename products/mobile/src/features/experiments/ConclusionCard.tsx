import type { ReactElement } from 'react'
import { Text, View } from 'react-native'

import { Dot } from '@/ui/Dot'
import { createStyles, useColors } from '@/ui/theme'
import { radii, type } from '@/ui/tokens'

import { CONCLUSION_COPY, conclusionColor } from './conclusionCopy'
import type { ConclusionModel } from './detailModel'

/** The outcome of a complete experiment: the conclusion, when it ended, what the flag serves now, and the note. */
export function ConclusionCard({ model }: { model: ConclusionModel }): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    const label = model.conclusion ? CONCLUSION_COPY[model.conclusion].label : 'No conclusion'
    return (
        <View style={styles.card} testID="experiment-conclusion">
            <View style={styles.top}>
                <Dot color={model.conclusion ? conclusionColor(model.conclusion, colors) : colors.tertiary} size={10} />
                <Text style={styles.label}>{label}</Text>
                {model.ended ? <Text style={styles.ended}>Ended {model.ended}</Text> : null}
            </View>
            <Text style={styles.line}>{model.line}</Text>
            {model.comment ? (
                <View style={styles.quote}>
                    <Text style={styles.quoteText} testID="experiment-conclusion-comment">
                        {model.comment}
                    </Text>
                </View>
            ) : null}
        </View>
    )
}

const useStyles = createStyles(({ colors }) => ({
    card: {
        marginTop: 12,
        padding: 14,
        borderRadius: radii.card,
        borderWidth: 1,
        borderColor: colors.hairline,
        backgroundColor: colors.surface,
        gap: 8,
    },
    top: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: 8,
    },
    label: {
        ...type.sheetTitleLarge,
        color: colors.ink,
        flex: 1,
    },
    ended: {
        ...type.meta,
        color: colors.secondary,
    },
    line: {
        ...type.bodySmall,
        color: colors.ink,
    },
    quote: {
        marginTop: 4,
        paddingTop: 10,
        borderTopWidth: 1,
        borderTopColor: colors.hairline,
    },
    quoteText: {
        ...type.bodySmall,
        color: colors.muted,
    },
}))
