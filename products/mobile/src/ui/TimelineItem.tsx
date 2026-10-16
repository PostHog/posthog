import type { ReactElement } from 'react'
import { StyleSheet, Text, View } from 'react-native'

import { RichText } from './RichText'
import { colors, fonts, lineHeight, type } from './tokens'

interface TimelineItemProps {
    text: string
    time: string
    via?: string
    isLast: boolean
}

export function TimelineItem({ text, time, via, isLast }: TimelineItemProps): ReactElement {
    return (
        <View style={styles.row}>
            <View style={styles.rail}>
                <View style={styles.node} />
                {isLast ? null : <View style={styles.line} />}
            </View>
            <View style={[styles.body, !isLast && styles.bodySpaced]}>
                <RichText text={text} style={styles.text} boldStyle={styles.bold} />
                <View style={styles.meta}>
                    {via ? (
                        <View style={styles.via}>
                            <Text style={styles.viaText} numberOfLines={1}>
                                {via}
                            </Text>
                        </View>
                    ) : null}
                    <Text style={styles.time}>{time}</Text>
                </View>
            </View>
        </View>
    )
}

const styles = StyleSheet.create({
    row: {
        flexDirection: 'row',
        columnGap: 14,
    },
    rail: {
        width: 12,
        alignItems: 'center',
    },
    node: {
        width: 11,
        height: 11,
        borderRadius: 6,
        borderWidth: 1.5,
        borderColor: colors.tertiary,
        backgroundColor: colors.background,
        marginTop: 5,
    },
    line: {
        flex: 1,
        width: 1,
        marginTop: 5,
        backgroundColor: colors.border,
    },
    body: {
        flex: 1,
        minWidth: 0,
    },
    bodySpaced: {
        paddingBottom: 22,
    },
    text: {
        ...type.bodySmall,
        color: colors.muted,
    },
    bold: {
        fontWeight: '600',
        color: colors.ink,
    },
    meta: {
        marginTop: 4,
        flexDirection: 'row',
        alignItems: 'center',
        flexWrap: 'wrap',
        rowGap: 6,
        columnGap: 8,
    },
    via: {
        borderWidth: 1,
        borderColor: colors.border,
        borderRadius: 6,
        paddingVertical: 2,
        paddingHorizontal: 7,
    },
    viaText: {
        fontFamily: fonts.mono,
        fontSize: 11,
        lineHeight: lineHeight(11),
        color: colors.secondary,
    },
    time: {
        ...type.meta,
        color: colors.tertiary,
    },
})
