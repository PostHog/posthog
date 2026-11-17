import type { ReactElement, ReactNode } from 'react'
import { Text, View } from 'react-native'

import type { AuthProject, StoredAccount } from '@/auth/authStore'
import { AccountActionButton } from '@/features/accounts/AccountActionButton'
import { AccountIdentity } from '@/features/accounts/AccountIdentity'
import type { AccountSwitch } from '@/features/accounts/useAccountSwitch'
import { createStyles } from '@/ui/theme'
import { type } from '@/ui/tokens'
import { ProjectGroups } from './ProjectGroups'
import { ProjectRow } from './ProjectRow'
import type { AccountSection as Section } from './projectList'

interface AccountSectionProps {
    section: Section
    /** How copy names this account, from `accountLabel`. */
    label: string
    compact: boolean
    selectedProjectId: number | null
    accountSwitch: AccountSwitch
    onPickActive: (project: AuthProject) => void
    onSignInAgain: (account: StoredAccount) => void
    /** Shown instead of rows when the account lists no project, such as the active account's loading state. */
    empty: ReactNode
}

/** One account in the Project card: its header, then its projects, or what it needs before it can list them. */
export function AccountSection({
    section,
    label,
    compact,
    selectedProjectId,
    accountSwitch,
    onPickActive,
    onSignInAgain,
    empty,
}: AccountSectionProps): ReactElement {
    const styles = useStyles()
    const { account, active, state } = section
    const { pending, failed, run } = accountSwitch
    const busy = pending !== null
    const testKey = active ? 'active' : account.key
    const failedHere = failed?.key === account.key ? failed : null

    let body: ReactNode = null
    if (state === 'not_loaded') {
        body = (
            <ProjectRow
                label="Switch to this account"
                compact={compact}
                selected={false}
                pending={pending?.key === account.key}
                disabled={busy}
                onPress={() => void run({ key: account.key })}
                testID={`project-sheet-account-${testKey}-switch`}
            />
        )
    } else if (state === 'projects') {
        body =
            section.groups.length === 0 ? (
                empty
            ) : (
                <ProjectGroups groups={section.groups} showOrganizations={section.showOrganizations}>
                    {(project) => (
                        <ProjectRow
                            key={project.id}
                            label={project.name}
                            compact={compact}
                            selected={active && project.id === selectedProjectId}
                            pending={pending?.key === account.key && pending.projectId === project.id}
                            disabled={busy}
                            onPress={() =>
                                active ? onPickActive(project) : void run({ key: account.key, projectId: project.id })
                            }
                            testID={active ? `project-sheet-${project.id}` : `project-sheet-${testKey}-${project.id}`}
                        />
                    )}
                </ProjectGroups>
            )
    }

    return (
        <View testID={`project-sheet-account-${testKey}`}>
            <View style={styles.header}>
                <AccountIdentity
                    account={account}
                    size="compact"
                    status={state === 'needs_sign_in' ? <Text style={styles.ended}>Session ended</Text> : null}
                />
                {state === 'needs_sign_in' ? (
                    <AccountActionButton
                        label="Sign in again"
                        onPress={() => onSignInAgain(account)}
                        disabled={busy}
                        accessibilityLabel={`Sign in again to ${label}`}
                        testID={`project-sheet-account-${testKey}-sign-in`}
                    />
                ) : null}
            </View>
            {body}
            {failedHere ? (
                <View
                    style={styles.failure}
                    accessibilityRole="alert"
                    testID={`project-sheet-account-${testKey}-error`}
                >
                    <Text style={styles.failureText}>Couldn't switch to {label}.</Text>
                    <AccountActionButton
                        label="Try again"
                        onPress={() => void run(failedHere)}
                        disabled={busy}
                        testID={`project-sheet-account-${testKey}-retry`}
                    />
                </View>
            ) : null}
        </View>
    )
}

const useStyles = createStyles(({ colors }) => ({
    header: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: 12,
        paddingTop: 12,
        paddingBottom: 6,
        paddingHorizontal: 4,
    },
    ended: {
        ...type.meta,
        color: colors.orange,
        flexShrink: 0,
    },
    failure: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: 12,
        paddingHorizontal: 4,
        paddingVertical: 8,
    },
    failureText: {
        ...type.metaSmall,
        color: colors.muted,
        flex: 1,
    },
}))
