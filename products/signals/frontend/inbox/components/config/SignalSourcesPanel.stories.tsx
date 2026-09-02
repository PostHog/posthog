import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import type { Meta, StoryObj } from '@storybook/react'
import { useEffect } from 'react'

import { teamLogic } from 'scenes/teamLogic'

import { useStorybookMocks } from '~/mocks/browser'

import { ERROR_TRACKING_SIGNAL_SOURCE_TYPES } from '../../signalSourcesLogic'
import { SignalSourceConfig, SignalSourceProduct, SignalSourceType } from '../../types'
import { SignalSourcesPanel } from './SignalSourcesPanel'

// Every axis the signal sources dialog renders from: which sources are armed
// (SignalSourceConfig rows), which PostHog tools are on (team opt-ins), and which usage
// events exist (event definitions). Each control drives one of the three mocks.
interface PanelState {
    // Armed sources
    errorTrackingArmed: boolean
    /** Replay Vision arms per scanner, so this stands in for "the first scanner emits signals". */
    replayVisionArmed: boolean
    sessionReplayArmed: boolean
    supportArmed: boolean
    aiObservabilityArmed: boolean
    productAnalyticsArmed: boolean
    healthChecksArmed: boolean
    // Tool enablement (team opt-ins)
    exceptionAutocaptureOn: boolean
    sessionRecordingOn: boolean
    conversationsOn: boolean
    // Usage (event definitions present)
    hasExceptionEvents: boolean
    hasAiEvents: boolean
    hasAnalyticsEvents: boolean
    eventDefinitionsUnavailable: boolean
}

function sourceConfig(
    sourceProduct: SignalSourceProduct,
    sourceType: SignalSourceType,
    enabled: boolean
): SignalSourceConfig {
    return {
        id: `${sourceProduct}_${sourceType}`,
        source_product: sourceProduct,
        source_type: sourceType,
        enabled,
        config: {},
        created_at: '2024-03-20T00:00:00Z',
        updated_at: '2024-03-20T00:00:00Z',
        status: null,
    }
}

function sourceConfigsFor(state: PanelState): SignalSourceConfig[] {
    return [
        ...ERROR_TRACKING_SIGNAL_SOURCE_TYPES.map((sourceType) =>
            sourceConfig(SignalSourceProduct.ErrorTracking, sourceType, state.errorTrackingArmed)
        ),
        sourceConfig(
            SignalSourceProduct.SessionReplay,
            SignalSourceType.SessionAnalysisCluster,
            state.sessionReplayArmed
        ),
        sourceConfig(SignalSourceProduct.Conversations, SignalSourceType.Ticket, state.supportArmed),
        sourceConfig(SignalSourceProduct.LlmAnalytics, SignalSourceType.EvaluationReport, state.aiObservabilityArmed),
        sourceConfig(SignalSourceProduct.Analytics, SignalSourceType.AnomalyInvestigation, state.productAnalyticsArmed),
        sourceConfig(SignalSourceProduct.HealthChecks, SignalSourceType.HealthIssue, state.healthChecksArmed),
    ]
}

/** Two scanners so the roster's per-scanner list has both an on and an off row to render. */
function scannersFor(state: PanelState): Record<string, unknown>[] {
    return [
        {
            id: 'scanner-checkout',
            name: 'Checkout confusion',
            description: 'Watches for hesitation and repeated attempts on the checkout step.',
            scanner_type: 'monitor',
            enabled: true,
            emits_signals: state.replayVisionArmed,
        },
        {
            id: 'scanner-onboarding',
            name: 'Onboarding drop-off',
            description: 'Sorts abandoned onboarding sessions into reasons.',
            scanner_type: 'classifier',
            enabled: true,
            emits_signals: false,
        },
    ]
}

function eventDefinitionsFor(state: PanelState): { name: string; last_seen_at: string }[] {
    const names = [
        ...(state.hasExceptionEvents ? ['$exception'] : []),
        ...(state.hasAiEvents ? ['$ai_generation', '$ai_trace'] : []),
        ...(state.hasAnalyticsEvents ? ['$pageview', '$autocapture'] : []),
    ]
    return names.map((name) => ({ name, last_seen_at: new Date().toISOString() }))
}

function PanelHarness(state: PanelState): JSX.Element {
    useStorybookMocks({
        get: {
            '/api/environments/:team_id/': () => [
                200,
                {
                    ...MOCK_DEFAULT_TEAM,
                    autocapture_exceptions_opt_in: state.exceptionAutocaptureOn,
                    session_recording_opt_in: state.sessionRecordingOn,
                    conversations_enabled: state.conversationsOn,
                },
            ],
            '/api/projects/:team_id/signals/source_configs/': () => [200, { results: sourceConfigsFor(state) }],
            '/api/projects/:team_id/vision/scanners/': () => {
                const results = scannersFor(state)
                return [200, { count: results.length, next: null, previous: null, results }]
            },
            '/api/projects/:team_id/event_definitions/': () =>
                state.eventDefinitionsUnavailable
                    ? [500, { detail: "Couldn't check recent data." }]
                    : [
                          200,
                          {
                              count: eventDefinitionsFor(state).length,
                              next: null,
                              previous: null,
                              results: eventDefinitionsFor(state),
                          },
                      ],
            '/api/environments/:team_id/external_data_sources/': () => [
                200,
                { count: 0, next: null, previous: null, results: [] },
            ],
        },
    })

    // The panel loads on mount and the team is cached app-wide, so a control change has to
    // both remount the panel (the `key`) and refetch the team against the updated mock.
    const stateKey = JSON.stringify(state)
    const { loadCurrentTeam } = teamLogic.actions
    useEffect(() => {
        loadCurrentTeam()
    }, [stateKey, loadCurrentTeam])

    return (
        <div className="w-[760px] p-6 bg-surface-primary border rounded">
            <SignalSourcesPanel key={stateKey} />
        </div>
    )
}

const meta: Meta<typeof PanelHarness> = {
    title: 'Scenes-App/Inbox/SignalSourcesPanel',
    component: PanelHarness,
    parameters: {
        layout: 'centered',
        viewMode: 'story',
        mockDate: '2024-03-20',
    },
    args: {
        errorTrackingArmed: true,
        replayVisionArmed: true,
        sessionReplayArmed: true,
        supportArmed: false,
        aiObservabilityArmed: false,
        productAnalyticsArmed: false,
        healthChecksArmed: true,
        exceptionAutocaptureOn: true,
        sessionRecordingOn: true,
        conversationsOn: false,
        hasExceptionEvents: true,
        hasAiEvents: false,
        hasAnalyticsEvents: true,
        eventDefinitionsUnavailable: false,
    },
}
export default meta

type Story = StoryObj<typeof PanelHarness>

/** Flip any control: armed sources, tool opt-ins, and which usage events exist. */
export const Playground: Story = {}

/** Sources armed while every tool is off: each PostHog card warns and offers "Turn it on". */
export const ArmedButToolsOff: Story = {
    args: {
        errorTrackingArmed: true,
        replayVisionArmed: true,
        sessionReplayArmed: true,
        supportArmed: true,
        exceptionAutocaptureOn: false,
        sessionRecordingOn: false,
        conversationsOn: false,
        hasExceptionEvents: false,
        hasAiEvents: false,
        hasAnalyticsEvents: false,
    },
}

/** Nothing armed and every tool off: switches are disabled with the turn-on-the-tool reason. */
export const ArmingBlocked: Story = {
    args: {
        errorTrackingArmed: false,
        replayVisionArmed: false,
        sessionReplayArmed: false,
        supportArmed: false,
        aiObservabilityArmed: false,
        productAnalyticsArmed: false,
        healthChecksArmed: false,
        exceptionAutocaptureOn: false,
        sessionRecordingOn: false,
        conversationsOn: false,
        hasExceptionEvents: false,
        hasAiEvents: false,
        hasAnalyticsEvents: false,
    },
}

/** Every tool on and every source armed, with data flowing everywhere it can be measured. */
export const EverythingHealthy: Story = {
    args: {
        errorTrackingArmed: true,
        replayVisionArmed: true,
        sessionReplayArmed: true,
        supportArmed: true,
        aiObservabilityArmed: true,
        productAnalyticsArmed: true,
        healthChecksArmed: true,
        exceptionAutocaptureOn: true,
        sessionRecordingOn: true,
        conversationsOn: true,
        hasExceptionEvents: true,
        hasAiEvents: true,
        hasAnalyticsEvents: true,
    },
}

/** Tools on but no recent events show the setup link. */
export const ToolsOnNoRecentData: Story = {
    args: {
        errorTrackingArmed: true,
        replayVisionArmed: true,
        sessionReplayArmed: true,
        supportArmed: true,
        aiObservabilityArmed: true,
        productAnalyticsArmed: true,
        exceptionAutocaptureOn: true,
        sessionRecordingOn: true,
        conversationsOn: true,
        hasExceptionEvents: false,
        hasAiEvents: false,
        hasAnalyticsEvents: false,
    },
}

/** A failed event-definition check shows the retry action without marking tools as off. */
export const EventDefinitionsUnavailable: Story = {
    args: {
        errorTrackingArmed: true,
        aiObservabilityArmed: true,
        productAnalyticsArmed: true,
        exceptionAutocaptureOn: false,
        eventDefinitionsUnavailable: true,
    },
}

/** Exceptions flow from a server SDK while the autocapture opt-in is off: still counts as on. */
export const ServerSideExceptionsOnly: Story = {
    args: {
        errorTrackingArmed: true,
        exceptionAutocaptureOn: false,
        hasExceptionEvents: true,
    },
}
