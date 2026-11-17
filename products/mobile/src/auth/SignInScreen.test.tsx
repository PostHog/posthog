import { act, cleanup, fireEvent, render, screen } from '@testing-library/react-native'
import { Linking, Platform } from 'react-native'

import { EU_ACCOUNT, SELF_HOSTED_ACCOUNT, US_ACCOUNT } from '@/features/accounts/testAccounts'
import { OverlayHost } from '@/ui/OverlayPortal'

import { type AuthState, useAuthStore } from './authStore'
import { SignInScreen } from './SignInScreen'
import { AccountAlreadyAddedError, type AccountAlreadyAddedOptions } from './signInErrors'

jest.mock('react-native-worklets', () => jest.requireActual('react-native-worklets/src/mock'))
jest.mock('react-native-reanimated', () => ({
    ...jest.requireActual('react-native-reanimated/mock'),
    useReducedMotion: () => true,
}))
jest.mock(
    'react-native-safe-area-context',
    () => jest.requireActual('react-native-safe-area-context/jest/mock').default
)
const mockRouter = { push: jest.fn(), replace: jest.fn(), back: jest.fn(), canGoBack: jest.fn(() => true) }
let mockParams: Record<string, string> = {}
jest.mock('expo-router', () => ({
    ...jest.requireActual('expo-router'),
    useIsFocused: () => true,
    useRouter: () => mockRouter,
    useLocalSearchParams: () => mockParams,
}))

const INITIAL_AUTH = useAuthStore.getState()
const ENDED = SELF_HOSTED_ACCOUNT

function setAuth(state: Partial<AuthState>): void {
    act(() => useAuthStore.setState(state))
}

const signedInAsUs: Partial<AuthState> = {
    status: 'signed_in',
    signedIn: true,
    accounts: [US_ACCOUNT, EU_ACCOUNT, SELF_HOSTED_ACCOUNT],
    activeAccountKey: US_ACCOUNT.key,
    host: US_ACCOUNT.host,
    region: 'us',
}

describe('SignInScreen', () => {
    const originalPlatform = Platform.OS
    afterEach(() => {
        cleanup()
        act(() => useAuthStore.setState(INITIAL_AUTH, true))
        Platform.OS = originalPlatform
        mockParams = {}
        jest.clearAllMocks()
    })

    test.each<[string, Record<string, string>, string, string | null]>([
        ['add mode', { mode: 'add' }, 'Add another account to this phone.', null],
        [
            'Sign in again for a stored account',
            { mode: 'add', reauth: SELF_HOSTED_ACCOUNT.key },
            'Your other accounts stay signed in.',
            'Sign in again to use maya@example.org.',
        ],
    ])('%s opens while signed in, without the demo, and Cancel returns', (_name, params, subtitle, notice) => {
        mockParams = params
        setAuth(signedInAsUs)
        render(<SignInScreen />, { wrapper: OverlayHost })

        expect(screen.getByText(subtitle)).toBeTruthy()
        expect(screen.queryByTestId('try-demo')).toBeNull()
        if (notice) {
            expect(screen.getByTestId('sign-in-reauth')).toHaveTextContent(notice)
            expect(screen.getByTestId('sign-in-host').props.value).toBe('https://posthog.example.org')
            expect(screen.queryByTestId('sign-in-self-hosted')).toBeNull()
        }
        fireEvent.press(screen.getByTestId('sign-in-cancel'))
        expect(mockRouter.back).toHaveBeenCalled()
    })

    const PRIVATE_SESSION_TEXT =
        'You signed in as maya@example.com, and that account is already on this phone. To add a different account, try again and sign in with it.'
    // On iOS, so a notice that reads the platform instead of the error fails the shared case.
    test.each<[string, AccountAlreadyAddedOptions, string, boolean]>([
        [
            'a shared browser session',
            {},
            'Your browser is still signed in to PostHog as maya@example.com, and that account is already on this phone. To add a different account, sign out of PostHog in the browser, then try again.',
            true,
        ],
        ['a private browser session', { privateSession: true }, PRIVATE_SESSION_TEXT, false],
        [
            'a sign-in that asked for the account chooser',
            { selectAccount: true },
            'Your browser is signed in to PostHog as maya@example.com, and that account is already on this phone. To add a different account, try again and choose "Use a different account".',
            false,
        ],
        // The chooser never appears in a private session, which starts signed out.
        [
            'a private browser session that asked for the account chooser',
            { privateSession: true, selectAccount: true },
            PRIVATE_SESSION_TEXT,
            false,
        ],
    ])(
        'after %s, an account that is already on the phone gets the next steps that apply',
        async (_name, options, text, opensBrowser) => {
            Platform.OS = 'ios'
            mockParams = { mode: 'add' }
            const signIn = jest.fn(async () => {
                throw new AccountAlreadyAddedError(US_ACCOUNT.key, 'maya@example.com', US_ACCOUNT.host, options)
            })
            setAuth({ ...signedInAsUs, signIn })
            const openURL = jest.spyOn(Linking, 'openURL').mockResolvedValue(undefined)
            render(<SignInScreen />, { wrapper: OverlayHost })

            await act(async () => fireEvent.press(screen.getByTestId('sign-in')))

            expect(screen.getByTestId('sign-in-already-added')).toHaveTextContent(text, { exact: false })
            if (opensBrowser) {
                fireEvent.press(screen.getByTestId('sign-in-open-browser'))
                expect(openURL).toHaveBeenCalledWith(US_ACCOUNT.host)
            } else {
                expect(screen.queryByTestId('sign-in-open-browser')).toBeNull()
            }
            await act(async () => fireEvent.press(screen.getByTestId('sign-in-retry')))
            expect(signIn).toHaveBeenCalledTimes(2)
        }
    )

    test('after an expiry, names the account, switches to another one, and Sign in again can be canceled', async () => {
        const switchAccount = jest.fn(async () => undefined)
        setAuth({
            status: 'signed_out',
            signedOutReason: 'expired',
            expiredAccountKey: ENDED.key,
            accounts: [US_ACCOUNT, EU_ACCOUNT, ENDED],
            activeAccountKey: null,
            switchAccount,
        })
        render(<SignInScreen />, { wrapper: OverlayHost })

        expect(screen.getByTestId('session-ended-screen')).toHaveTextContent(/maya@example\.orgposthog\.example\.org/)
        expect(
            screen.getByText('Sign in again to keep using this account. Your other accounts stay signed in.')
        ).toBeTruthy()
        await act(async () => fireEvent.press(screen.getByTestId(`session-ended-switch-${EU_ACCOUNT.key}`)))
        expect(switchAccount).toHaveBeenCalledWith(EU_ACCOUNT.key, { from: 'sign_in' })

        fireEvent.press(screen.getByTestId('session-ended-sign-in'))
        expect(screen.getByTestId('sign-in-host').props.value).toBe('https://posthog.example.org')
        fireEvent.press(screen.getByTestId('sign-in-cancel'))
        expect(screen.getByTestId('session-ended-screen')).toBeTruthy()
        expect(mockRouter.back).not.toHaveBeenCalled()
    })

    test('an expiry with no stored account keeps the plain sign-in form', () => {
        setAuth({ status: 'signed_out', signedOutReason: 'expired', accounts: [], activeAccountKey: null })
        render(<SignInScreen />, { wrapper: OverlayHost })

        expect(screen.getByTestId('sign-in-expired')).toBeTruthy()
        expect(screen.getByTestId('try-demo')).toBeTruthy()
        expect(screen.queryByTestId('sign-in-cancel')).toBeNull()
    })
})
