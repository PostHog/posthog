import { type ReactElement, useEffect, useMemo, useRef, useState } from 'react'
import { ActivityIndicator, ScrollView, Text, TextInput, useWindowDimensions, View } from 'react-native'

import { actionErrorMessage } from '@/lib/errors'
import type { Person, Reviewer } from '@/model/types'
import { Avatar } from '@/ui/Avatar'
import { FloatingCard } from '@/ui/FloatingCard'
import { CheckIcon } from '@/ui/icons/CheckIcon'
import { CloseIcon } from '@/ui/icons/CloseIcon'
import { PersonIcon } from '@/ui/icons/PersonIcon'
import { SearchIcon } from '@/ui/icons/SearchIcon'
import { Pressable44 } from '@/ui/Pressable44'
import { createStyles, useColors, useTheme } from '@/ui/theme'
import { iconSizes, inputReset, radii, type } from '@/ui/tokens'
import { topOffset, useScreenInsets } from '@/ui/useScreenInsets'

import { MAX_REVIEWERS, useAvailableReviewers } from './hooks'

interface AssigneeSheetProps {
    visible: boolean
    current: Reviewer[]
    /** Reviewers the sheet cannot list. They stay on the report and count toward `MAX_REVIEWERS`. */
    githubOnlyCount: number
    onClose: () => void
    onSave: (uuids: string[]) => Promise<void>
    pending: boolean
}

function sameSelection(a: ReadonlySet<string>, b: readonly string[]): boolean {
    return a.size === b.length && b.every((uuid) => a.has(uuid))
}

function limitMessage(githubOnlyCount: number): string {
    const limit = `A report can have up to ${MAX_REVIEWERS} reviewers`
    if (githubOnlyCount === 0) {
        return `${limit}.`
    }
    return githubOnlyCount === 1
        ? `${limit}, including 1 GitHub reviewer who isn't listed here.`
        : `${limit}, including ${githubOnlyCount} GitHub reviewers who aren't listed here.`
}

interface PersonRowProps {
    person: Person
    selected: boolean
    onPress: () => void
}

function PersonRow({ person, selected, onPress }: PersonRowProps): ReactElement {
    const styles = useStyles()
    const colors = useColors()
    return (
        <Pressable44
            onPress={onPress}
            accessibilityRole="checkbox"
            accessibilityState={{ checked: selected }}
            pressedBackground={colors.background}
            style={styles.row}
            testID={`assignee-${person.uuid}`}
        >
            <Avatar name={person.name} color={person.color} seed={person.uuid} size={32} fontSize={12} />
            <Text style={styles.rowLabel} numberOfLines={1}>
                {person.name}
            </Text>
            {selected ? <CheckIcon size={iconSizes.control} /> : null}
        </Pressable44>
    )
}

export function AssigneeSheet({
    visible,
    current,
    githubOnlyCount,
    onClose,
    onSave,
    pending,
}: AssigneeSheetProps): ReactElement {
    const styles = useStyles()
    const { colors, scheme } = useTheme()
    const insets = useScreenInsets()
    const { height: windowHeight } = useWindowDimensions()
    const top = topOffset(insets, 120)
    const cardHeight = Math.max(320, Math.round((windowHeight - top) * 0.52))
    const [query, setQuery] = useState('')
    const [selected, setSelected] = useState<Set<string>>(() => new Set())
    const [limitHit, setLimitHit] = useState(false)
    const [error, setError] = useState<string | undefined>(undefined)
    const people = useAvailableReviewers(query)
    const currentIds = useMemo(() => current.map((reviewer) => reviewer.uuid), [current])
    const wasVisible = useRef(false)

    useEffect(() => {
        if (visible && !wasVisible.current) {
            setQuery('')
            setSelected(new Set(currentIds))
            setLimitHit(false)
            setError(undefined)
        }
        wasVisible.current = visible
    }, [visible, currentIds])

    const overLimit = selected.size + githubOnlyCount > MAX_REVIEWERS
    const toggle = (uuid: string): void => {
        const adding = !selected.has(uuid)
        if (adding && selected.size + githubOnlyCount >= MAX_REVIEWERS) {
            setLimitHit(true)
            return
        }
        setLimitHit(false)
        setSelected((previous) => {
            const next = new Set(previous)
            if (next.has(uuid)) {
                next.delete(uuid)
            } else {
                next.add(uuid)
            }
            return next
        })
    }
    const clear = (): void => {
        setLimitHit(false)
        setSelected(new Set())
    }

    const changed = !sameSelection(selected, currentIds)
    const save = async (): Promise<void> => {
        setError(undefined)
        try {
            await onSave([...selected])
        } catch (saveError) {
            setError(actionErrorMessage(saveError))
            return
        }
        onClose()
    }
    const trimmed = query.trim()

    return (
        <FloatingCard
            visible={visible}
            onClose={onClose}
            accessibilityLabel="Assignee"
            testID="assignee-sheet"
            style={[styles.card, { top, height: cardHeight }]}
        >
            <View style={styles.header}>
                <Text style={styles.title}>Assignee</Text>
                <View style={styles.headerActions}>
                    {changed ? (
                        <Pressable44
                            onPress={() => void save()}
                            disabled={pending || overLimit}
                            accessibilityState={{ busy: pending, disabled: pending || overLimit }}
                            pressedBackground={colors.inkHover}
                            style={styles.done}
                            testID="assignee-done"
                        >
                            {pending ? (
                                <ActivityIndicator size="small" color={colors.onInk} />
                            ) : (
                                <Text style={styles.doneText}>Done</Text>
                            )}
                        </Pressable44>
                    ) : null}
                    <Pressable44
                        onPress={onClose}
                        accessibilityLabel="Close"
                        pressedBackground={colors.hairline}
                        style={styles.close}
                    >
                        <CloseIcon size={iconSizes.control} />
                    </Pressable44>
                </View>
            </View>
            {error ? (
                <Text style={styles.error} accessibilityRole="alert" testID="assignee-error">
                    {error}
                </Text>
            ) : null}
            {limitHit || overLimit ? (
                <Text style={styles.limit} testID="assignee-limit">
                    {limitMessage(githubOnlyCount)}
                </Text>
            ) : null}
            <View style={styles.search}>
                <SearchIcon size={iconSizes.control} />
                <TextInput
                    value={query}
                    onChangeText={setQuery}
                    placeholder="Assign to…"
                    placeholderTextColor={colors.tertiary}
                    keyboardAppearance={scheme}
                    autoFocus
                    autoCorrect={false}
                    style={styles.input}
                    accessibilityLabel="Search people"
                    testID="assignee-search"
                />
            </View>
            <ScrollView style={styles.list} keyboardShouldPersistTaps="handled">
                {trimmed ? null : (
                    <Pressable44
                        onPress={clear}
                        accessibilityRole="checkbox"
                        accessibilityState={{ checked: selected.size === 0 }}
                        pressedBackground={colors.background}
                        style={styles.row}
                        testID="assignee-none"
                    >
                        <View style={styles.dashed}>
                            <PersonIcon size={iconSizes.control} color={colors.muted} />
                        </View>
                        <Text style={styles.rowLabel}>No assignee</Text>
                        {selected.size === 0 ? <CheckIcon size={iconSizes.control} /> : null}
                    </Pressable44>
                )}
                {people.isLoading ? <ActivityIndicator color={colors.ink} style={styles.loading} /> : null}
                {people.isError ? (
                    <View style={styles.loadError} testID="assignee-load-error">
                        <Text style={styles.empty}>Couldn't load people. Check your connection and try again.</Text>
                        <Pressable44
                            onPress={() => void people.refetch()}
                            disabled={people.isRefetching}
                            accessibilityState={{ busy: people.isRefetching, disabled: people.isRefetching }}
                            pressedBackground={colors.sunken}
                            style={styles.retry}
                            testID="assignee-retry"
                        >
                            <Text style={styles.retryText}>Try again</Text>
                        </Pressable44>
                    </View>
                ) : null}
                {(people.data ?? []).map((person) => (
                    <PersonRow
                        key={person.uuid}
                        person={person}
                        selected={selected.has(person.uuid)}
                        onPress={() => toggle(person.uuid)}
                    />
                ))}
                {people.data && people.data.length === 0 ? (
                    <Text style={styles.empty}>No one matches "{trimmed}"</Text>
                ) : null}
            </ScrollView>
        </FloatingCard>
    )
}

const useStyles = createStyles(({ colors }) => ({
    card: {
        left: 14,
        right: 14,
        paddingTop: 20,
        paddingHorizontal: 20,
        paddingBottom: 24,
    },
    header: {
        flexDirection: 'row',
        alignItems: 'center',
        justifyContent: 'space-between',
    },
    title: {
        ...type.sheetTitle,
        color: colors.ink,
    },
    headerActions: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: 8,
    },
    done: {
        height: 44,
        minWidth: 72,
        paddingHorizontal: 16,
        borderRadius: radii.pill,
        backgroundColor: colors.ink,
        alignItems: 'center',
        justifyContent: 'center',
    },
    doneText: {
        ...type.buttonSmall,
        color: colors.onInk,
    },
    close: {
        width: 44,
        height: 44,
        borderRadius: 22,
        backgroundColor: colors.sunken,
        alignItems: 'center',
        justifyContent: 'center',
    },
    error: {
        ...type.metaSmall,
        color: colors.orange,
        marginTop: 10,
        paddingHorizontal: 4,
    },
    limit: {
        ...type.metaSmall,
        color: colors.muted,
        marginTop: 10,
        paddingHorizontal: 4,
    },
    search: {
        marginTop: 16,
        height: 48,
        flexDirection: 'row',
        alignItems: 'center',
        gap: 10,
        borderRadius: radii.pill,
        backgroundColor: colors.sunken,
        paddingHorizontal: 16,
    },
    input: {
        ...inputReset,
        flex: 1,
        minWidth: 0,
        ...type.input,
        color: colors.ink,
        paddingVertical: 0,
    },
    list: {
        marginTop: 8,
        flexGrow: 0,
    },
    row: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: 14,
        minHeight: 56,
        paddingHorizontal: 4,
        borderRadius: radii.card,
    },
    rowLabel: {
        ...type.label,
        color: colors.ink,
        flex: 1,
        minWidth: 0,
    },
    dashed: {
        width: 32,
        height: 32,
        borderRadius: 16,
        borderWidth: 2,
        borderStyle: 'dashed',
        borderColor: colors.disabled,
        alignItems: 'center',
        justifyContent: 'center',
    },
    loading: {
        paddingVertical: 20,
    },
    empty: {
        paddingVertical: 28,
        textAlign: 'center',
        fontSize: 15,
        lineHeight: 21,
        color: colors.tertiary,
    },
    loadError: {
        alignItems: 'center',
        paddingBottom: 12,
    },
    retry: {
        height: 44,
        paddingHorizontal: 20,
        borderRadius: radii.pill,
        borderWidth: 1,
        borderColor: colors.border,
        alignItems: 'center',
        justifyContent: 'center',
    },
    retryText: {
        ...type.buttonSmall,
        color: colors.ink,
    },
}))
