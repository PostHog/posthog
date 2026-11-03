import * as Clipboard from 'expo-clipboard'
import { useRouter } from 'expo-router'
import { type ReactElement, type ReactNode, useEffect, useMemo, useRef, useState } from 'react'
import { ActivityIndicator, Linking, ScrollView, StyleSheet, Text, useWindowDimensions, View } from 'react-native'
import { Gesture, GestureDetector, type NativeGesture } from 'react-native-gesture-handler'

import { ACTORS_LIMIT } from '@/api/actors'
import { safeHttpsUrl } from '@/lib/urls'
import type { ActorRow, InsightSnapshot } from '@/model/views'
import { BottomSheet } from '@/ui/BottomSheet'
import { formatAxisDate, formatChange, formatTooltipDate } from '@/ui/chart/chartMath'
import { tooltipContent } from '@/ui/chart/chartSeries'
import type { ChartTooltipPoint, ChartTooltipRow } from '@/ui/chart/types'
import { CheckIcon } from '@/ui/icons/CheckIcon'
import { ChevronLeftIcon } from '@/ui/icons/ChevronLeftIcon'
import { ChevronRightIcon } from '@/ui/icons/ChevronRightIcon'
import { CopyIcon } from '@/ui/icons/CopyIcon'
import { ExternalLinkIcon } from '@/ui/icons/ExternalLinkIcon'
import { InfoIcon } from '@/ui/icons/InfoIcon'
import { PersonIcon } from '@/ui/icons/PersonIcon'
import { PlayIcon } from '@/ui/icons/PlayIcon'
import { Pressable44 } from '@/ui/Pressable44'
import { createStyles, useColors } from '@/ui/theme'
import { radii, type } from '@/ui/tokens'

import { trackViewOpenedInWeb } from '../analytics'
import { SheetTitle } from '../screen/SheetTitle'
import { snapshotFormatter } from '../snapshotChart'
import { useViewsContext } from '../useViewsContext'
import { type PointActors, usePointActors } from '../viewHooks'
import { personWebUrl, viewWebUrl } from '../webLinks'
import { type ChartSheetSource, useLiveSnapshot } from './chartSheetSource'
import { pointActorsInput, recordingRows } from './pointActorsInput'

export interface PointSheetRequest {
    source: ChartSheetSource
    point: ChartTooltipPoint
}

interface PointSheetProps {
    /** Null closes the sheet. */
    request: PointSheetRequest | null
    onClose: () => void
    onOpenAbout: (source: ChartSheetSource) => void
}

type Page = 'point' | 'recordings' | 'people'

function openLink(url: string | undefined, viewType: 'insight' | 'recordings' | 'person'): void {
    const safe = url ? safeHttpsUrl(url) : undefined
    if (!safe) {
        return
    }
    trackViewOpenedInWeb({ viewType, reason: 'action' })
    Linking.openURL(safe).catch(() => undefined)
}

/**
 * Details for one bucket of a chart, opened from its pinned tooltip: every series' value with its change, then
 * "Watch recordings", "View people" and "Open on web". People and recordings come from one actors query at a time.
 */
export function PointSheet({ request, onClose, onOpenAbout }: PointSheetProps): ReactElement {
    const colors = useColors()
    // The last request stays rendered while the sheet slides out.
    const shown = useRef<PointSheetRequest | null>(request)
    if (request) {
        shown.current = request
    }
    const current = shown.current
    const actors = usePointActors()
    const listGesture = useMemo(() => Gesture.Native(), [])
    const close = (): void => {
        actors.close()
        onClose()
    }
    const key = current ? `${current.source.snapshot.shortId}:${current.point.at}:${current.point.index}` : 'none'
    return (
        <BottomSheet
            visible={request !== null}
            onClose={close}
            scrollGesture={listGesture}
            backgroundColor={colors.background}
            accessibilityLabel="Point details"
            testID="point-sheet"
        >
            {current ? (
                <PointBody
                    key={key}
                    request={current}
                    actors={actors}
                    listGesture={listGesture}
                    onClose={close}
                    onOpenAbout={(source) => {
                        actors.close()
                        onOpenAbout(source)
                    }}
                />
            ) : null}
        </BottomSheet>
    )
}

interface PointBodyProps {
    request: PointSheetRequest
    actors: PointActors
    listGesture: NativeGesture
    onClose: () => void
    onOpenAbout: (source: ChartSheetSource) => void
}

function PointBody({ request, actors, listGesture, onClose, onOpenAbout }: PointBodyProps): ReactElement | null {
    const colors = useColors()
    const styles = useStyles()
    const { source, point } = request
    const snapshot = useLiveSnapshot(source)
    const { scope } = useViewsContext()
    const router = useRouter()
    const { height } = useWindowDimensions()
    const [page, setPage] = useState<Page>('point')
    const [selectedKey, setSelectedKey] = useState(point.rows[0]?.key ?? null)
    if (!snapshot) {
        return null
    }
    const formatValue = snapshotFormatter(snapshot)
    const people = snapshot.capabilities.people && selectedKey !== null
    const load = (includeRecordings: boolean): void => {
        const input = selectedKey ? pointActorsInput(snapshot, selectedKey, point.index, includeRecordings) : null
        if (!input) {
            return
        }
        setPage(includeRecordings ? 'recordings' : 'people')
        void actors.load(input)
    }
    const title = formatTooltipDate(point.at, point.interval)
    const maxHeight = Math.round(height * 0.7)

    return (
        <View>
            <SheetTitle title={title} subtitle={snapshot.name} onDone={onClose} />
            <GestureDetector gesture={listGesture}>
                <ScrollView style={{ maxHeight }} contentContainerStyle={styles.body}>
                    {page === 'point' ? (
                        <>
                            <SeriesRows
                                point={point}
                                formatValue={formatValue}
                                selectable={people && point.rows.length > 1}
                                selectedKey={selectedKey}
                                onSelect={setSelectedKey}
                            />
                            <InProgressNote point={point} snapshot={snapshot} formatValue={formatValue} />
                            <View style={styles.actions}>
                                {people ? (
                                    <>
                                        <Action
                                            primary
                                            icon={<PlayIcon size={16} color={colors.onInk} />}
                                            title="Watch recordings"
                                            detail="Sessions from people counted at this point"
                                            onPress={() => load(true)}
                                            testID="point-recordings"
                                        />
                                        <Action
                                            icon={<PersonIcon size={20} />}
                                            title="View people"
                                            detail="People counted at this point"
                                            onPress={() => load(false)}
                                            testID="point-people"
                                        />
                                    </>
                                ) : null}
                                <Action
                                    icon={<ExternalLinkIcon size={19} color={scope ? colors.ink : colors.disabled} />}
                                    title="Open on web"
                                    detail={scope ? undefined : 'Not available in the demo'}
                                    onPress={() =>
                                        openLink(viewWebUrl(scope, `/insights/${snapshot.shortId}`), 'insight')
                                    }
                                    disabled={!scope}
                                    chevron={false}
                                    testID="point-open-web"
                                />
                            </View>
                            <View style={styles.chips}>
                                <Chip
                                    icon={<InfoIcon size={17} />}
                                    label="About this chart"
                                    onPress={() => onOpenAbout(source)}
                                    testID="point-about"
                                />
                                <CopyValueChip point={point} formatValue={formatValue} />
                            </View>
                        </>
                    ) : (
                        <ActorsPage
                            page={page}
                            actors={actors}
                            scopeOpen={Boolean(scope)}
                            onBack={() => setPage('point')}
                            onRetry={() => load(page === 'recordings')}
                            onOpenRecording={(sessionId) =>
                                router.push({ pathname: '/replay/[sessionId]', params: { sessionId, source: 'chart' } })
                            }
                            onOpenPerson={(personId) => openLink(personWebUrl(scope, personId), 'person')}
                        />
                    )}
                </ScrollView>
            </GestureDetector>
        </View>
    )
}

interface SeriesRowsProps {
    point: ChartTooltipPoint
    formatValue: (value: number) => string
    selectable: boolean
    selectedKey: string | null
    onSelect: (key: string) => void
}

function compareText(row: ChartTooltipRow, point: ChartTooltipPoint, formatValue: (value: number) => string): string {
    const previous = row.previous
    if (!previous) {
        return ''
    }
    const date = formatAxisDate(previous.at, point.interval)
    return `Previous: ${formatValue(previous.value)} (${date}) · ${formatChange(row.value, previous.value, formatValue)}`
}

function SeriesRows({ point, formatValue, selectable, selectedKey, onSelect }: SeriesRowsProps): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    return (
        <View style={styles.rows} accessibilityRole={selectable ? 'radiogroup' : undefined}>
            {selectable ? <Text style={styles.pickHint}>Pick a series for people and recordings.</Text> : null}
            {point.rows.map((row) => {
                const selected = row.key === selectedKey
                const content = (
                    <>
                        <View style={styles.rowHead}>
                            <View style={[styles.swatch, { backgroundColor: row.color }]} />
                            <Text style={styles.rowLabel} numberOfLines={1}>
                                {row.label}
                            </Text>
                            {selectable && selected ? <CheckIcon size={16} color={colors.ink} /> : null}
                        </View>
                        <Text style={selectable ? styles.rowValueSmall : styles.rowValue}>
                            {formatValue(row.value)}
                        </Text>
                        {row.previous ? (
                            <Text style={styles.compare}>{compareText(row, point, formatValue)}</Text>
                        ) : null}
                    </>
                )
                if (!selectable) {
                    return (
                        <View key={row.key} style={styles.row}>
                            {content}
                        </View>
                    )
                }
                return (
                    <Pressable44
                        key={row.key}
                        onPress={() => onSelect(row.key)}
                        accessibilityRole="radio"
                        accessibilityState={{ checked: selected }}
                        style={[styles.row, styles.selectableRow, selected && styles.selectedRow]}
                        pressedBackground={colors.pressed}
                    >
                        {content}
                    </Pressable44>
                )
            })}
        </View>
    )
}

function InProgressNote({
    point,
    snapshot,
    formatValue,
}: {
    point: ChartTooltipPoint
    snapshot: InsightSnapshot
    formatValue: (value: number) => string
}): ReactElement | null {
    const colors = useColors()
    const styles = useStyles()
    const dataUntil = snapshot.lastRefreshAt ? Date.parse(snapshot.lastRefreshAt) : undefined
    const note = tooltipContent(point, {
        formatValue,
        compact: false,
        maxRows: Number.POSITIVE_INFINITY,
        dataUntil,
    }).note
    if (!note) {
        return null
    }
    return (
        <View style={styles.note}>
            <InfoIcon size={16} color={colors.tertiary} />
            <Text style={styles.noteText}>{`${note} The final value can still change.`}</Text>
        </View>
    )
}

interface ActionProps {
    icon: ReactNode
    title: string
    detail?: string
    onPress: () => void
    primary?: boolean
    disabled?: boolean
    chevron?: boolean
    testID?: string
}

function Action({
    icon,
    title,
    detail,
    onPress,
    primary = false,
    disabled = false,
    chevron = true,
    testID,
}: ActionProps): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    return (
        <Pressable44
            onPress={onPress}
            disabled={disabled}
            style={[styles.action, primary && styles.actionPrimary]}
            pressedBackground={primary ? colors.inkHover : colors.pressed}
            testID={testID}
        >
            <View style={styles.actionIcon}>{icon}</View>
            <View style={styles.actionText}>
                <Text style={[styles.actionTitle, primary && styles.onInk, disabled && styles.disabledText]}>
                    {title}
                </Text>
                {detail ? <Text style={[styles.actionDetail, primary && styles.onInkDetail]}>{detail}</Text> : null}
            </View>
            {chevron ? <ChevronRightIcon size={13} color={primary ? colors.onInk : colors.ink} /> : null}
        </Pressable44>
    )
}

function Chip({
    icon,
    label,
    onPress,
    testID,
}: {
    icon: ReactNode
    label: string
    onPress: () => void
    testID?: string
}): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    return (
        <Pressable44 onPress={onPress} style={styles.chip} pressedBackground={colors.pressed} testID={testID}>
            {icon}
            <Text style={styles.chipLabel}>{label}</Text>
        </Pressable44>
    )
}

const COPIED_MS = 2000

function CopyValueChip({
    point,
    formatValue,
}: {
    point: ChartTooltipPoint
    formatValue: (value: number) => string
}): ReactElement | null {
    const [copied, setCopied] = useState(false)
    useEffect(() => {
        if (!copied) {
            return undefined
        }
        const timer = setTimeout(() => setCopied(false), COPIED_MS)
        return () => clearTimeout(timer)
    }, [copied])
    const top = point.rows[0]
    if (!top) {
        return null
    }
    return (
        <Chip
            icon={copied ? <CheckIcon size={16} /> : <CopyIcon size={16} />}
            label={copied ? 'Copied' : 'Copy value'}
            onPress={() => {
                void Clipboard.setStringAsync(formatValue(top.value)).then(() => setCopied(true))
            }}
            testID="point-copy"
        />
    )
}

interface ActorsPageProps {
    page: Exclude<Page, 'point'>
    actors: PointActors
    /** False in demo mode, where there is no project to open. */
    scopeOpen: boolean
    onBack: () => void
    onRetry: () => void
    onOpenRecording: (sessionId: string) => void
    onOpenPerson: (personId: string) => void
}

function ActorsPage({
    page,
    actors,
    scopeOpen,
    onBack,
    onRetry,
    onOpenRecording,
    onOpenPerson,
}: ActorsPageProps): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    const recordings = page === 'recordings'
    const state = actors.people
    return (
        <View style={styles.actorsPage}>
            <Pressable44
                onPress={onBack}
                style={styles.back}
                accessibilityLabel="Back to the point"
                testID="point-back"
            >
                <ChevronLeftIcon size={13} color={colors.blue} />
                <Text style={styles.backText}>Back</Text>
            </Pressable44>
            <Text style={styles.pageTitle} accessibilityRole="header">
                {recordings ? 'Recordings at this point' : 'People at this point'}
            </Text>
            {!state || state.isLoading ? (
                <View style={styles.loading} accessibilityLabel="Loading" accessibilityRole="progressbar">
                    <ActivityIndicator color={colors.ink} />
                </View>
            ) : state.isError ? (
                <View style={styles.message}>
                    <Text style={styles.messageText}>{state.error?.message ?? "Couldn't load people. Try again."}</Text>
                    <Chip icon={null} label="Try again" onPress={onRetry} testID="point-retry" />
                </View>
            ) : (
                <ActorList
                    rows={state.data ?? []}
                    recordings={recordings}
                    scopeOpen={scopeOpen}
                    onOpenRecording={onOpenRecording}
                    onOpenPerson={onOpenPerson}
                />
            )}
        </View>
    )
}

interface ActorListProps {
    rows: ActorRow[]
    recordings: boolean
    scopeOpen: boolean
    onOpenRecording: (sessionId: string) => void
    onOpenPerson: (personId: string) => void
}

function ActorList({ rows, recordings, scopeOpen, onOpenRecording, onOpenPerson }: ActorListProps): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    const demoNote = scopeOpen ? null : 'Not available in the demo'
    const limited = rows.length >= ACTORS_LIMIT ? `Showing the first ${ACTORS_LIMIT} people.` : null
    if (recordings) {
        const sessions = recordingRows(rows)
        if (sessions.length === 0) {
            return <Text style={styles.messageText}>No recordings at this point.</Text>
        }
        return (
            <View style={styles.list} testID="point-recording-list">
                {sessions.map((row) => (
                    <ActorRowView
                        key={row.key}
                        icon={<PlayIcon size={12} color={colors.ink} />}
                        title={row.personName}
                        detail={[row.position ?? 'Recording', demoNote].filter(Boolean).join(' · ')}
                        disabled={!scopeOpen}
                        inApp
                        onPress={() => onOpenRecording(row.sessionId)}
                    />
                ))}
                {limited ? <Text style={styles.listNote}>{limited}</Text> : null}
            </View>
        )
    }
    if (rows.length === 0) {
        return <Text style={styles.messageText}>No people at this point.</Text>
    }
    return (
        <View style={styles.list} testID="point-people-list">
            {rows.map((person) => (
                <ActorRowView
                    key={person.id}
                    icon={<PersonIcon size={18} />}
                    title={person.name}
                    detail={demoNote ?? undefined}
                    disabled={!scopeOpen}
                    onPress={() => onOpenPerson(person.id)}
                />
            ))}
            {limited ? <Text style={styles.listNote}>{limited}</Text> : null}
        </View>
    )
}

function ActorRowView({
    icon,
    title,
    detail,
    disabled,
    inApp = false,
    onPress,
}: {
    icon: ReactNode
    title: string
    detail?: string
    disabled: boolean
    /** True when the row opens a screen in the app, which takes a chevron instead of the external-link mark. */
    inApp?: boolean
    onPress: () => void
}): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    return (
        <Pressable44 onPress={onPress} disabled={disabled} style={styles.actorRow} pressedBackground={colors.pressed}>
            <View style={styles.actorIcon}>{icon}</View>
            <View style={styles.actionText}>
                <Text style={styles.actorTitle} numberOfLines={1}>
                    {title}
                </Text>
                {detail ? <Text style={styles.actionDetail}>{detail}</Text> : null}
            </View>
            {disabled ? null : inApp ? (
                <ChevronRightIcon size={13} color={colors.tertiary} />
            ) : (
                <ExternalLinkIcon size={16} color={colors.tertiary} />
            )}
        </Pressable44>
    )
}

const useStyles = createStyles(({ colors }) => ({
    body: {
        gap: 14,
        paddingBottom: 8,
    },
    rows: {
        gap: 10,
    },
    pickHint: {
        ...type.meta,
        color: colors.tertiary,
        paddingHorizontal: 4,
    },
    row: {
        paddingHorizontal: 4,
    },
    selectableRow: {
        padding: 12,
        borderRadius: radii.option,
        borderWidth: 1,
        borderColor: colors.hairline,
        backgroundColor: colors.surface,
    },
    selectedRow: {
        borderColor: colors.ink,
    },
    rowHead: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: 10,
    },
    swatch: {
        width: 10,
        height: 10,
        borderRadius: 3,
    },
    rowLabel: {
        fontSize: 15,
        lineHeight: 20,
        color: colors.muted,
        flex: 1,
    },
    rowValue: {
        fontSize: 30,
        lineHeight: 35,
        fontWeight: '700',
        letterSpacing: -0.6,
        color: colors.ink,
        marginLeft: 20,
        fontVariant: ['tabular-nums'],
    },
    rowValueSmall: {
        fontSize: 22,
        lineHeight: 28,
        fontWeight: '700',
        letterSpacing: -0.4,
        color: colors.ink,
        marginLeft: 20,
        fontVariant: ['tabular-nums'],
    },
    compare: {
        fontSize: 14,
        lineHeight: 20,
        color: colors.secondary,
        marginLeft: 20,
        fontVariant: ['tabular-nums'],
    },
    note: {
        flexDirection: 'row',
        alignItems: 'flex-start',
        gap: 8,
        paddingVertical: 10,
        paddingHorizontal: 12,
        borderRadius: radii.card,
        borderWidth: 1,
        borderColor: colors.hairline,
        backgroundColor: colors.surface,
    },
    noteText: {
        ...type.metaSmall,
        lineHeight: 20,
        color: colors.muted,
        flex: 1,
    },
    actions: {
        gap: 8,
    },
    action: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: 12,
        minHeight: 56,
        paddingVertical: 8,
        paddingHorizontal: 14,
        borderRadius: radii.option,
        borderWidth: 1,
        borderColor: colors.border,
        backgroundColor: colors.surface,
    },
    actionPrimary: {
        borderColor: colors.ink,
        backgroundColor: colors.ink,
    },
    actionIcon: {
        width: 22,
        alignItems: 'center',
    },
    actionText: {
        flex: 1,
        minWidth: 0,
    },
    actionTitle: {
        ...type.bodyStrong,
        lineHeight: 20,
        color: colors.ink,
    },
    actionDetail: {
        ...type.meta,
        color: colors.tertiary,
    },
    onInk: {
        color: colors.onInk,
    },
    onInkDetail: {
        color: colors.disabled,
    },
    disabledText: {
        color: colors.disabled,
    },
    chips: {
        flexDirection: 'row',
        flexWrap: 'wrap',
        gap: 8,
    },
    chip: {
        height: 36,
        flexDirection: 'row',
        alignItems: 'center',
        gap: 8,
        paddingLeft: 12,
        paddingRight: 14,
        borderRadius: radii.pill,
        borderWidth: 1,
        borderColor: colors.border,
        backgroundColor: colors.surface,
    },
    chipLabel: {
        fontSize: 14,
        fontWeight: '600',
        color: colors.ink,
    },
    actorsPage: {
        gap: 10,
    },
    back: {
        alignSelf: 'flex-start',
        height: 36,
        flexDirection: 'row',
        alignItems: 'center',
        gap: 4,
        paddingRight: 12,
        paddingLeft: 2,
    },
    backText: {
        ...type.bodyStrong,
        color: colors.blue,
    },
    pageTitle: {
        ...type.sectionHeader,
        color: colors.ink,
        paddingHorizontal: 4,
    },
    loading: {
        paddingVertical: 28,
        alignItems: 'center',
    },
    message: {
        gap: 12,
        alignItems: 'flex-start',
    },
    messageText: {
        ...type.bodySmall,
        color: colors.muted,
        paddingHorizontal: 4,
    },
    list: {
        borderRadius: radii.option,
        borderWidth: 1,
        borderColor: colors.hairline,
        backgroundColor: colors.surface,
        overflow: 'hidden',
    },
    listNote: {
        ...type.meta,
        color: colors.tertiary,
        padding: 12,
    },
    actorRow: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: 12,
        minHeight: 56,
        paddingHorizontal: 14,
        borderBottomWidth: StyleSheet.hairlineWidth,
        borderBottomColor: colors.rowDivider,
    },
    actorIcon: {
        width: 32,
        height: 32,
        borderRadius: 16,
        backgroundColor: colors.sunken,
        alignItems: 'center',
        justifyContent: 'center',
    },
    actorTitle: {
        ...type.bodyStrong,
        lineHeight: 20,
        color: colors.ink,
    },
}))
