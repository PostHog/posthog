import AsyncStorage from '@react-native-async-storage/async-storage'
import { act, fireEvent, render, screen } from '@testing-library/react-native'
import * as Clipboard from 'expo-clipboard'
import { Linking, Platform } from 'react-native'

import { buildDemoFixtures } from '@/demo/fixtures'
import { OverlayHost } from '@/ui/OverlayPortal'

import { externalHandoffPrompt, externalHandoffUrl } from './externalHandoff'
import { HandoffSheet } from './HandoffSheet'
import { HandoffSplitButton } from './HandoffSplitButton'
import { useHandoffPreferenceStore } from './handoffPreferenceStore'

jest.mock('@react-native-async-storage/async-storage', () =>
    jest.requireActual('@react-native-async-storage/async-storage/jest/async-storage-mock')
)
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
jest.mock('./useRunOptions', () => ({
    useRunDefaults: () => undefined,
    useModelCatalogue: () => ({ catalogue: [], loading: false, unavailable: false }),
    useRunOptionActions: () => ({}),
}))

const FIXTURE = buildDemoFixtures(new Date(2026, 9, 14)).byId['demo-report-ui-errors']
if (!FIXTURE) {
    throw new Error('Missing demo report')
}
const REPORT = { ...FIXTURE.report, repository: 'example/app' }
const originalOS = Platform.OS

beforeEach(() => {
    jest.clearAllMocks()
    Platform.OS = 'android'
    useHandoffPreferenceStore.getState().setTarget('posthog')
})
afterEach(() => {
    Platform.OS = originalOS
    jest.restoreAllMocks()
})

test('blocks repeated launches and offers copying after a failed launch without starting a run', async () => {
    let rejectLaunch!: (error: Error) => void
    const open = jest.spyOn(Linking, 'openURL').mockImplementation(
        () =>
            new Promise((_, reject) => {
                rejectLaunch = reject
            })
    )
    const copy = jest.spyOn(Clipboard, 'setStringAsync').mockResolvedValue(true)
    const onHandOff = jest.fn()
    const onClose = jest.fn()
    render(<HandoffSheet visible report={REPORT} pending={false} onClose={onClose} onHandOff={onHandOff} />, {
        wrapper: OverlayHost,
    })
    fireEvent.press(screen.getByTestId('handoff-agent-codex'))
    fireEvent.press(screen.getByTestId('handoff-agent-codex'))
    expect(open).toHaveBeenCalledTimes(1)
    expect(screen.getByTestId('handoff-agent-claude')).toBeDisabled()
    expect(screen.getByTestId('copy-prompt')).toBeDisabled()
    expect(screen.queryByTestId('handoff-agent-share')).toBeNull()
    expect(screen.getByTestId('handoff-agent-posthog')).toBeDisabled()
    await act(async () => rejectLaunch(new Error('No application installed')))
    expect(screen.getByTestId('handoff-external-error')).toHaveTextContent(/copy the prompt/)
    await act(async () => fireEvent.press(screen.getByTestId('copy-prompt')))
    expect(copy).toHaveBeenCalledWith(externalHandoffPrompt(REPORT))
    expect(useHandoffPreferenceStore.getState().target).toBe('codex')
    expect(screen.queryByTestId('handoff-external-error')).toBeNull()
    expect(onHandOff).not.toHaveBeenCalled()
    expect(onClose).not.toHaveBeenCalled()
    expect(screen.getByTestId('handoff-agent-codex')).toBeEnabled()
})

test('failed clipboard writes do not announce Copied and can be retried with the same prepared prompt', async () => {
    const copy = jest
        .spyOn(Clipboard, 'setStringAsync')
        .mockRejectedValueOnce(new Error('Clipboard unavailable'))
        .mockResolvedValue(true)
    render(<HandoffSheet visible report={REPORT} pending={false} onClose={jest.fn()} onHandOff={jest.fn()} />, {
        wrapper: OverlayHost,
    })
    await act(async () => fireEvent.press(screen.getByTestId('copy-prompt')))
    expect(screen.queryByText('Copied')).toBeNull()
    expect(screen.getByTestId('handoff-external-error')).toHaveTextContent(/Couldn't copy the prompt/)
    await act(async () => fireEvent.press(screen.getByTestId('copy-prompt')))
    expect(screen.getByText('Copied')).toBeTruthy()
    expect(copy).toHaveBeenLastCalledWith(externalHandoffPrompt(REPORT))
})

test.each(['claude', 'codex'] as const)(
    'remembers %s across reports and reloads, and can switch back to PostHog',
    async (target) => {
        const open = jest.spyOn(Linking, 'openURL').mockResolvedValue(undefined)
        const onHandOff = jest.fn()
        const view = render(
            <HandoffSheet visible report={REPORT} pending={false} onClose={jest.fn()} onHandOff={onHandOff} />,
            { wrapper: OverlayHost }
        )
        await act(async () => fireEvent.press(screen.getByTestId(`handoff-agent-${target}`)))
        expect(onHandOff).not.toHaveBeenCalled()
        view.unmount()

        // Rehydrate the saved preference as a fresh app instance would.
        const saved = await AsyncStorage.getItem('posthog-mobile-handoff-preference')
        if (!saved) {
            throw new Error('Missing saved handoff preference')
        }
        useHandoffPreferenceStore.getState().setTarget('posthog')
        await AsyncStorage.setItem('posthog-mobile-handoff-preference', saved)
        await useHandoffPreferenceStore.persist.rehydrate()

        const otherReport = { ...REPORT, id: 'another-report', prompt: 'Investigate this other report.' }
        const button = render(
            <HandoffSplitButton report={otherReport} pending={false} onOpenPicker={jest.fn()} onHandOff={onHandOff} />
        )
        const name = target === 'claude' ? 'Claude Code' : 'Codex'
        expect(screen.getByTestId('handoff-button')).toHaveTextContent(`Hand off to ${name}`)
        await act(async () => fireEvent.press(screen.getByTestId('handoff-button')))
        expect(open).toHaveBeenLastCalledWith(externalHandoffUrl(target, otherReport))
        expect(onHandOff).not.toHaveBeenCalled()
        button.unmount()

        render(
            <>
                <HandoffSheet visible report={REPORT} pending={false} onClose={jest.fn()} onHandOff={onHandOff} />
                <HandoffSplitButton report={REPORT} pending={false} onOpenPicker={jest.fn()} onHandOff={onHandOff} />
            </>,
            { wrapper: OverlayHost }
        )
        fireEvent.press(screen.getByTestId('handoff-agent-posthog'))
        expect(screen.getByTestId('handoff-button')).toHaveTextContent(/Hand off to PostHog/)
        await act(async () => fireEvent.press(screen.getByTestId('handoff-button')))
        expect(onHandOff).toHaveBeenCalledTimes(2)
        expect(open).toHaveBeenCalledTimes(2)
    }
)

test('the preferred external shortcut prevents duplicate launches and recovers after a failure', async () => {
    useHandoffPreferenceStore.getState().setTarget('claude')
    let rejectLaunch!: (error: Error) => void
    const open = jest
        .spyOn(Linking, 'openURL')
        .mockImplementationOnce(
            () =>
                new Promise((_, reject) => {
                    rejectLaunch = reject
                })
        )
        .mockResolvedValue(undefined)
    const onHandOff = jest.fn()
    render(<HandoffSplitButton report={REPORT} pending={false} onOpenPicker={jest.fn()} onHandOff={onHandOff} />)
    fireEvent.press(screen.getByTestId('handoff-button'))
    fireEvent.press(screen.getByTestId('handoff-button'))
    expect(open).toHaveBeenCalledTimes(1)
    expect(screen.getByTestId('handoff-button')).toBeDisabled()
    expect(screen.getByTestId('handoff-picker-button')).toBeDisabled()
    await act(async () => rejectLaunch(new Error('App unavailable')))
    expect(screen.getByTestId('handoff-launch-error')).toHaveTextContent(/Couldn't open Claude Code/)
    expect(screen.getByTestId('handoff-picker-button')).toBeEnabled()
    await act(async () => fireEvent.press(screen.getByTestId('handoff-button')))
    expect(screen.queryByTestId('handoff-launch-error')).toBeNull()
    expect(open).toHaveBeenCalledTimes(2)
    expect(onHandOff).not.toHaveBeenCalled()
})
