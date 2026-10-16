import type { ReactElement, ReactNode } from 'react'
import { StyleSheet, Text, type TextStyle, View } from 'react-native'

import { sourceInfo } from '@/model/sources'
import type { ReportOwner, ReportPriority, ReportView } from '@/model/types'
import { Avatar } from '@/ui/Avatar'
import { Dot } from '@/ui/Dot'
import { ChevronDownIcon } from '@/ui/icons/ChevronDownIcon'
import { Pressable44 } from '@/ui/Pressable44'
import { colors, iconSizes, lineHeight, radii, type } from '@/ui/tokens'

import { priorityTone } from '../priority/PrioritySheet'

const AVATAR_SIZE = 18
const PRIORITY_DOT_SIZE = 8

interface ReportMetaProps {
    report: ReportView
    onReassign: () => void
    onChangePriority: () => void
}

// Facts that never change (source, start time) read as a quiet byline. Facts the user can change (owner, priority)
// are chips that open the sheet for that value.
export function ReportMeta({ report, onReassign, onChangePriority }: ReportMetaProps): ReactElement {
    const { Icon } = sourceInfo(report.sourceProduct)
    const since = report.since ? sinceText(report.since) : undefined
    return (
        <View>
            <View
                style={styles.byline}
                accessible
                accessibilityLabel={[`From ${report.sourceLabel}`, since ? lowerFirst(since) : undefined]
                    .filter(Boolean)
                    .join(', ')}
                testID="report-byline"
            >
                <View style={styles.segment}>
                    <View style={styles.glyph}>
                        <Icon size={iconSizes.inline} color={colors.secondary} />
                    </View>
                    <Text style={styles.bylineText}>{report.sourceLabel}</Text>
                    {/* The separator rides on the end of the segment before it, so a wrapped line never starts with a dot. */}
                    {since ? <Text style={[styles.bylineText, styles.separator]}>·</Text> : null}
                </View>
                {since ? (
                    <View style={styles.segment}>
                        <Text style={styles.bylineText}>{since}</Text>
                    </View>
                ) : null}
            </View>
            <View style={styles.chips}>
                <OwnerChip owner={report.owner} onPress={onReassign} />
                <PriorityChip priority={report.priority} onPress={onChangePriority} />
            </View>
        </View>
    )
}

function OwnerChip({ owner, onPress }: { owner: ReportOwner; onPress: () => void }): ReactElement {
    if (owner.kind === 'none') {
        return (
            <Chip
                accessibilityLabel="No owner, assign"
                leading={<View style={styles.unassigned} />}
                label="Assign"
                labelStyle={styles.alert}
                onPress={onPress}
                testID="report-owner-chip"
            />
        )
    }
    const agent = owner.kind === 'agent'
    return (
        <Chip
            accessibilityLabel={`Owner: ${owner.name}, change`}
            leading={
                <Avatar name={owner.name} color={agent ? colors.blue : undefined} size={AVATAR_SIZE} fontSize={8} />
            }
            label={owner.name}
            labelStyle={agent ? styles.agent : undefined}
            onPress={onPress}
            testID="report-owner-chip"
        />
    )
}

function PriorityChip({ priority, onPress }: { priority?: ReportPriority; onPress: () => void }): ReactElement {
    const tone = priorityTone(priority)
    return (
        <Chip
            accessibilityLabel={priority ? `Priority ${priority}, change` : 'No priority, set'}
            leading={
                <View style={styles.priorityDot}>
                    <Dot color={tone.dot} size={PRIORITY_DOT_SIZE} />
                </View>
            }
            label={priority ?? 'Priority'}
            labelStyle={{ color: tone.text }}
            onPress={onPress}
            testID="report-priority-chip"
        />
    )
}

interface ChipProps {
    accessibilityLabel: string
    leading: ReactNode
    label: string
    labelStyle?: TextStyle
    onPress: () => void
    testID: string
}

// The trailing chevron is what tells these chips apart from the read-only byline above them.
function Chip({ accessibilityLabel, leading, label, labelStyle, onPress, testID }: ChipProps): ReactElement {
    return (
        <Pressable44
            onPress={onPress}
            accessibilityRole="button"
            accessibilityLabel={accessibilityLabel}
            pressedBackground={colors.pressed}
            style={styles.chip}
            testID={testID}
        >
            {leading}
            <View style={styles.chipBody}>
                <Text numberOfLines={1} style={[styles.chipLabel, labelStyle]}>
                    {label}
                </Text>
                <ChevronDownIcon size={iconSizes.small} color={colors.tertiary} />
            </View>
        </Pressable44>
    )
}

// Live times start with "Today" or read "Just now", which would sit oddly after "Since".
function sinceText(moment: string): string {
    if (moment === 'Just now') {
        return moment
    }
    return `Since ${moment.replace(/^Today /, 'today ')}`
}

function lowerFirst(value: string): string {
    return value.charAt(0).toLowerCase() + value.slice(1)
}

const styles = StyleSheet.create({
    byline: {
        marginTop: 10,
        flexDirection: 'row',
        flexWrap: 'wrap',
        alignItems: 'center',
        rowGap: 2,
    },
    segment: {
        flexDirection: 'row',
        alignItems: 'center',
        flexShrink: 1,
    },
    bylineText: {
        ...type.meta,
        color: colors.secondary,
        flexShrink: 1,
    },
    separator: {
        color: colors.dotSeparator,
        marginHorizontal: 6,
        flexShrink: 0,
    },
    glyph: {
        marginRight: 4,
    },
    chips: {
        marginTop: 10,
        flexDirection: 'row',
        flexWrap: 'wrap',
        gap: 8,
    },
    chip: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: 6,
        height: 32,
        maxWidth: '100%',
        paddingLeft: 8,
        paddingRight: 10,
        borderRadius: radii.pill,
        borderWidth: 1,
        borderColor: colors.border,
        backgroundColor: colors.white,
    },
    chipBody: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: 4,
        flexShrink: 1,
    },
    chipLabel: {
        flexShrink: 1,
        fontSize: 13,
        lineHeight: lineHeight(13, 1.3),
        fontWeight: '500',
        color: colors.ink,
    },
    alert: {
        color: colors.orange,
    },
    agent: {
        color: colors.blue,
    },
    unassigned: {
        width: AVATAR_SIZE,
        height: AVATAR_SIZE,
        borderRadius: AVATAR_SIZE / 2,
        borderWidth: 1.5,
        borderStyle: 'dashed',
        borderColor: colors.orange,
    },
    // Centers the 8pt dot in the same 18pt slot the owner avatar takes, so both chips start their text at one inset.
    priorityDot: {
        width: AVATAR_SIZE,
        height: AVATAR_SIZE,
        alignItems: 'center',
        justifyContent: 'center',
    },
})
