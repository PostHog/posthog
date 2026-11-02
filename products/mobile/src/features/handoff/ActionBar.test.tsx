import { act, fireEvent, render, screen, within } from '@testing-library/react-native'
import type { ComponentProps } from 'react'

import { buildDemoFixtures } from '@/demo/fixtures'
import type { ActionBarState, PullRequestView, ReportActions } from '@/model/types'
import { OverlayHost } from '@/ui/OverlayPortal'

import { ActionBar } from './ActionBar'
import { useHandoffStore } from './handoffStore'
import { usePullRequestChecks } from './usePullRequestChecks'

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
jest.mock('@/demo/demoMode', () => ({ useDataMode: () => 'live' }))
jest.mock('./usePullRequestChecks', () => ({
    usePullRequestChecks: jest.fn(() => ({ status: 'unavailable', isRefreshing: false })),
}))

const FIXTURE = buildDemoFixtures(new Date(2026, 9, 14)).byId['demo-report-ui-errors']
if (!FIXTURE) {
    throw new Error('Missing demo report')
}
const REPORT = FIXTURE.report
const DRAFT_PR: PullRequestView = {
    url: 'https://github.com/example/app/pull/1',
    number: 1,
    title: 'Fix chart labels',
    state: 'draft',
}
const PULL_REQUESTS: PullRequestView[] = [
    DRAFT_PR,
    { url: 'https://github.com/example/app/pull/2', number: 2, title: 'Update legend tests', state: 'merged' },
    { url: 'https://github.com/example/app/pull/3', number: 3, title: 'Add keyboard support', state: 'closed' },
    { url: 'https://github.com/example/app/pull/4', number: 4, title: 'Check tooltip layout', state: 'unknown' },
]

beforeEach(() => {
    jest.useFakeTimers()
    useHandoffStore.setState({ reports: {} })
    jest.mocked(usePullRequestChecks).mockReturnValue({ status: 'unavailable', isRefreshing: false })
})
afterEach(() => {
    act(() => jest.runOnlyPendingTimers())
    jest.useRealTimers()
})

function props(state: ActionBarState): ComponentProps<typeof ActionBar> {
    const actions: ReportActions = {
        handOff: jest.fn(async () => undefined),
        answerDecision: jest.fn(async () => undefined),
        undoDecision: jest.fn(async () => undefined),
        snooze: jest.fn(async () => undefined),
        resolve: jest.fn(async () => undefined),
        dismiss: jest.fn(async () => undefined),
        setReviewers: jest.fn(async () => undefined),
        setPriority: jest.fn(async () => undefined),
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
    return {
        report: REPORT,
        state,
        actions,
        onOpenHandoff: jest.fn(),
        onReassign: jest.fn(),
        onResolve: jest.fn(),
        onDismiss: jest.fn(),
        onChat: jest.fn(),
        onTaskChat: jest.fn(),
    }
}

test('keeps the PR, activity and real request together, with full question and answers in a sheet', () => {
    const question = {
        id: 'question-1',
        details: '{"path":"/example/report.txt","content":"<plain text>"}',
        question:
            '**Which fix should ship?**\n\nUse the guard for missing labels, or update the source of the labels. The full explanation remains available when the report footer is compact.',
        options: [{ id: 'guard', title: 'Guard missing labels' }],
    }
    const viewProps = props({
        pullRequests: [DRAFT_PR],
        activity: { title: 'PostHog is working', meta: 'Checking regression tests', tone: 'working' },
        request: question,
        showHandoff: false,
    })
    const { rerender } = render(<ActionBar {...viewProps} />, { wrapper: OverlayHost })
    expect(screen.getByTestId('pr-ready-card')).toBeTruthy()
    expect(screen.getByText('PostHog is working')).toBeTruthy()
    expect(screen.queryByText('Which fix should ship?')).toBeNull()
    expect(screen.queryByTestId('decision-option-guard')).toBeNull()
    fireEvent.press(screen.getByTestId('view-task-activity'))
    expect(viewProps.onTaskChat).toHaveBeenCalledTimes(1)
    expect(viewProps.onTaskChat).toHaveBeenCalledWith('pr_card')
    fireEvent.press(screen.getByTestId('decision-request'))
    expect(within(screen.getByTestId('pr-ready-card')).queryByTestId('decision-sheet')).toBeNull()
    expect(screen.getByText('Which fix should ship?')).toBeTruthy()
    expect(screen.getByText(question.details)).toBeTruthy()
    expect(screen.getByText(question.details).props.selectable).toBe(true)
    expect(screen.getByText(/The full explanation remains available/)).toBeTruthy()
    fireEvent.press(screen.getByTestId('decision-option-guard'))
    expect(viewProps.actions.answerDecision).toHaveBeenCalledWith({
        questionId: question.id,
        optionId: 'guard',
        text: 'Guard missing labels',
    })
    rerender(
        <ActionBar
            {...viewProps}
            actions={{ ...viewProps.actions, pending: { ...viewProps.actions.pending, answer: true } }}
        />
    )
    expect(screen.getByTestId('decision-option-guard')).toBeDisabled()
    fireEvent.changeText(screen.getByLabelText('Your answer'), 'Keep the guard')
    expect(screen.getByLabelText('Send')).toBeDisabled()
    rerender(<ActionBar {...viewProps} />)
    fireEvent.press(screen.getByLabelText('Send'))
    expect(viewProps.actions.answerDecision).toHaveBeenLastCalledWith({
        questionId: question.id,
        text: 'Keep the guard',
    })
})

test('selects every PR state and keeps selection by URL as activity changes', () => {
    const viewProps = props({
        pullRequests: PULL_REQUESTS,
        activity: { title: 'PostHog is working', tone: 'working' },
        showHandoff: false,
    })
    const { rerender } = render(<ActionBar {...viewProps} />, { wrapper: OverlayHost })
    expect(screen.getByTestId('pull-request-state')).toHaveTextContent('Draft')
    for (const [number, label] of [
        [2, 'Merged'],
        [3, 'Closed'],
        [4, 'Status unavailable'],
    ] as const) {
        fireEvent.press(screen.getByTestId('pull-request-selector'))
        expect(within(screen.getByTestId('pr-ready-card')).queryByTestId('pull-request-picker')).toBeNull()
        fireEvent.press(screen.getByTestId(`pull-request-option-${number}`))
        expect(screen.getByTestId('pull-request-state')).toHaveTextContent(label)
    }
    rerender(
        <ActionBar
            {...viewProps}
            state={{
                ...viewProps.state,
                pullRequests: PULL_REQUESTS.slice(1).concat(DRAFT_PR),
                activity: { title: 'PostHog finished this turn', tone: 'idle' },
            }}
        />
    )
    expect(screen.getByTestId('pull-request-title')).toHaveTextContent('Check tooltip layout')
    expect(screen.getByTestId('pull-request-state')).toHaveTextContent('Status unavailable')
    expect(screen.getByTestId('view-task-activity')).toBeTruthy()
    expect(screen.queryByTestId('decision-request')).toBeNull()
    fireEvent.press(screen.getByTestId('action-chat'))
    expect(viewProps.onChat).toHaveBeenCalledTimes(1)
    fireEvent.press(screen.getByTestId('action-resolve'))
    expect(viewProps.onResolve).toHaveBeenCalledTimes(1)
    fireEvent.press(screen.getByTestId('action-dismiss'))
    expect(viewProps.onDismiss).toHaveBeenCalledTimes(1)
    expect(screen.queryByTestId('action-snooze')).toBeNull()
})

test('allows Undo during the answer delivery that it cancels', () => {
    const answer = { questionId: 'question-1', text: 'Guard missing labels', canUndo: true }
    const viewProps = props({ pullRequests: [DRAFT_PR], showHandoff: false, answer })
    render(
        <ActionBar
            {...viewProps}
            answer={answer}
            actions={{ ...viewProps.actions, pending: { ...viewProps.actions.pending, answer: true } }}
        />
    )
    expect(screen.getByTestId('decision-undo')).toBeEnabled()
    fireEvent.press(screen.getByTestId('decision-undo'))
    expect(viewProps.actions.undoDecision).toHaveBeenCalledTimes(1)
})

test('shows checked CI data and replaces a prior pass with unavailable when it cannot be fetched', () => {
    jest.mocked(usePullRequestChecks).mockReturnValue({
        status: 'passing',
        observedAt: Date.now(),
        isRefreshing: false,
    })
    const viewProps = props({ pullRequests: [{ ...DRAFT_PR, id: 'pr-1' }], showHandoff: false })
    const { rerender } = render(<ActionBar {...viewProps} />)
    expect(screen.getByTestId('pull-request-checks')).toHaveTextContent(/Checks passed/)
    expect(screen.getByTestId('pull-request-checks')).toHaveTextContent(/Checked just now/)
    jest.mocked(usePullRequestChecks).mockReturnValue({ status: 'unavailable', isRefreshing: false })
    rerender(<ActionBar {...viewProps} />)
    expect(screen.getByTestId('pull-request-checks')).toHaveTextContent('Checks unavailable')
    expect(screen.queryByText('Checks passed')).toBeNull()
    expect(screen.getByTestId('pr-ready-card')).toBeTruthy()
})

test.each([false, true])('a task without a run can retry with local kickoff state: %s', async (remembered) => {
    if (remembered) useHandoffStore.getState().setUnstartedTask(REPORT.id, 'task-retry')
    const viewProps = props({ pullRequests: [], showHandoff: false })
    render(
        <ActionBar
            {...viewProps}
            report={{
                ...REPORT,
                work: { state: 'working', assignee: { kind: 'task', name: 'PostHog', taskId: 'task-retry' } },
                task: { taskId: 'task-retry', status: 'not_started' },
            }}
        />
    )
    await act(async () => fireEvent.press(screen.getByTestId('handoff-button')))
    expect(viewProps.actions.handOff).toHaveBeenCalledTimes(1)
})
