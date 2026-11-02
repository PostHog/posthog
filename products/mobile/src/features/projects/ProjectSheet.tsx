import { type ReactElement, type ReactNode, useEffect, useMemo, useState } from 'react'
import { ActivityIndicator, ScrollView, Text, TextInput, useWindowDimensions, View } from 'react-native'

import { type AuthProject, useAuthStore } from '@/auth/authStore'
import { DEMO_PROJECT_NAME } from '@/demo/briefings'
import { useDemoMode } from '@/demo/demoMode'
import { FloatingCard } from '@/ui/FloatingCard'
import { CheckIcon } from '@/ui/icons/CheckIcon'
import { CloseIcon } from '@/ui/icons/CloseIcon'
import { SearchIcon } from '@/ui/icons/SearchIcon'
import { Pressable44 } from '@/ui/Pressable44'
import { createStyles, useColors, useTheme } from '@/ui/theme'
import { iconSizes, inputReset, radii, type } from '@/ui/tokens'
import { topOffset, useScreenInsets } from '@/ui/useScreenInsets'

import { filterProjects, groupByOrganization } from './projectList'

interface ProjectSheetProps {
    visible: boolean
    onClose: () => void
    onSelect: (projectId: number) => void
}

// Demo mode has no account, so the sheet lists the one sample project and keeps it selected.
const DEMO_PROJECT: AuthProject = { id: 0, name: DEMO_PROJECT_NAME, organizationId: 'demo', organizationName: '' }
const DEMO_PROJECTS = [DEMO_PROJECT]

interface ProjectRowProps {
    project: AuthProject
    selected: boolean
    onPress: () => void
}

function ProjectRow({ project, selected, onPress }: ProjectRowProps): ReactElement {
    const styles = useStyles()
    const colors = useColors()
    return (
        <Pressable44
            onPress={onPress}
            accessibilityRole="radio"
            accessibilityState={{ checked: selected }}
            accessibilityLabel={project.name}
            pressedBackground={colors.background}
            style={styles.row}
            testID={`project-sheet-${project.id}`}
        >
            <Text style={styles.rowLabel} numberOfLines={1}>
                {project.name}
            </Text>
            {selected ? <CheckIcon size={iconSizes.control} /> : null}
        </Pressable44>
    )
}

export function ProjectSheet({ visible, onClose, onSelect }: ProjectSheetProps): ReactElement {
    const styles = useStyles()
    const { colors, scheme } = useTheme()
    const insets = useScreenInsets()
    const { height: windowHeight } = useWindowDimensions()
    const top = topOffset(insets, 120)
    const cardHeight = Math.max(320, Math.round((windowHeight - top) * 0.52))
    const demo = useDemoMode((state) => state.enabled)
    const storeProjects = useAuthStore((state) => state.projects)
    const storeProjectId = useAuthStore((state) => state.projectId)
    const accountLoading = useAuthStore((state) => state.accountLoading)
    const accountError = useAuthStore((state) => state.accountError)
    const reloadAccount = useAuthStore((state) => state.reloadAccount)
    const [query, setQuery] = useState('')

    useEffect(() => {
        if (!visible) {
            return
        }
        setQuery('')
        // Picks up a project created on the web since launch.
        if (!demo && !useAuthStore.getState().accountLoading) {
            void reloadAccount()
        }
    }, [visible, demo, reloadAccount])

    const projects = demo ? DEMO_PROJECTS : storeProjects
    const projectId = demo ? DEMO_PROJECT.id : storeProjectId
    const showOrganizations = useMemo(() => groupByOrganization(projects).length > 1, [projects])
    const trimmed = query.trim()
    const groups = useMemo(() => groupByOrganization(filterProjects(projects, query)), [projects, query])

    const pick = (project: AuthProject): void => {
        if (project.id === projectId) {
            onClose()
            return
        }
        onSelect(project.id)
    }

    const retry = (
        <Pressable44
            onPress={() => void reloadAccount()}
            disabled={accountLoading}
            accessibilityState={{ busy: accountLoading, disabled: accountLoading }}
            pressedBackground={colors.sunken}
            style={styles.retry}
            testID="project-retry"
        >
            {accountLoading ? (
                <ActivityIndicator color={colors.ink} />
            ) : (
                <Text style={styles.retryText}>Try again</Text>
            )}
        </Pressable44>
    )

    let content: ReactNode
    if (!demo && projects.length === 0 && accountLoading) {
        content = <ActivityIndicator color={colors.ink} style={styles.loading} accessibilityLabel="Loading projects" />
    } else if (!demo && projects.length === 0 && accountError) {
        content = (
            <View style={styles.loadError} testID="project-load-error">
                <Text style={styles.empty}>Couldn't load your projects. {accountError}</Text>
                {retry}
            </View>
        )
    } else if (projects.length === 0) {
        content = (
            <Text style={styles.empty}>
                Your account has no projects you can open. Create one in PostHog on the web.
            </Text>
        )
    } else {
        content = (
            <>
                {groups.flatMap((group) => [
                    ...(showOrganizations
                        ? [
                              <Text
                                  key={`org-${group.id}`}
                                  style={[type.eyebrow, styles.organization]}
                                  numberOfLines={1}
                              >
                                  {group.name.toUpperCase()}
                              </Text>,
                          ]
                        : []),
                    ...group.projects.map((project) => (
                        <ProjectRow
                            key={project.id}
                            project={project}
                            selected={project.id === projectId}
                            onPress={() => pick(project)}
                        />
                    )),
                ])}
                {groups.length === 0 && trimmed ? (
                    <Text style={styles.empty}>No projects match "{trimmed}"</Text>
                ) : null}
                {demo ? (
                    <Text style={styles.note}>
                        Demo mode shows sample reports. Turn it off in Settings to switch projects.
                    </Text>
                ) : accountError ? (
                    <View style={styles.footer} testID="project-refresh-error">
                        <Text style={styles.note}>Couldn't refresh the project list. {accountError}</Text>
                        {retry}
                    </View>
                ) : null}
            </>
        )
    }

    return (
        <FloatingCard
            visible={visible}
            onClose={onClose}
            accessibilityLabel="Project"
            testID="project-sheet"
            style={[styles.card, { top, height: cardHeight }]}
        >
            <View style={styles.header}>
                <Text style={styles.title}>Project</Text>
                <Pressable44
                    onPress={onClose}
                    accessibilityLabel="Close"
                    pressedBackground={colors.hairline}
                    style={styles.close}
                >
                    <CloseIcon size={iconSizes.control} />
                </Pressable44>
            </View>
            <View style={styles.search}>
                <SearchIcon size={iconSizes.control} />
                <TextInput
                    value={query}
                    onChangeText={setQuery}
                    placeholder="Find a project…"
                    placeholderTextColor={colors.tertiary}
                    keyboardAppearance={scheme}
                    autoFocus
                    autoCorrect={false}
                    autoCapitalize="none"
                    style={styles.input}
                    accessibilityLabel="Search projects"
                    testID="project-search"
                />
            </View>
            <ScrollView style={styles.list} keyboardShouldPersistTaps="handled">
                {content}
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
    close: {
        width: 44,
        height: 44,
        borderRadius: 22,
        backgroundColor: colors.sunken,
        alignItems: 'center',
        justifyContent: 'center',
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
    organization: {
        color: colors.tertiary,
        paddingHorizontal: 4,
        paddingTop: 14,
        paddingBottom: 4,
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
    footer: {
        alignItems: 'center',
        gap: 12,
        paddingBottom: 12,
    },
    note: {
        ...type.metaSmall,
        color: colors.muted,
        textAlign: 'center',
        paddingTop: 12,
        paddingHorizontal: 4,
    },
    // The minimum width keeps the pill the same size when the spinner replaces the label.
    retry: {
        height: 44,
        minWidth: 112,
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
