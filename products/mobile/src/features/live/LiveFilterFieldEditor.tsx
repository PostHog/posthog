import { type ReactElement, useState } from 'react'
import { ScrollView, Text, TextInput } from 'react-native'
import { GestureDetector } from 'react-native-gesture-handler'
import type { LivePathMode, LiveTrafficFilters } from '@/model/liveTrafficFilters'
import type { NativeGesture } from '@/ui/gestureTypes'
import { Pressable44 } from '@/ui/Pressable44'
import { SegmentedPill } from '@/ui/SegmentedPill'
import { createStyles, useColors } from '@/ui/theme'
import { radii, type } from '@/ui/tokens'
import { LIVE_FILTER_FIELDS } from './liveFilterLabels'

type InputField = 'hostname' | 'pathPrefix' | 'referringDomain'

export function LiveFilterFieldEditor({
    field,
    filters,
    gesture,
    onSave,
}: {
    field: InputField
    filters: LiveTrafficFilters
    gesture: NativeGesture
    onSave: (value: string, pathMode: LivePathMode) => void
}): ReactElement {
    const [text, setText] = useState(filters[field] ?? '')
    const [mode, setMode] = useState<LivePathMode>(filters.pathMode ?? (filters.pathPrefix ? 'prefix' : 'exact'))
    const colors = useColors()
    const styles = useStyles()
    const isPath = field === 'pathPrefix'
    const invalidDomain = !isPath && /[\s/?#@]/.test(text.trim())
    const direct = field === 'referringDomain' && text === '$direct'
    const save = (): void => {
        if (!invalidDomain) onSave(text, mode)
    }
    return (
        <>
            <GestureDetector gesture={gesture}>
                <ScrollView
                    keyboardShouldPersistTaps="handled"
                    style={styles.scroll}
                    contentContainerStyle={styles.content}
                >
                    {isPath ? (
                        <SegmentedPill
                            segments={(['exact', 'prefix'] as const).map((key) => {
                                const label = key === 'exact' ? 'Is exactly' : 'Starts with'
                                return {
                                    key,
                                    selected: mode === key,
                                    onPress: () => setMode(key),
                                    accessibilityRole: 'radio',
                                    accessibilityLabel: label,
                                    testID: `live-filter-path-${key}`,
                                    children: <Text style={styles.label}>{label}</Text>,
                                }
                            })}
                        />
                    ) : null}
                    <TextInput
                        accessibilityLabel={LIVE_FILTER_FIELDS[field]}
                        autoCapitalize="none"
                        autoCorrect={false}
                        disableFullscreenUI
                        keyboardType="url"
                        returnKeyType="done"
                        placeholder={
                            isPath ? 'e.g. /docs/' : field === 'hostname' ? 'e.g. app.example.com' : 'e.g. google.com'
                        }
                        placeholderTextColor={colors.tertiary}
                        value={direct ? '' : text}
                        onChangeText={setText}
                        onSubmitEditing={save}
                        clearButtonMode="while-editing"
                        style={styles.input}
                        testID={`live-filter-${isPath ? 'path' : field}`}
                    />
                    {invalidDomain ? (
                        <Text style={styles.error} accessibilityRole="alert">
                            Enter just the domain, such as example.com.
                        </Text>
                    ) : null}
                    {field === 'referringDomain' ? (
                        <Pressable44
                            onPress={() => setText(direct ? '' : '$direct')}
                            accessibilityLabel="Direct traffic"
                            accessibilityRole="checkbox"
                            accessibilityState={{ checked: direct }}
                            pressedBackground={colors.pressed}
                            style={[styles.direct, direct && { borderColor: colors.blue }]}
                            testID="live-filter-direct"
                        >
                            <Text style={[styles.label, direct && { color: colors.blue }]}>
                                {direct ? '✓  Direct traffic' : 'Direct traffic'}
                            </Text>
                        </Pressable44>
                    ) : null}
                </ScrollView>
            </GestureDetector>
            <Pressable44
                onPress={save}
                disabled={invalidDomain}
                style={[styles.save, invalidDomain && { opacity: 0.45 }]}
                pressedBackground={colors.inkHover}
                testID="live-filter-save"
            >
                <Text style={styles.saveText}>Done</Text>
            </Pressable44>
        </>
    )
}

const useStyles = createStyles(({ colors }) => ({
    scroll: { flexShrink: 1, flexGrow: 0 },
    content: { paddingTop: 10, paddingBottom: 4, gap: 12 },
    label: { ...type.buttonSmall, color: colors.ink },
    input: {
        ...type.input,
        minHeight: 48,
        paddingHorizontal: 14,
        paddingVertical: 8,
        borderRadius: radii.card,
        borderWidth: 1,
        borderColor: colors.border,
        color: colors.ink,
        backgroundColor: colors.surface,
    },
    direct: {
        minHeight: 44,
        paddingHorizontal: 14,
        justifyContent: 'center',
        alignSelf: 'flex-start',
        borderRadius: radii.pill,
        borderWidth: 1,
        borderColor: colors.border,
    },
    save: {
        minHeight: 46,
        marginTop: 16,
        alignItems: 'center',
        justifyContent: 'center',
        backgroundColor: colors.ink,
        borderRadius: radii.pill,
    },
    saveText: { ...type.button, color: colors.onInk },
    error: { ...type.meta, color: colors.orange },
}))
