import { act, fireEvent, render, screen } from '@testing-library/react-native'
import { Linking, Platform } from 'react-native'

import { buildDemoFixtures } from '@/demo/fixtures'
import { loadingQuery, successQuery } from '@/model/queryStates'
import type { ReportActions, ReportView } from '@/model/types'
import { OverlayHost } from '@/ui/OverlayPortal'

import { externalHandoffUrl } from '../handoff/externalHandoff'
import { useHandoffPreferenceStore } from '../handoff/handoffPreferenceStore'
import { useHandoffStore } from '../handoff/handoffStore'
import { useReport, useReportActions } from '../report/hooks'
import { InboxRowActions } from './InboxRowActions'

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
jest.mock('expo-router', () => ({ useRouter: () => ({ push: jest.fn() }) }))
jest.mock('@/lib/analytics', () => ({ track: jest.fn() }))
jest.mock('../report/hooks', () => ({ useReport: jest.fn(), useReportActions: jest.fn() }))
jest.mock('../reviewers/hooks', () => ({ useReportReviewers: () => undefined, useGithubOnlyReviewerCount: () => 0 }))
jest.mock('../reviewers/AssigneeSheet', () => ({ AssigneeSheet: () => null }))

const fixture = buildDemoFixtures(new Date(2026, 9, 14)).list.find((item) => item.report.work.state === 'unclaimed')
if (!fixture) {
    throw new Error('Missing idle demo report')
}
const REPORT = fixture.report
const TARGET = { item: fixture.item, anchor: { x: 16, y: 180, width: 360, height: 72 } }
const originalOS = Platform.OS
let actions: ReportActions

beforeEach(() => {
    jest.clearAllMocks()
    jest.spyOn(Linking, 'openURL').mockReset()
    Platform.OS = 'android'
    useHandoffPreferenceStore.getState().setTarget('posthog')
    useHandoffStore.setState({ reports: {} })
    actions = {
        handOff: jest.fn(async () => undefined),
        answerDecision: jest.fn(),
        undoDecision: jest.fn(),
        snooze: jest.fn(),
        resolve: jest.fn(),
        dismiss: jest.fn(),
        setReviewers: jest.fn(),
        setPriority: jest.fn(),
        markRead: jest.fn(async () => undefined),
        markUnread: jest.fn(async () => undefined),
        pending: {
            handOff: false,
            answer: false,
            snooze: false,
            reviewers: false,
            priority: false,
            resolve: false,
            dismiss: false,
        },
    }
    jest.mocked(useReport).mockReturnValue(successQuery(REPORT))
    jest.mocked(useReportActions).mockReturnValue(actions)
})
afterEach(() => {
    Platform.OS = originalOS
    jest.restoreAllMocks()
})

test.each([
    ['posthog', 'PostHog'],
    ['claude', 'Claude Code'],
    ['codex', 'Codex'],
] as const)('hands the selected report to the saved %s agent and blocks duplicate taps', async (target, name) => {
    useHandoffPreferenceStore.getState().setTarget(target)
    let finish!: () => void
    const pending = new Promise<void>((resolve) => {
        finish = resolve
    })
    jest.mocked(actions.handOff).mockReturnValue(pending)
    const open = jest.spyOn(Linking, 'openURL').mockReturnValue(pending)
    const close = jest.fn()
    render(<InboxRowActions target={TARGET} onClose={close} />, { wrapper: OverlayHost })
    expect(screen.getByTestId('inbox-row-menu-handoff')).toHaveTextContent(`Hand off to ${name}`)
    fireEvent.press(screen.getByTestId('inbox-row-menu-handoff'))
    fireEvent.press(screen.getByTestId('inbox-row-menu-handoff'))
    expect(screen.getByTestId('inbox-row-menu-handoff')).toBeDisabled()
    expect(close).not.toHaveBeenCalled()
    if (target === 'posthog') {
        expect(actions.handOff).toHaveBeenCalledTimes(1)
        expect(open).not.toHaveBeenCalled()
    } else {
        expect(open).toHaveBeenCalledTimes(1)
        expect(open).toHaveBeenCalledWith(externalHandoffUrl(target, REPORT))
        expect(actions.handOff).not.toHaveBeenCalled()
    }
    await act(async () => finish())
    expect(close).toHaveBeenCalledTimes(1)
})

test.each(['posthog', 'claude'] as const)('keeps a failed %s handoff visible and retryable', async (target) => {
    useHandoffPreferenceStore.getState().setTarget(target)
    jest.spyOn(Linking, 'openURL').mockRejectedValueOnce(new Error('Unavailable')).mockResolvedValue(undefined)
    jest.mocked(actions.handOff)
        .mockImplementationOnce(async () => {
            useHandoffStore.getState().setNotice(REPORT.id, 'Could not start the run. Try again.')
        })
        .mockImplementation(async () => {
            useHandoffStore.getState().setNotice(REPORT.id, undefined)
        })
    const close = jest.fn()
    render(<InboxRowActions target={TARGET} onClose={close} />, { wrapper: OverlayHost })
    await act(async () => fireEvent.press(screen.getByTestId('inbox-row-menu-handoff')))
    expect(screen.getByTestId('inbox-row-menu-handoff-error')).toHaveTextContent(/Try again/)
    expect(close).not.toHaveBeenCalled()
    expect(screen.getByTestId('inbox-row-menu-handoff')).toBeEnabled()
    await act(async () => fireEvent.press(screen.getByTestId('inbox-row-menu-handoff')))
    expect(screen.queryByTestId('inbox-row-menu-handoff-error')).toBeNull()
    expect(close).toHaveBeenCalledTimes(1)
})

test('waits for report details and prevents a second handoff before the server refreshes', () => {
    jest.mocked(useReport).mockReturnValue(loadingQuery())
    const props = { target: TARGET, onClose: jest.fn() }
    const view = render(<InboxRowActions {...props} />, { wrapper: OverlayHost })
    expect(screen.getByTestId('inbox-row-menu-handoff')).toBeDisabled()
    fireEvent.press(screen.getByTestId('inbox-row-menu-handoff'))
    expect(actions.handOff).not.toHaveBeenCalled()
    jest.mocked(useReport).mockReturnValue(successQuery(REPORT))
    view.rerender(<InboxRowActions {...props} />)
    expect(screen.getByTestId('inbox-row-menu-handoff')).toBeEnabled()
    act(() => useHandoffStore.getState().setStarted(REPORT.id, { taskId: 'task-1', runId: 'run-1' }))
    expect(screen.queryByTestId('inbox-row-menu-handoff')).toBeNull()
})

test('offers View PR from the row data before report details load and never shows handoff', () => {
    jest.mocked(useReport).mockReturnValue(loadingQuery())
    const open = jest.spyOn(Linking, 'openURL').mockResolvedValue(undefined)
    const close = jest.fn()
    const url = 'https://github.com/example/app/pull/77'
    const props = { target: { ...TARGET, item: { ...TARGET.item, pullRequestUrl: url } }, onClose: close }
    const view = render(<InboxRowActions {...props} />, { wrapper: OverlayHost })
    expect(screen.queryByTestId('inbox-row-menu-handoff')).toBeNull()
    expect(screen.getByTestId('inbox-row-menu-view-pr')).toHaveTextContent('View PR')
    jest.mocked(useReport).mockReturnValue(successQuery(REPORT))
    view.rerender(<InboxRowActions {...props} />)
    expect(screen.queryByTestId('inbox-row-menu-handoff')).toBeNull()
    fireEvent.press(screen.getByTestId('inbox-row-menu-view-pr'))
    expect(open).toHaveBeenCalledWith(url)
    expect(close).toHaveBeenCalledTimes(1)
})

test.each<Partial<ReportView>>([
    { status: 'resolved' },
    { canAct: false },
    { work: { ...REPORT.work, assignee: { kind: 'agent', name: 'Codex' } } },
])('omits handoff for an ineligible report: %j', (change) => {
    jest.mocked(useReport).mockReturnValue(successQuery({ ...REPORT, ...change }))
    render(<InboxRowActions target={TARGET} onClose={jest.fn()} />, { wrapper: OverlayHost })
    expect(screen.queryByTestId('inbox-row-menu-handoff')).toBeNull()
    expect(screen.getByTestId('inbox-row-menu-chat')).toBeEnabled()
})

test.each([
    ['an unread report as read', false, 'inbox-row-menu-mark-read', 'inbox-row-menu-mark-unread', 'markRead'],
    ['a read report as unread', true, 'inbox-row-menu-mark-unread', 'inbox-row-menu-mark-read', 'markUnread'],
] as const)('marks %s and closes the menu', (_name, read, shown, hidden, action) => {
    const close = jest.fn()
    render(<InboxRowActions target={{ ...TARGET, item: { ...TARGET.item, read } }} onClose={close} />, {
        wrapper: OverlayHost,
    })
    expect(screen.queryByTestId(hidden)).toBeNull()
    fireEvent.press(screen.getByTestId(shown))
    expect(actions[action]).toHaveBeenCalledTimes(1)
    expect(close).toHaveBeenCalledTimes(1)
})

test.each([
    ['resolve', 'fixed_outside_posthog'],
    ['dismiss', 'analysis_wrong'],
] as const)('opens the %s sheet from the menu and closes after the verdict', async (verdict, reason) => {
    const close = jest.fn()
    render(<InboxRowActions target={TARGET} onClose={close} />, { wrapper: OverlayHost })
    fireEvent.press(screen.getByTestId(`inbox-row-menu-${verdict}`))
    fireEvent.press(screen.getByTestId(`${verdict}-sheet-reason-${reason}`))
    await act(async () => fireEvent.press(screen.getByTestId(`${verdict}-sheet-confirm`)))
    expect(actions[verdict]).toHaveBeenCalledWith(reason, '')
    expect(close).toHaveBeenCalledTimes(1)
})
