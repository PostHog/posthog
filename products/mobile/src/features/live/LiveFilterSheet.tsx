import { type ReactElement, useMemo, useState } from 'react'
import { Keyboard, ScrollView, Switch, Text, View } from 'react-native'
import { Gesture, GestureDetector } from 'react-native-gesture-handler'
import { useReanimatedKeyboardAnimation } from 'react-native-keyboard-controller'
import {
    DEFAULT_LIVE_TRAFFIC_FILTERS,
    hasLiveTrafficFilters,
    normalizeLiveTrafficFilters,
} from '@/model/liveTrafficFilters'
import { BottomSheet } from '@/ui/BottomSheet'
import { Eyebrow } from '@/ui/Eyebrow'
import { ChevronLeftIcon } from '@/ui/icons/ChevronLeftIcon'
import { ChevronRightIcon } from '@/ui/icons/ChevronRightIcon'
import { Pressable44 } from '@/ui/Pressable44'
import { SegmentedPill } from '@/ui/SegmentedPill'
import { createStyles, useColors } from '@/ui/theme'
import { radii, type } from '@/ui/tokens'

import { trackLiveAudienceChanged } from './analytics'
import { LiveFilterFieldEditor } from './LiveFilterFieldEditor'
import { LiveFilterPicker } from './LiveFilterPicker'
import { LIVE_FILTER_FIELDS, type LiveFilterField, liveFilterValue } from './liveFilterLabels'
import { useLivePreference } from './livePreference'

const AUDIENCES = [
    { key: 'all', label: 'All' },
    { key: 'web', label: 'Web' },
    { key: 'mobile', label: 'Mobile' },
] as const
const SECTIONS = [
    { label: 'Page location', fields: ['hostname', 'pathPrefix'] },
    { label: 'Traffic source', fields: ['channelType', 'referringDomain'] },
    { label: 'Visitor', fields: ['countryCode', 'deviceType'] },
] as const

export function LiveFilterSheet({ onClose }: { onClose: () => void }): ReactElement {
    const { preference, trafficFilters, setLiveFilters } = useLivePreference()
    const [audience, setAudience] = useState(preference)
    const [draft, setDraft] = useState(trafficFilters)
    const [editing, setEditing] = useState<LiveFilterField | null>(null)
    const keyboard = useReanimatedKeyboardAnimation()
    const gesture = useMemo(() => Gesture.Native(), [])
    const colors = useColors()
    const styles = useStyles()
    const canClear = audience !== 'all' || hasLiveTrafficFilters(draft)
    const back = (): void => {
        Keyboard.dismiss()
        setEditing(null)
    }
    const close = (): void => {
        Keyboard.dismiss()
        onClose()
    }
    const apply = (): void => {
        if (audience !== preference) trackLiveAudienceChanged({ preference: audience })
        setLiveFilters(audience, normalizeLiveTrafficFilters(draft))
        close()
    }
    return (
        <BottomSheet
            visible
            onClose={editing ? back : close}
            paddingHorizontal={20}
            keyboardHeight={keyboard.height}
            scrollGesture={gesture}
            dragResetKey={editing}
            accessibilityLabel={editing ? LIVE_FILTER_FIELDS[editing] : 'Live filters'}
            testID="live-filter-sheet"
        >
            <View style={styles.head}>
                {editing ? (
                    <Pressable44
                        onPress={back}
                        accessibilityLabel="Back to Live filters"
                        pressedBackground={colors.pressed}
                        style={styles.back}
                        testID="live-filter-back"
                    >
                        <ChevronLeftIcon size={15} color={colors.ink} />
                    </Pressable44>
                ) : null}
                <Text style={styles.title} accessibilityRole="header">
                    {editing ? LIVE_FILTER_FIELDS[editing] : 'Live filters'}
                </Text>
                {!editing || draft[editing] ? (
                    <Pressable44
                        onPress={() => {
                            if (editing) {
                                setDraft({
                                    ...draft,
                                    [editing]: '',
                                    ...(editing === 'pathPrefix' ? { pathMode: 'exact' } : {}),
                                })
                                back()
                            } else {
                                setAudience('all')
                                setDraft(DEFAULT_LIVE_TRAFFIC_FILTERS)
                            }
                        }}
                        disabled={!canClear}
                        accessibilityLabel={editing ? `Clear ${LIVE_FILTER_FIELDS[editing]}` : 'Clear all filters'}
                        pressedBackground={colors.sunken}
                        style={styles.clear}
                        testID="live-filters-clear"
                    >
                        <Text style={[styles.clearText, !canClear && styles.disabledText]}>
                            {editing ? 'Clear' : 'Clear all'}
                        </Text>
                    </Pressable44>
                ) : null}
            </View>
            {editing === 'countryCode' || editing === 'deviceType' || editing === 'channelType' ? (
                <LiveFilterPicker
                    key={editing}
                    field={editing}
                    value={draft[editing] ?? ''}
                    gesture={gesture}
                    onChoose={(value) => {
                        setDraft({ ...draft, [editing]: value })
                        back()
                    }}
                />
            ) : editing ? (
                <LiveFilterFieldEditor
                    key={editing}
                    field={editing}
                    filters={draft}
                    gesture={gesture}
                    onSave={(value, pathMode) => {
                        setDraft(
                            normalizeLiveTrafficFilters({
                                ...draft,
                                [editing]: value,
                                ...(editing === 'pathPrefix' ? { pathMode } : {}),
                            })
                        )
                        back()
                    }}
                />
            ) : (
                <>
                    <GestureDetector gesture={gesture}>
                        <ScrollView
                            style={styles.scroll}
                            contentContainerStyle={styles.sections}
                            testID="live-filter-list"
                        >
                            <View style={styles.section}>
                                <Eyebrow>Platform</Eyebrow>
                                <SegmentedPill
                                    segments={AUDIENCES.map(({ key, label }) => ({
                                        key,
                                        selected: audience === key,
                                        accessibilityLabel: label,
                                        accessibilityRole: 'radio',
                                        onPress: () => setAudience(key),
                                        testID: `live-filter-${key}`,
                                        children: <Text style={styles.label}>{label}</Text>,
                                    }))}
                                />
                            </View>
                            <View style={styles.switchRow}>
                                <View style={styles.switchLabel}>
                                    <Text style={styles.label}>Exclude bot traffic</Text>
                                    <Text style={styles.hint}>Hide events PostHog identifies as bots.</Text>
                                </View>
                                <Switch
                                    accessibilityLabel="Exclude bot traffic"
                                    value={draft.excludeBots}
                                    onValueChange={(excludeBots) => setDraft({ ...draft, excludeBots })}
                                    trackColor={{ true: colors.switchOn, false: colors.switchOff }}
                                    thumbColor={colors.white}
                                    testID="live-filter-bots"
                                />
                            </View>
                            {SECTIONS.map(({ label, fields }) => (
                                <View style={styles.section} key={label}>
                                    <Eyebrow>{label}</Eyebrow>
                                    <View style={styles.group}>
                                        {fields.map((field, index) => {
                                            const current = liveFilterValue(field, draft)
                                            return (
                                                <Pressable44
                                                    key={field}
                                                    onPress={() => setEditing(field)}
                                                    accessibilityLabel={`${LIVE_FILTER_FIELDS[field]}, ${current || 'Any'}`}
                                                    style={[styles.row, index > 0 && styles.divider]}
                                                    pressedBackground={colors.pressed}
                                                    hitSlop={0}
                                                    testID={`live-filter-edit-${field}`}
                                                >
                                                    <Text style={styles.rowTitle}>{LIVE_FILTER_FIELDS[field]}</Text>
                                                    <Text
                                                        numberOfLines={2}
                                                        style={[styles.value, !!current && styles.activeValue]}
                                                    >
                                                        {current || 'Any'}
                                                    </Text>
                                                    <ChevronRightIcon size={12} color={colors.tertiary} />
                                                </Pressable44>
                                            )
                                        })}
                                    </View>
                                </View>
                            ))}
                        </ScrollView>
                    </GestureDetector>
                    <View style={styles.footer}>
                        <Pressable44
                            onPress={close}
                            style={[styles.button, styles.cancel]}
                            pressedBackground={colors.sunken}
                        >
                            <Text style={styles.label}>Cancel</Text>
                        </Pressable44>
                        <Pressable44
                            onPress={apply}
                            style={[styles.button, styles.apply]}
                            pressedBackground={colors.inkHover}
                            testID="live-filters-apply"
                        >
                            <Text style={styles.applyText}>Apply filters</Text>
                        </Pressable44>
                    </View>
                </>
            )}
        </BottomSheet>
    )
}

const useStyles = createStyles(({ colors }) => ({
    head: { flexDirection: 'row', alignItems: 'center', gap: 8, minHeight: 44, marginTop: 6 },
    title: { ...type.sheetTitleLarge, color: colors.ink, flex: 1 },
    back: { minWidth: 36, minHeight: 44, justifyContent: 'center', alignItems: 'center', borderRadius: radii.pill },
    clear: { minHeight: 44, paddingHorizontal: 8, borderRadius: radii.pill, justifyContent: 'center' },
    clearText: { ...type.buttonSmall, color: colors.ink },
    disabledText: { color: colors.disabled },
    scroll: { flexGrow: 0, flexShrink: 1 },
    sections: { paddingTop: 10, paddingBottom: 4, gap: 14 },
    section: { gap: 7 },
    switchRow: { flexDirection: 'row', alignItems: 'center', gap: 12, paddingHorizontal: 2, paddingVertical: 4 },
    switchLabel: { flex: 1, gap: 3 },
    label: { ...type.buttonSmall, color: colors.ink },
    hint: { ...type.meta, color: colors.secondary },
    group: { borderWidth: 1, borderColor: colors.hairline, borderRadius: radii.card, overflow: 'hidden' },
    row: {
        flexDirection: 'row',
        gap: 8,
        alignItems: 'center',
        minHeight: 44,
        paddingHorizontal: 12,
        paddingVertical: 8,
    },
    divider: { borderTopWidth: 1, borderColor: colors.rowDivider },
    rowTitle: { ...type.bodySmallStrong, color: colors.ink, flexShrink: 1 },
    value: { ...type.metaSmall, color: colors.secondary, textAlign: 'right', flex: 1 },
    activeValue: { color: colors.blue },
    footer: { flexDirection: 'row', gap: 10, paddingTop: 16 },
    button: { minHeight: 46, borderRadius: radii.pill, alignItems: 'center', justifyContent: 'center' },
    cancel: { flex: 1, borderWidth: 1, borderColor: colors.border },
    apply: { flex: 2, backgroundColor: colors.ink },
    applyText: { ...type.button, color: colors.onInk },
}))
