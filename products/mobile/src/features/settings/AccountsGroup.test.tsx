import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react-native'
import { View } from 'react-native'

import { useAuthStore } from '@/auth/authStore'
import { EU_ACCOUNT, SELF_HOSTED_ACCOUNT, US_ACCOUNT } from '@/features/accounts/testAccounts'

import { AccountsGroup } from './AccountsGroup'
import { SignOutSection } from './SignOutSection'

const mockRouter = { push: jest.fn(), replace: jest.fn() }
jest.mock('expo-router', () => ({
    ...jest.requireActual('expo-router'),
    useIsFocused: () => true,
    useRouter: () => mockRouter,
}))

const INITIAL_AUTH = useAuthStore.getState()

describe('Settings accounts', () => {
    const switchAccount = jest.fn(async () => undefined)
    const signOutAccount = jest.fn(async () => undefined)
    const signOutAll = jest.fn(async () => undefined)

    beforeEach(() => {
        act(() =>
            useAuthStore.setState({
                status: 'signed_in',
                signedIn: true,
                accounts: [US_ACCOUNT, EU_ACCOUNT, SELF_HOSTED_ACCOUNT],
                activeAccountKey: US_ACCOUNT.key,
                switchAccount,
                signOutAccount,
                signOutAll,
            })
        )
        render(
            <View>
                <AccountsGroup />
                <SignOutSection />
            </View>
        )
    })
    afterEach(() => {
        cleanup()
        act(() => useAuthStore.setState(INITIAL_AUTH, true))
        jest.clearAllMocks()
    })

    test('lists every account with its state; a row switches to its account or opens sign-in for it', async () => {
        expect(screen.getByTestId('settings-account-active')).toHaveTextContent(/maya@example\.comUSActive/)
        expect(screen.getByTestId(`settings-account-${SELF_HOSTED_ACCOUNT.key}`)).toHaveTextContent(/Sign in again/)

        await act(async () => fireEvent.press(screen.getByTestId(`settings-account-${EU_ACCOUNT.key}-open`)))
        expect(switchAccount).toHaveBeenCalledWith(EU_ACCOUNT.key, { from: 'settings' })

        fireEvent.press(screen.getByTestId(`settings-account-${SELF_HOSTED_ACCOUNT.key}-open`))
        expect(mockRouter.push).toHaveBeenCalledWith({
            pathname: '/sign-in',
            params: { mode: 'add', reauth: SELF_HOSTED_ACCOUNT.key },
        })
    })

    test('a row signs out of only its account after a confirmation that names it', async () => {
        fireEvent.press(screen.getByTestId(`settings-account-${EU_ACCOUNT.key}-sign-out`))
        const confirm = screen.getByTestId(`settings-account-${EU_ACCOUNT.key}-sign-out-confirm`)
        expect(within(confirm).getByText('Sign out of maya@example.com (EU)?')).toBeTruthy()
        expect(
            within(confirm).getByText(
                'You stay signed in to maya@example.com (US). Notifications keep coming from that account.'
            )
        ).toBeTruthy()

        await act(async () =>
            fireEvent.press(screen.getByTestId(`settings-account-${EU_ACCOUNT.key}-sign-out-confirm-button`))
        )
        expect(signOutAccount).toHaveBeenCalledWith(EU_ACCOUNT.key)
        expect(signOutAll).not.toHaveBeenCalled()
    })

    test('the bottom button signs out of every account after stating how many', async () => {
        fireEvent.press(screen.getByTestId('settings-sign-out'))
        expect(screen.getByText('Sign out of all 3 accounts?')).toBeTruthy()

        await act(async () => fireEvent.press(screen.getByTestId('settings-sign-out-confirm-button')))
        expect(signOutAll).toHaveBeenCalled()
        expect(signOutAccount).not.toHaveBeenCalled()
    })
})
