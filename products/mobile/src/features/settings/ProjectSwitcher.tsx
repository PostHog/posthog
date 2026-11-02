import { type ReactElement, useMemo, useState } from 'react'
import { ActivityIndicator, Text, View } from 'react-native'

import { useAuthStore } from '@/auth/authStore'
import { groupByOrganization, orderSettingsProjects } from '@/features/projects/projectList'
import { useAsyncAction } from '@/lib/useAsyncAction'
import { ChevronDownIcon } from '@/ui/icons/ChevronDownIcon'
import { ChevronUpIcon } from '@/ui/icons/ChevronUpIcon'
import { Pressable44 } from '@/ui/Pressable44'
import { createStyles, useColors } from '@/ui/theme'
import { iconSizes, radii, type } from '@/ui/tokens'

import { SettingsGroup } from './SettingsGroup'
import { SettingsRadioRow } from './SettingsRadioRow'

const COLLAPSED_PROJECT_COUNT = 5

export function ProjectSwitcher(): ReactElement {
    const styles = useStyles()
    const colors = useColors()
    const projects = useAuthStore((state) => state.projects)
    const projectId = useAuthStore((state) => state.projectId)
    const accountLoading = useAuthStore((state) => state.accountLoading)
    const accountError = useAuthStore((state) => state.accountError)
    const selectProject = useAuthStore((state) => state.selectProject)
    const reload = useAsyncAction(() => useAuthStore.getState().reloadAccount())
    const [expanded, setExpanded] = useState(false)
    const orderedProjects = useMemo(() => orderSettingsProjects(projects, projectId), [projects, projectId])
    const visibleProjects = expanded ? orderedProjects : orderedProjects.slice(0, COLLAPSED_PROJECT_COUNT)
    const groups = groupByOrganization(visibleProjects)
    const showOrganizations = projects.some((project) => project.organizationId !== projects[0]?.organizationId)
    const canExpand = projects.length > COLLAPSED_PROJECT_COUNT

    const retry = (
        <Pressable44
            onPress={() => void reload.run()}
            disabled={reload.pending}
            accessibilityState={{ busy: reload.pending, disabled: reload.pending }}
            pressedBackground={colors.sunken}
            style={styles.retry}
            testID="projects-retry"
        >
            {reload.pending ? (
                <ActivityIndicator color={colors.ink} />
            ) : (
                <Text style={styles.retryText}>Try again</Text>
            )}
        </Pressable44>
    )

    if (projects.length === 0) {
        return (
            <SettingsGroup title="Project" testID="settings-projects">
                {accountLoading ? (
                    <View style={styles.stateRow} accessibilityLabel="Loading projects">
                        <ActivityIndicator color={colors.ink} />
                    </View>
                ) : accountError ? (
                    <View style={styles.stateRow}>
                        <Text style={styles.stateText}>Couldn't load your projects. {accountError}</Text>
                        {retry}
                    </View>
                ) : (
                    <View style={styles.stateRow}>
                        <Text style={styles.stateText}>
                            Your account has no projects you can open. Create one in PostHog on the web.
                        </Text>
                    </View>
                )}
            </SettingsGroup>
        )
    }

    return (
        <SettingsGroup
            title="Project"
            footer={accountError ? `Couldn't refresh the project list. ${accountError}` : undefined}
            testID="settings-projects"
        >
            {groups.flatMap((group) => [
                ...(showOrganizations
                    ? [
                          <Text key={`org-${group.id}`} style={[type.eyebrow, styles.organization]} numberOfLines={1}>
                              {group.name.toUpperCase()}
                          </Text>,
                      ]
                    : []),
                ...group.projects.map((project) => (
                    <SettingsRadioRow
                        key={project.id}
                        label={project.name}
                        selected={project.id === projectId}
                        onPress={() => selectProject(project.id, 'settings')}
                        testID={`project-${project.id}`}
                    />
                )),
            ])}
            {canExpand ? (
                <Pressable44
                    onPress={() => setExpanded((value) => !value)}
                    aria-expanded={expanded}
                    pressedBackground={colors.background}
                    style={styles.expandRow}
                    testID="projects-see-more"
                >
                    <Text style={styles.expandLabel}>{expanded ? 'See less' : 'See more'}</Text>
                    {expanded ? (
                        <ChevronUpIcon size={iconSizes.inline} color={colors.secondary} />
                    ) : (
                        <ChevronDownIcon size={iconSizes.inline} color={colors.secondary} />
                    )}
                </Pressable44>
            ) : null}
            {accountError ? <View style={styles.retryRow}>{retry}</View> : null}
        </SettingsGroup>
    )
}

const useStyles = createStyles(({ colors }) => ({
    expandRow: {
        minHeight: 52,
        flexDirection: 'row',
        alignItems: 'center',
        gap: 12,
        paddingHorizontal: 16,
    },
    expandLabel: {
        ...type.body,
        color: colors.secondary,
        flex: 1,
    },
    organization: {
        color: colors.tertiary,
        paddingHorizontal: 16,
        paddingTop: 16,
        paddingBottom: 10,
    },
    stateRow: {
        minHeight: 52,
        paddingHorizontal: 16,
        paddingVertical: 14,
        gap: 12,
        alignItems: 'flex-start',
        justifyContent: 'center',
    },
    stateText: {
        ...type.bodySmall,
        color: colors.muted,
    },
    retryRow: {
        paddingHorizontal: 16,
        paddingVertical: 10,
        alignItems: 'flex-start',
    },
    retry: {
        height: 36,
        minWidth: 96,
        paddingHorizontal: 14,
        borderRadius: radii.pill,
        borderWidth: 1,
        borderColor: colors.border,
        backgroundColor: colors.surface,
        alignItems: 'center',
        justifyContent: 'center',
    },
    retryText: {
        ...type.buttonSmall,
        color: colors.ink,
    },
}))
