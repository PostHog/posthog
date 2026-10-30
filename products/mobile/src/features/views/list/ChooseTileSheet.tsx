import { type ReactElement, useEffect, useMemo, useRef, useState } from 'react'
import { ActivityIndicator, ScrollView, Text, useWindowDimensions, View } from 'react-native'
import { Gesture, GestureDetector } from 'react-native-gesture-handler'
import Svg, { Path, Rect, Text as SvgText } from 'react-native-svg'

import type { DashboardTileView, InsightSnapshot, PinView } from '@/model/views'
import { BottomSheet } from '@/ui/BottomSheet'
import { CheckIcon } from '@/ui/icons/CheckIcon'
import { Pressable44 } from '@/ui/Pressable44'
import { createStyles, useColors } from '@/ui/theme'
import { motion, radii, type } from '@/ui/tokens'

import { type TileSheetEntry, trackPinTileSheetClosed } from '../analytics'
import { insightQueryKey, tileTarget } from '../items'
import { snapshotFormatter } from '../snapshotChart'
import { useViewsContext } from '../useViewsContext'
import { useSnapshot } from '../viewsCache'
import { splitTilesByEligibility } from './tileEligibility'
import { useDashboardTiles } from './useDashboardTiles'

export interface ChooseTileTarget {
    pin: PinView
    mode: 'number' | 'chart'
    /** Opened by picking Number or Chart on a pin without a tile: the first tile that can show it is chosen at once. */
    chooseFirst: boolean
    entry: TileSheetEntry
}

interface ChooseTileSheetProps {
    target: ChooseTileTarget | null
    onClose: () => void
    onChoose: (pin: PinView, mode: 'number' | 'chart', tile: DashboardTileView) => void
}

/** "Choose tile" for a dashboard pin in Number or Chart mode. */
export function ChooseTileSheet({ target, onClose, onChoose }: ChooseTileSheetProps): ReactElement | null {
    // Keeps the last target until the exit animation ends, so the sheet slides out with its content.
    const [shown, setShown] = useState(target)
    if (target !== null && target !== shown) {
        setShown(target)
    }
    useEffect(() => {
        if (target) {
            return undefined
        }
        const timer = setTimeout(() => setShown(null), motion.sheet)
        return () => clearTimeout(timer)
    }, [target])
    if (!shown) {
        return null
    }
    return (
        <TileSheet
            key={shown.pin.shortcutId}
            target={shown}
            visible={target !== null}
            onClose={onClose}
            onChoose={onChoose}
        />
    )
}

interface TileSheetProps {
    target: ChooseTileTarget
    visible: boolean
    onClose: () => void
    onChoose: ChooseTileSheetProps['onChoose']
}

function TileSheet({ target, visible, onClose, onChoose }: TileSheetProps): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    const { pin, mode, chooseFirst, entry } = target
    const { height: windowHeight } = useWindowDimensions()
    const listGesture = useMemo(() => Gesture.Native(), [])
    const { dashboard, retry } = useDashboardTiles(pin.ref)
    const [chosen, setChosen] = useState<number | null>(pin.display.tileId ?? null)
    const tiles = dashboard.data?.tiles
    const groups = useMemo(() => (tiles ? splitTilesByEligibility(tiles, mode) : null), [tiles, mode])
    const choose = (tile: DashboardTileView): void => {
        setChosen(tile.tileId)
        onChoose(pin, mode, tile)
    }
    // The automatic first choice does not count as a pick, so `picked` stays a choice the person made.
    const picked = useRef(false)
    const closed = useRef(false)
    // The sheet stays mounted through its exit animation, so a reopen in that time starts a new session here.
    useEffect(() => {
        if (visible) {
            closed.current = false
            picked.current = false
        }
    }, [visible])
    const pick = (tile: DashboardTileView): void => {
        picked.current = true
        choose(tile)
    }
    const close = (): void => {
        if (!closed.current) {
            closed.current = true
            trackPinTileSheetClosed({
                entry,
                picked: picked.current,
                tilesUsable: groups ? groups.usable.length : null,
                tilesUnusable: groups ? groups.unusable.length : null,
            })
        }
        onClose()
    }
    const chooseRef = useRef(choose)
    chooseRef.current = choose
    const choseFirst = useRef(false)
    useEffect(() => {
        if (!chooseFirst || !groups || choseFirst.current) {
            return
        }
        choseFirst.current = true
        const first = groups.usable[0]
        if (first) {
            chooseRef.current(first)
        }
    }, [chooseFirst, groups])

    return (
        <BottomSheet
            visible={visible}
            onClose={close}
            scrollGesture={listGesture}
            accessibilityLabel="Choose tile"
            testID="choose-tile-sheet"
        >
            <View style={styles.head}>
                <View style={styles.headText}>
                    <Text style={styles.sub} numberOfLines={1}>
                        {pin.name}
                    </Text>
                    <Text style={styles.title} accessibilityRole="header">
                        Choose tile
                    </Text>
                </View>
                <Pressable44
                    onPress={close}
                    accessibilityLabel="Done"
                    pressedBackground={colors.background}
                    style={styles.done}
                    testID="choose-tile-done"
                >
                    <Text style={styles.doneText}>Done</Text>
                </Pressable44>
            </View>
            {groups ? (
                <GestureDetector gesture={listGesture}>
                    <ScrollView
                        style={{ maxHeight: windowHeight * 0.6 }}
                        contentContainerStyle={styles.list}
                        accessibilityRole="radiogroup"
                        accessibilityLabel={`Tiles on ${pin.name}`}
                    >
                        {groups.usable.map((tile) => (
                            <TileOption
                                key={tile.tileId}
                                dashboardRef={pin.ref ?? ''}
                                tile={tile}
                                selected={tile.tileId === chosen}
                                onPick={pick}
                            />
                        ))}
                        {groups.unusable.length > 0 ? (
                            <View style={styles.sectionHead} testID="choose-tile-unusable">
                                <Text style={styles.sectionTitle} accessibilityRole="header">
                                    {groups.usable.length > 0
                                        ? `Can't show as a ${mode}`
                                        : `No tile here shows as a ${mode}`}
                                </Text>
                                <Text style={styles.note}>A pin shows one number, or one line over time.</Text>
                            </View>
                        ) : null}
                        {groups.unusable.map(({ tile, reason }) => (
                            <TileOption
                                key={tile.tileId}
                                dashboardRef={pin.ref ?? ''}
                                tile={tile}
                                selected={tile.tileId === chosen}
                                onPick={pick}
                                reason={reason}
                            />
                        ))}
                    </ScrollView>
                </GestureDetector>
            ) : dashboard.isError ? (
                <View style={styles.state}>
                    <Text style={styles.stateText}>{dashboard.error?.message}</Text>
                    <Pressable44 onPress={retry} pressedBackground={colors.inkHover} style={styles.retry}>
                        <Text style={styles.retryText}>Try again</Text>
                    </Pressable44>
                </View>
            ) : (
                <View style={styles.state} accessibilityLabel="Loading the tiles" accessibilityRole="progressbar">
                    <ActivityIndicator color={colors.tertiary} />
                </View>
            )}
        </BottomSheet>
    )
}

interface TileOptionProps {
    dashboardRef: string
    tile: DashboardTileView
    selected: boolean
    onPick: (tile: DashboardTileView) => void
    /** Set when the pin cannot show the tile: the row is disabled and says why. */
    reason?: string
}

function TileOption({ dashboardRef, tile, selected, onPick, reason }: TileOptionProps): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    const { scope } = useViewsContext()
    const target = tileTarget(dashboardRef, tile, null)
    const snapshot = useSnapshot<InsightSnapshot>(target ? insightQueryKey(scope, target) : null)
    const eligible = reason === undefined
    const value = snapshot && snapshot.value !== null ? snapshotFormatter(snapshot)(snapshot.value) : null
    const meta = eligible
        ? [tile.kindLabel, value].filter(Boolean).join(' · ')
        : [tile.kind === 'text' ? null : tile.kindLabel, reason].filter(Boolean).join(' · ')
    const title = tile.name || tile.text?.split('\n')[0]?.trim() || tile.kindLabel
    return (
        <Pressable44
            onPress={() => onPick(tile)}
            disabled={!eligible}
            accessibilityRole="radio"
            accessibilityLabel={`${title}, ${meta}`}
            accessibilityState={{ checked: selected, disabled: !eligible }}
            pressedBackground={colors.background}
            style={[styles.option, !eligible && styles.optionDisabled, selected && styles.optionSelected]}
            testID={`choose-tile-${tile.tileId}`}
        >
            <View style={[styles.thumb, !eligible && styles.faded]}>
                <TileThumb kindLabel={tile.kindLabel} />
            </View>
            <View style={styles.optionText}>
                <Text style={[styles.optionTitle, !eligible && styles.faded]} numberOfLines={1}>
                    {title}
                </Text>
                <Text style={styles.optionMeta} numberOfLines={1}>
                    {meta}
                </Text>
            </View>
            {selected ? <CheckIcon size={18} color={colors.ink} /> : null}
        </Pressable44>
    )
}

/** A small glyph of the tile's kind, so a list of tiles scans by shape. */
function TileThumb({ kindLabel }: { kindLabel: string }): ReactElement {
    const colors = useColors()
    const gray = colors.tertiary
    let body: ReactElement
    switch (kindLabel) {
        case 'Line':
            body = (
                <Path
                    d="M3 20 L11 14 L18 16 L26 8 L37 5"
                    fill="none"
                    stroke={colors.blue}
                    strokeWidth={2}
                    strokeLinecap="round"
                    strokeLinejoin="round"
                />
            )
            break
        case 'Bar':
            body = (
                <>
                    <Rect x={5} y={12} width={6} height={10} rx={1} fill={colors.blue} />
                    <Rect x={14} y={6} width={6} height={16} rx={1} fill={colors.blue} />
                    <Rect x={23} y={9} width={6} height={13} rx={1} fill={colors.blue} />
                    <Rect x={32} y={14} width={4} height={8} rx={1} fill={colors.blue} />
                </>
            )
            break
        case 'Big number':
            body = (
                <SvgText x={20} y={18} textAnchor="middle" fontSize={13} fontWeight="700" fill={colors.ink}>
                    123
                </SvgText>
            )
            break
        case 'Funnel':
            body = (
                <>
                    <Rect x={5} y={4} width={6} height={18} fill={gray} />
                    <Rect x={14} y={10} width={6} height={12} fill={gray} />
                    <Rect x={23} y={14} width={6} height={8} fill={gray} />
                    <Rect x={32} y={17} width={4} height={5} fill={gray} />
                </>
            )
            break
        case 'Paths':
            body = <Path d="M4 6 C16 6 20 20 36 20 M4 20 C16 20 20 6 36 6" fill="none" stroke={gray} strokeWidth={2} />
            break
        case 'SQL':
        case 'Table':
            body = <Path d="M4 6h32M4 13h32M4 20h32M18 3v20" stroke={gray} strokeWidth={1.5} />
            break
        default:
            body = <Path d="M5 7h30M5 13h30M5 19h18" stroke={gray} strokeWidth={2} strokeLinecap="round" />
    }
    return (
        <Svg width={40} height={26} viewBox="0 0 40 26">
            {body}
        </Svg>
    )
}

const useStyles = createStyles(({ colors }) => ({
    head: {
        flexDirection: 'row',
        alignItems: 'center',
        justifyContent: 'space-between',
        gap: 12,
        paddingTop: 12,
        paddingBottom: 12,
        paddingHorizontal: 4,
    },
    headText: {
        flex: 1,
        minWidth: 0,
    },
    sub: {
        ...type.meta,
        color: colors.secondary,
    },
    title: {
        ...type.sheetTitleLarge,
        color: colors.ink,
    },
    done: {
        height: 38,
        paddingHorizontal: 16,
        borderRadius: radii.pill,
        borderWidth: 1,
        borderColor: colors.border,
        alignItems: 'center',
        justifyContent: 'center',
    },
    doneText: {
        ...type.buttonSmall,
        color: colors.ink,
    },
    list: {
        gap: 8,
        paddingBottom: 8,
    },
    option: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: 12,
        paddingVertical: 10,
        paddingHorizontal: 12,
        borderRadius: radii.option,
        borderWidth: 1,
        borderColor: colors.hairline,
        backgroundColor: colors.surface,
    },
    optionSelected: {
        borderWidth: 2,
        borderColor: colors.ink,
        paddingVertical: 9,
        paddingHorizontal: 11,
    },
    optionDisabled: {
        backgroundColor: colors.background,
    },
    thumb: {
        width: 52,
        height: 38,
        borderRadius: 8,
        borderWidth: 1,
        borderColor: colors.hairline,
        backgroundColor: colors.background,
        alignItems: 'center',
        justifyContent: 'center',
    },
    faded: {
        opacity: 0.5,
    },
    optionText: {
        flex: 1,
        minWidth: 0,
    },
    optionTitle: {
        ...type.bodySmallStrong,
        color: colors.ink,
    },
    optionMeta: {
        ...type.meta,
        color: colors.tertiary,
    },
    sectionHead: {
        gap: 2,
        marginTop: 8,
        marginBottom: 2,
        marginHorizontal: 4,
    },
    sectionTitle: {
        ...type.bodySmallStrong,
        color: colors.secondary,
    },
    note: {
        ...type.meta,
        color: colors.tertiary,
    },
    state: {
        alignItems: 'center',
        gap: 12,
        paddingVertical: 32,
    },
    stateText: {
        ...type.bodySmall,
        color: colors.muted,
        textAlign: 'center',
    },
    retry: {
        height: 40,
        paddingHorizontal: 18,
        borderRadius: radii.pill,
        backgroundColor: colors.ink,
        alignItems: 'center',
        justifyContent: 'center',
    },
    retryText: {
        ...type.buttonSmall,
        color: colors.onInk,
    },
}))
