import type { ReactElement } from 'react'
import { Text, View } from 'react-native'

import type { ProjectScope } from '@/api/reports'
import type { LiveEventRow } from '@/model/live'
import { MonoText } from '@/ui/MonoText'
import { Pressable44 } from '@/ui/Pressable44'
import { createStyles, useColors } from '@/ui/theme'
import { radii, type } from '@/ui/tokens'

import { customEventProperties } from './eventProperties'
import { useLiveEventProperties } from './useLiveEventProperties'

export function LiveEventProperties({
    event,
    scope,
    active,
}: {
    event: LiveEventRow
    scope: ProjectScope | null
    active: boolean
}): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    const query = useLiveEventProperties(event, scope, active)
    const properties = query.data ? customEventProperties(query.data) : []

    return (
        <View style={styles.section} testID="live-event-properties">
            <Text style={styles.title} accessibilityRole="header">
                Custom properties
            </Text>
            <View style={styles.card}>
                {query.isPending ? (
                    <View
                        accessible
                        accessibilityRole="progressbar"
                        accessibilityLabel="Loading custom properties"
                        style={styles.property}
                    >
                        <View style={[styles.placeholder, styles.placeholderKey]} />
                        <View style={[styles.placeholder, styles.placeholderValue]} />
                    </View>
                ) : query.isError ? (
                    <View style={styles.status}>
                        <Text style={styles.note}>Couldn't load properties.</Text>
                        <Pressable44
                            onPress={() => void query.refetch()}
                            disabled={query.isFetching}
                            accessibilityRole="button"
                            accessibilityLabel="Retry loading properties"
                            accessibilityState={{ disabled: query.isFetching }}
                            pressedBackground={colors.pressed}
                            style={styles.retry}
                            testID="live-event-properties-retry"
                        >
                            <Text style={styles.retryText}>Retry</Text>
                        </Pressable44>
                    </View>
                ) : properties.length === 0 ? (
                    <Text style={[styles.note, styles.empty]}>No custom properties on this event.</Text>
                ) : (
                    properties.map(([key, value], index) => (
                        <View key={key} style={[styles.property, index > 0 && styles.divided]}>
                            <Text style={styles.key} selectable>
                                {key}
                            </Text>
                            <MonoText style={styles.value} selectable>
                                {value}
                            </MonoText>
                        </View>
                    ))
                )}
            </View>
        </View>
    )
}

const useStyles = createStyles(({ colors }) => ({
    section: { marginTop: 20 },
    title: { ...type.label, color: colors.ink, marginBottom: 8, paddingHorizontal: 4 },
    card: {
        paddingHorizontal: 14,
        borderRadius: radii.card,
        borderWidth: 1,
        borderColor: colors.hairline,
        backgroundColor: colors.surface,
    },
    property: { paddingVertical: 12, gap: 6 },
    placeholder: { borderRadius: radii.markSmall, backgroundColor: colors.sunken },
    placeholderKey: { width: 76, height: 12 },
    placeholderValue: { width: 124, height: 16 },
    divided: { borderTopWidth: 1, borderTopColor: colors.rowDivider },
    key: { ...type.meta, color: colors.tertiary },
    value: { flexShrink: 1 },
    note: { ...type.meta, color: colors.tertiary, flexShrink: 1 },
    status: { flexDirection: 'row', alignItems: 'center', minHeight: 52, gap: 10 },
    empty: { paddingVertical: 16 },
    retry: { marginLeft: 'auto', paddingHorizontal: 8, borderRadius: radii.markSmall },
    retryText: { ...type.buttonSmall, color: colors.blue },
}))
