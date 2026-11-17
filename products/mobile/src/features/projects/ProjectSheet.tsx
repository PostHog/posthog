import { type ReactElement, type ReactNode, useEffect, useMemo, useState } from 'react'
import { ActivityIndicator, ScrollView, Text, TextInput, View } from 'react-native'
import { type AuthProject, type StoredAccount, useAuthStore } from '@/auth/authStore'
import { DEMO_PROJECT_NAME } from '@/demo/briefings'
import { useDemoMode } from '@/demo/demoMode'
import { AddAccountRow } from '@/features/accounts/AddAccountRow'
import { accountLabel } from '@/features/accounts/accountLabel'
import { useAccountSwitch } from '@/features/accounts/useAccountSwitch'
import { useOpenAddAccount } from '@/features/accounts/useOpenAddAccount'
import { FloatingCard } from '@/ui/FloatingCard'
import { CloseIcon } from '@/ui/icons/CloseIcon'
import { SearchIcon } from '@/ui/icons/SearchIcon'
import { Pressable44 } from '@/ui/Pressable44'
import { createStyles, useTheme } from '@/ui/theme'
import { iconSizes, inputReset, radii, type } from '@/ui/tokens'
import { usePickerCardStyle } from '@/ui/usePickerCardStyle'
import { useSceneDimensions } from '@/ui/useSceneDimensions'
import { bottomOffset, topOffset, useScreenInsets } from '@/ui/useScreenInsets'

import { AccountSection } from './AccountSection'
import { ProjectGroups } from './ProjectGroups'
import { ProjectRow } from './ProjectRow'
import { accountSections, filterProjects, groupByOrganization } from './projectList'

interface ProjectSheetProps {
    visible: boolean
    onClose: () => void
    onSelect: (projectId: number) => void
}

// Demo mode has no account, so the sheet lists the one sample project and keeps it selected.
const DEMO_PROJECT: AuthProject = { id: 0, name: DEMO_PROJECT_NAME, organizationId: 'demo', organizationName: '' }
const DEMO_PROJECTS = [DEMO_PROJECT]

/**
 * The project switcher. With two or more accounts on the phone it lists every account's projects under the account,
 * and a project of another account switches to that account.
 */
export function ProjectSheet({ visible, onClose, onSelect }: ProjectSheetProps): ReactElement {
    const styles = useStyles()
    const { colors, scheme } = useTheme()
    const insets = useScreenInsets()
    const { height: windowHeight } = useSceneDimensions()
    const compact = windowHeight < 480
    const top = topOffset(insets, 120)
    const demo = useDemoMode((state) => state.enabled)
    const accounts = useAuthStore((state) => state.accounts)
    const activeKey = useAuthStore((state) => state.activeAccountKey)
    const storeProjects = useAuthStore((state) => state.projects)
    const storeProjectId = useAuthStore((state) => state.projectId)
    const accountLoading = useAuthStore((state) => state.accountLoading)
    const accountError = useAuthStore((state) => state.accountError)
    const reloadAccount = useAuthStore((state) => state.reloadAccount)
    const [query, setQuery] = useState('')
    const accountSwitch = useAccountSwitch('nav_menu')
    const openAddAccount = useOpenAddAccount()
    const multi = !demo && accounts.length >= 2
    // With several accounts the card reaches down to the bottom edge, so more than one account header stays in view.
    const cardHeight = multi
        ? Math.max(320, windowHeight - top - bottomOffset(insets, 40))
        : Math.max(320, Math.round((windowHeight - top) * 0.52))
    const cardStyle = usePickerCardStyle(top, cardHeight)

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
    const list = useMemo(() => accountSections(accounts, activeKey, query), [accounts, activeKey, query])
    const switching = accountSwitch.pending !== null

    const pick = (project: AuthProject): void => {
        if (project.id === projectId) {
            onClose()
            return
        }
        onSelect(project.id)
    }
    const addAccount = (reauth?: StoredAccount): void => {
        onClose()
        openAddAccount('project_card', reauth)
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
    // The active account's state before it lists a project: loading, a load error, or no project to open.
    const activeEmpty = accountLoading ? (
        <ActivityIndicator color={colors.ink} style={styles.loading} accessibilityLabel="Loading projects" />
    ) : accountError ? (
        <View style={styles.loadError} testID="project-load-error">
            <Text style={styles.empty}>Couldn't load your projects. {accountError}</Text>
            {retry}
        </View>
    ) : (
        <Text style={styles.empty}>Your account has no projects you can open. Create one in PostHog on the web.</Text>
    )
    const refreshError =
        !demo && accountError && projects.length > 0 ? (
            <View style={styles.footer} testID="project-refresh-error">
                <Text style={styles.note}>Couldn't refresh the project list. {accountError}</Text>
                {retry}
            </View>
        ) : null
    const addRow =
        !demo && !trimmed ? (
            <>
                <View style={styles.addDivider} />
                <AddAccountRow
                    onPress={() => addAccount()}
                    disabled={switching}
                    quiet={!multi}
                    style={[styles.addRow, compact && styles.addRowCompact]}
                    testID="project-sheet-add-account"
                />
            </>
        ) : null

    let content: ReactNode
    if (multi) {
        content = (
            <>
                {list.sections.map((section, index) => (
                    <View key={section.account.key} style={index > 0 ? styles.sectionDivider : undefined}>
                        <AccountSection
                            section={section}
                            label={accountLabel(section.account, accounts)}
                            compact={compact}
                            selectedProjectId={storeProjectId}
                            accountSwitch={accountSwitch}
                            onPickActive={pick}
                            onSignInAgain={addAccount}
                            empty={
                                section.active ? (
                                    activeEmpty
                                ) : (
                                    <Text style={styles.note}>This account has no projects you can open.</Text>
                                )
                            }
                        />
                    </View>
                ))}
                {trimmed && list.matches === 0 ? <Text style={styles.empty}>No projects match "{trimmed}"</Text> : null}
                {list.skipped.map(({ account, state }) => (
                    <Text key={account.key} style={styles.note} testID="project-sheet-skipped">
                        {state === 'needs_sign_in'
                            ? `Projects in ${accountLabel(account, accounts)} show after you sign in again.`
                            : `Projects in ${accountLabel(account, accounts)} show after you switch to it.`}
                    </Text>
                ))}
                {refreshError}
                {addRow}
            </>
        )
    } else if (!demo && projects.length === 0 && (accountLoading || accountError)) {
        content = (
            <>
                {activeEmpty}
                {accountLoading ? null : addRow}
            </>
        )
    } else if (projects.length === 0) {
        content = (
            <>
                {activeEmpty}
                {addRow}
            </>
        )
    } else {
        content = (
            <>
                <ProjectGroups groups={groups} showOrganizations={showOrganizations}>
                    {(project) => (
                        <ProjectRow
                            key={project.id}
                            label={project.name}
                            compact={compact}
                            selected={project.id === projectId}
                            onPress={() => pick(project)}
                            testID={`project-sheet-${project.id}`}
                        />
                    )}
                </ProjectGroups>
                {groups.length === 0 && trimmed ? (
                    <Text style={styles.empty}>No projects match "{trimmed}"</Text>
                ) : null}
                {demo ? (
                    <Text style={styles.note}>
                        Demo mode shows sample reports. Turn it off in Settings to switch projects.
                    </Text>
                ) : (
                    refreshError
                )}
                {addRow}
            </>
        )
    }

    return (
        <FloatingCard
            visible={visible}
            onClose={onClose}
            accessibilityLabel="Project"
            testID="project-sheet"
            style={[styles.card, compact && styles.cardCompact, cardStyle]}
        >
            <View style={compact ? styles.controlsCompact : undefined}>
                <View style={[styles.header, compact && styles.headerCompact]}>
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
                <View style={[styles.search, compact && styles.searchCompact]}>
                    <SearchIcon size={iconSizes.control} />
                    <TextInput
                        value={query}
                        onChangeText={setQuery}
                        placeholder="Find a project…"
                        placeholderTextColor={colors.tertiary}
                        keyboardAppearance={scheme}
                        // The keyboard would cover the account headers that tell the lists apart.
                        autoFocus={!multi}
                        autoCorrect={false}
                        disableFullscreenUI
                        autoCapitalize="none"
                        style={styles.input}
                        accessibilityLabel="Search projects"
                        testID="project-search"
                    />
                </View>
            </View>
            <ScrollView style={[styles.list, compact && { marginTop: 2 }]} keyboardShouldPersistTaps="handled">
                {content}
            </ScrollView>
        </FloatingCard>
    )
}

const useStyles = createStyles(({ colors }) => ({
    cardCompact: {
        paddingTop: 4,
        paddingBottom: 4,
    },
    controlsCompact: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: 12,
    },
    headerCompact: {
        gap: 12,
    },
    searchCompact: {
        flex: 1,
        height: 44,
        marginTop: 0,
    },
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
        flexShrink: 1,
    },
    sectionDivider: {
        marginTop: 10,
        paddingTop: 4,
        borderTopWidth: 1,
        borderTopColor: colors.hairline,
    },
    addDivider: {
        height: 1,
        backgroundColor: colors.hairline,
        marginTop: 10,
        marginBottom: 2,
        marginHorizontal: 4,
    },
    addRow: {
        minHeight: 56,
        paddingHorizontal: 4,
        borderRadius: radii.card,
    },
    addRowCompact: {
        minHeight: 44,
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
