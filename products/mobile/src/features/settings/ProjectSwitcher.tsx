import { type ReactElement, useMemo } from 'react'
import { ActivityIndicator, StyleSheet, Text, View } from 'react-native'

import { useAuthStore } from '@/auth/authStore'
import { groupByOrganization } from '@/features/projects/projectList'
import { useAsyncAction } from '@/lib/useAsyncAction'
import { Pressable44 } from '@/ui/Pressable44'
import { colors, radii, type } from '@/ui/tokens'

import { SettingsGroup } from './SettingsGroup'
import { SettingsRadioRow } from './SettingsRadioRow'

export function ProjectSwitcher(): ReactElement {
    const projects = useAuthStore((state) => state.projects)
    const projectId = useAuthStore((state) => state.projectId)
    const accountLoading = useAuthStore((state) => state.accountLoading)
    const accountError = useAuthStore((state) => state.accountError)
    const selectProject = useAuthStore((state) => state.selectProject)
    const reload = useAsyncAction(() => useAuthStore.getState().reloadAccount())
    const groups = useMemo(() => groupByOrganization(projects), [projects])
    const showOrganizations = groups.length > 1

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
            {accountError ? <View style={styles.retryRow}>{retry}</View> : null}
        </SettingsGroup>
    )
}

const styles = StyleSheet.create({
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
        backgroundColor: colors.white,
        alignItems: 'center',
        justifyContent: 'center',
    },
    retryText: {
        ...type.buttonSmall,
        color: colors.ink,
    },
})
