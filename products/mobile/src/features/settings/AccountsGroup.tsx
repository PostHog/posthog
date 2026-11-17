import { type ReactElement, useState } from 'react'

import { useAuthStore } from '@/auth/authStore'
import { AddAccountRow } from '@/features/accounts/AddAccountRow'
import { accountLabel, orderedAccounts } from '@/features/accounts/accountLabel'
import { useAccountSwitch } from '@/features/accounts/useAccountSwitch'
import { useOpenAddAccount } from '@/features/accounts/useOpenAddAccount'
import { createStyles } from '@/ui/theme'

import { AccountSettingsRow } from './AccountSettingsRow'
import { SettingsGroup } from './SettingsGroup'
import { useSignOutAction } from './useSignOut'

/** Settings with two or more accounts: every account, switching, per-account sign out and Add account. */
export function AccountsGroup(): ReactElement {
    const styles = useStyles()
    const accounts = useAuthStore((state) => state.accounts)
    const activeKey = useAuthStore((state) => state.activeAccountKey)
    const accountSwitch = useAccountSwitch('settings')
    const signOut = useSignOutAction()
    const openAddAccount = useOpenAddAccount()
    const [confirming, setConfirming] = useState<string | null>(null)
    const busy = accountSwitch.pending !== null || signOut.pending

    return (
        <SettingsGroup
            title="Accounts"
            footer="Only the active account sends push notifications to this phone."
            testID="settings-accounts"
        >
            {orderedAccounts(accounts, activeKey).map((account) => (
                <AccountSettingsRow
                    key={account.key}
                    account={account}
                    active={account.key === activeKey}
                    label={accountLabel(account, accounts)}
                    switching={accountSwitch.pending?.key === account.key}
                    disabled={busy}
                    switchFailed={accountSwitch.failed?.key === account.key}
                    onPress={() =>
                        account.needsSignIn
                            ? openAddAccount('settings', account)
                            : void accountSwitch.run({ key: account.key })
                    }
                    onRetrySwitch={() => void accountSwitch.run({ key: account.key })}
                    confirmingSignOut={confirming === account.key}
                    signOutPending={signOut.pending && confirming === account.key}
                    signOutError={confirming === account.key ? signOut.error : null}
                    onStartSignOut={() => {
                        signOut.clearError()
                        setConfirming(account.key)
                    }}
                    onCancelSignOut={() => {
                        signOut.clearError()
                        setConfirming(null)
                    }}
                    onConfirmSignOut={() =>
                        void signOut.run(account.key).then(() => {
                            if (!useAuthStore.getState().accounts.some((left) => left.key === account.key)) {
                                setConfirming(null)
                            }
                        })
                    }
                />
            ))}
            <AddAccountRow
                onPress={() => openAddAccount('settings')}
                disabled={busy}
                style={styles.addRow}
                testID="settings-add-account"
            />
        </SettingsGroup>
    )
}

const useStyles = createStyles(() => ({
    addRow: {
        minHeight: 52,
        paddingHorizontal: 16,
        paddingVertical: 8,
    },
}))
