import { act, cleanup, fireEvent, render, screen } from '@testing-library/react-native'
import { isLiquidGlassAvailable } from 'expo-glass-effect'

import { AccountNeedsSignInError, type StoredAccount, useAuthStore } from '@/auth/authStore'
import { useDemoMode } from '@/demo/demoMode'
import { EU_ACCOUNT, SELF_HOSTED_ACCOUNT, US_ACCOUNT } from '@/features/accounts/testAccounts'
import { OverlayHost } from '@/ui/OverlayPortal'

import { ProjectSheet } from './ProjectSheet'

jest.mock('react-native-worklets', () => jest.requireActual('react-native-worklets/src/mock'))
jest.mock('react-native-reanimated', () => ({
    ...jest.requireActual('react-native-reanimated/mock'),
    useReducedMotion: () => true,
}))
jest.mock(
    'react-native-safe-area-context',
    () => jest.requireActual('react-native-safe-area-context/jest/mock').default
)
jest.mock('react-native-keyboard-controller', () => jest.requireActual('react-native-keyboard-controller/jest'))
const mockPush = jest.fn()
jest.mock('expo-router', () => ({
    ...jest.requireActual('expo-router'),
    useIsFocused: () => true,
    useRouter: () => ({ push: mockPush }),
}))

const initialAuth = useAuthStore.getState()

function signIn(accounts: StoredAccount[], overrides: Partial<ReturnType<typeof useAuthStore.getState>> = {}): void {
    const active = accounts[0] as StoredAccount
    useAuthStore.setState({
        status: 'signed_in',
        signedIn: true,
        accounts,
        activeAccountKey: active.key,
        host: active.host,
        user: active.user,
        projects: active.projects,
        projectId: active.projectId,
        projectName: 'Hedgebox web',
        reloadAccount: jest.fn(async () => undefined),
        switchAccount: jest.fn(async () => undefined),
        ...overrides,
    })
}

function renderSheet(): { onClose: jest.Mock; onSelect: jest.Mock } {
    const onClose = jest.fn()
    const onSelect = jest.fn()
    render(<ProjectSheet visible onClose={onClose} onSelect={onSelect} />, { wrapper: OverlayHost })
    return { onClose, onSelect }
}

describe('ProjectSheet', () => {
    afterEach(() => {
        // Unmount first: the card reloads the account when the store's reload function changes.
        cleanup()
        act(() => {
            useAuthStore.setState(initialAuth, true)
            useDemoMode.setState({ enabled: false })
        })
        mockPush.mockReset()
        jest.mocked(isLiquidGlassAvailable).mockReturnValue(false)
    })

    test.each([
        ['draws the card on Liquid Glass where the system has it', true],
        ['keeps the solid card where the system has no glass', false],
    ])('%s', async (_name, available) => {
        jest.mocked(isLiquidGlassAvailable).mockReturnValue(available)
        act(() => signIn([US_ACCOUNT]))
        renderSheet()
        await act(async () => undefined)

        expect(screen.queryByTestId('floating-card-glass') !== null).toBe(available)
        expect(screen.getByTestId('project-sheet-1')).toBeChecked()
    })

    test.each([false, true])(
        'with one account (demo %s) lists projects as before, with Add account only outside demo',
        (demo) => {
            act(() => {
                signIn([US_ACCOUNT])
                useDemoMode.setState({ enabled: demo })
            })
            const { onClose } = renderSheet()

            expect(screen.queryByTestId('project-sheet-account-active')).toBeNull()
            if (demo) {
                expect(screen.queryByTestId('project-sheet-add-account')).toBeNull()
                return
            }
            expect(screen.getByTestId('project-sheet-1')).toBeChecked()
            expect(screen.getByTestId('project-sheet-3')).toBeTruthy()
            fireEvent.press(screen.getByTestId('project-sheet-add-account'))
            expect(onClose).toHaveBeenCalled()
            expect(mockPush).toHaveBeenCalledWith({ pathname: '/sign-in', params: { mode: 'add' } })
        }
    )

    test('a project of another account switches to it, and blocks every row until the switch settles', async () => {
        let finish: () => void = () => undefined
        const switchAccount = jest.fn(
            () =>
                new Promise<void>((resolve) => {
                    finish = resolve
                })
        )
        act(() => signIn([US_ACCOUNT, EU_ACCOUNT], { switchAccount }))
        const { onSelect } = renderSheet()
        expect(screen.getByTestId('project-sheet-account-active')).toHaveTextContent(/maya@example\.comUS/)
        expect(screen.getByTestId('project-sheet-account-eu-account')).toHaveTextContent(/maya@example\.comEU/)

        fireEvent.press(screen.getByTestId('project-sheet-eu-account-1'))
        expect(switchAccount).toHaveBeenCalledWith(EU_ACCOUNT.key, { projectId: 1, from: 'nav_menu' })
        expect(screen.getByTestId('project-sheet-eu-account-1-switching')).toBeTruthy()

        fireEvent.press(screen.getByTestId('project-sheet-eu-account-1'))
        fireEvent.press(screen.getByTestId('project-sheet-2'))
        expect(switchAccount).toHaveBeenCalledTimes(1)
        expect(onSelect).not.toHaveBeenCalled()

        await act(async () => finish())
        expect(screen.queryByTestId('project-sheet-eu-account-1-switching')).toBeNull()
    })

    test.each<[string, Error, boolean]>([
        ['a failure shows a retry line', new Error('Keychain unavailable'), true],
        ['an ended session needs no extra line', new AccountNeedsSignInError(EU_ACCOUNT), false],
    ])('%s', async (_name, error, shown) => {
        const switchAccount = jest.fn(async () => {
            throw error
        })
        act(() => signIn([US_ACCOUNT, EU_ACCOUNT], { switchAccount }))
        renderSheet()

        await act(async () => fireEvent.press(screen.getByTestId('project-sheet-eu-account-1')))

        expect(screen.queryByTestId('project-sheet-account-eu-account-error') !== null).toBe(shown)
        if (shown) {
            await act(async () => fireEvent.press(screen.getByTestId('project-sheet-account-eu-account-retry')))
            expect(switchAccount).toHaveBeenLastCalledWith(EU_ACCOUNT.key, { projectId: 1, from: 'nav_menu' })
        }
    })

    test('an account whose session ended lists no projects, offers sign-in, and a search says it was skipped', () => {
        act(() => signIn([US_ACCOUNT, SELF_HOSTED_ACCOUNT]))
        renderSheet()
        expect(screen.getByText('Session ended')).toBeTruthy()
        expect(screen.queryByText('Internal tools')).toBeNull()

        fireEvent.changeText(screen.getByTestId('project-search'), 'web')
        expect(screen.getByTestId('project-sheet-1')).toBeTruthy()
        expect(screen.getByTestId('project-sheet-3')).toBeTruthy()
        expect(screen.queryByTestId('project-sheet-2')).toBeNull()
        expect(screen.getByTestId('project-sheet-skipped')).toHaveTextContent(
            'Projects in maya@example.org show after you sign in again.'
        )
        expect(screen.queryByTestId('project-sheet-add-account')).toBeNull()

        fireEvent.changeText(screen.getByTestId('project-search'), '')
        fireEvent.press(screen.getByTestId('project-sheet-account-self-hosted-account-sign-in'))
        expect(mockPush).toHaveBeenCalledWith({
            pathname: '/sign-in',
            params: { mode: 'add', reauth: SELF_HOSTED_ACCOUNT.key },
        })
    })
})
