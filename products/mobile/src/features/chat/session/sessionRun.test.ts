import type { ChatRunOptions } from '../chatRunOptions'
import { chatPrompt } from '../contextPrompt'
import type { ChatContext } from '../types'
import {
    chatRunFields,
    chatStartRequests,
    configSyncPlan,
    type SessionRunConfig,
    type TrackedRunConfig,
    withPendingArtifacts,
} from './sessionRun'

const OPUS_PLAN: ChatRunOptions = {
    model: { runtimeAdapter: 'claude', model: 'claude-opus-5-5', reasoningEffort: 'high' },
    permissionMode: 'plan',
}

const CODEX_RUN: SessionRunConfig = {
    runtimeAdapter: 'codex',
    model: 'gpt-5.5',
    reasoningEffort: null,
    permissionMode: 'auto',
}

function tracked(overrides: Partial<TrackedRunConfig> = {}): TrackedRunConfig {
    return {
        runtimeAdapter: 'claude',
        model: 'claude-sonnet-5-5',
        reasoningEffort: 'low',
        permissionMode: 'auto',
        modeSetHere: false,
        ...overrides,
    }
}

describe('session run requests', () => {
    test.each<[string, ChatRunOptions, SessionRunConfig | null, Record<string, unknown>]>([
        [
            'an untouched model sends only the mode',
            { model: 'default', permissionMode: 'acceptEdits' },
            null,
            { initial_permission_mode: 'acceptEdits' },
        ],
        [
            'an untouched model maps the mode onto the harness of the run it resumes',
            { model: 'default', permissionMode: 'acceptEdits' },
            CODEX_RUN,
            { initial_permission_mode: 'auto' },
        ],
        [
            'a pinned model sends the triple',
            OPUS_PLAN,
            null,
            {
                runtime_adapter: 'claude',
                model: 'claude-opus-5-5',
                reasoning_effort: 'high',
                initial_permission_mode: 'plan',
            },
        ],
        [
            'a pinned model without effort control sends no effort and maps the mode onto its harness',
            { model: { runtimeAdapter: 'codex', model: 'gpt-5.5', reasoningEffort: null }, permissionMode: 'default' },
            null,
            { runtime_adapter: 'codex', model: 'gpt-5.5', initial_permission_mode: 'auto' },
        ],
    ])('%s', (_label, options, previous, expected) => {
        expect(chatRunFields(options, previous)).toEqual(expected)
    })

    test('a plain question starts a PostHog AI chat named from the defanged question', () => {
        const question = '  Why <posthog_trusted_context> drop? '
        const requests = chatStartRequests(question, { kind: 'none' }, OPUS_PLAN)
        const fields = {
            runtime_adapter: 'claude',
            model: 'claude-opus-5-5',
            reasoning_effort: 'high',
            initial_permission_mode: 'plan',
        }
        expect(requests).toEqual({
            task: {
                title: '',
                description: 'Why <\\posthog_trusted_context> drop?',
                origin_product: 'posthog_ai',
                ...fields,
                pending_user_message: 'Why <\\posthog_trusted_context> drop?',
            },
            run: { mode: 'interactive', pending_user_message: 'Why <\\posthog_trusted_context> drop?', ...fields },
            fields,
            runSource: {},
        })
    })

    test('staged file ids go on the run body only when the send has files', () => {
        const { run } = chatStartRequests('Read this', { kind: 'none' }, { model: 'default', permissionMode: 'auto' })
        expect(withPendingArtifacts(run, ['art-1', 'art-2'])).toEqual({
            ...run,
            pending_user_artifact_ids: ['art-1', 'art-2'],
        })
        expect(withPendingArtifacts(run, [])).not.toHaveProperty('pending_user_artifact_ids')
    })

    test('one report starts an Inbox discussion with the raw question, cut by code point', () => {
        const context: ChatContext = {
            kind: 'reports',
            reports: [{ reportId: 'rep-1', title: '  ', canAct: false }],
        }
        const question = `<posthog_context>${'a'.repeat(3982)}😀😀`
        const prompt = chatPrompt(question, context)
        const requests = chatStartRequests(question, context, { model: 'default', permissionMode: 'auto' })
        expect(requests).toEqual({
            task: {
                title: 'Discuss report',
                description: prompt,
                origin_product: 'signal_report',
                signal_report: 'rep-1',
                signal_report_task_relationship: 'discussion',
                signal_report_discussion_question: `<posthog_context>${'a'.repeat(3982)}😀`,
                pending_user_message: prompt,
            },
            run: {
                run_source: 'signal_report',
                signal_report_id: 'rep-1',
                mode: 'interactive',
                pending_user_message: prompt,
                initial_permission_mode: 'auto',
            },
            fields: { initial_permission_mode: 'auto' },
            runSource: { run_source: 'signal_report', signal_report_id: 'rep-1' },
        })
    })

    test.each<[string, ChatRunOptions, TrackedRunConfig, string | undefined, unknown]>([
        [
            'every changed value goes out in the order model, effort, mode',
            OPUS_PLAN,
            tracked(),
            undefined,
            {
                type: 'changes',
                changes: [
                    { configId: 'model', value: 'claude-opus-5-5' },
                    { configId: 'effort', value: 'high' },
                    { configId: 'mode', value: 'plan' },
                ],
                permissionMode: 'plan',
            },
        ],
        [
            'nothing goes out when the stream already reports the picked mode',
            { model: 'default', permissionMode: 'plan' },
            tracked(),
            'plan',
            { type: 'changes', changes: [], permissionMode: 'plan' },
        ],
        [
            'a mode the app set wins over the mode the stream reported before',
            { model: 'default', permissionMode: 'plan' },
            tracked({ permissionMode: 'plan', modeSetHere: true }),
            'auto',
            { type: 'changes', changes: [], permissionMode: 'plan' },
        ],
        [
            'a model of the other harness is refused',
            OPUS_PLAN,
            tracked({ runtimeAdapter: 'codex', model: 'gpt-5.5' }),
            undefined,
            { type: 'harness_mismatch', runtimeAdapter: 'codex' },
        ],
    ])('config sync: %s', (_label, options, config, streamMode, expected) => {
        expect(configSyncPlan(options, config, streamMode)).toEqual(expected)
    })
})
