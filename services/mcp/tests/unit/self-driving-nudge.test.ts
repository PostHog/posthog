import { describe, expect, it, vi } from 'vitest'

import type { SelfDrivingStatus } from '@/api/client'
import { maybeGetSelfDrivingNudge, selectSelfDrivingGap } from '@/lib/self-driving-nudge'
import type { Context } from '@/tools/types'

const FLAG_ON = { 'mcp-error-tracking-self-driving-nudge': true }
const ISSUE_DETAIL = { id: 'issue-1', name: 'TypeError: x is not a function' }

function makeStatus(overrides: Partial<SelfDrivingStatus> = {}): SelfDrivingStatus {
    return { autostart_enabled: true, github_connected: true, quota_blocked: false, ...overrides }
}

function makeContext(status: SelfDrivingStatus | undefined, fetchError = false): Context {
    return {
        stateManager: {
            getProjectId: vi.fn().mockResolvedValue('1'),
            getOrFetchSelfDrivingStatus: fetchError
                ? vi.fn().mockRejectedValue(new Error('unreachable'))
                : vi.fn().mockResolvedValue(status),
        },
        api: { getProjectBaseUrl: () => 'https://us.posthog.com/project/1' },
    } as unknown as Context
}

describe('self-driving nudge', () => {
    describe('selectSelfDrivingGap', () => {
        it.each([
            ['fully set up', makeStatus(), undefined],
            ['no GitHub connection', makeStatus({ github_connected: false }), 'github_missing'],
            ['autostart switched off', makeStatus({ autostart_enabled: false }), 'autostart_off'],
            // GitHub first: flipping the switch does nothing while no repo is connected.
            ['both gaps', makeStatus({ github_connected: false, autostart_enabled: false }), 'github_missing'],
            ['quota paused', makeStatus({ quota_blocked: true, github_connected: false }), undefined],
        ])('%s', (_label, status, expected) => {
            expect(selectSelfDrivingGap(status)).toBe(expected)
        })
    })

    describe('maybeGetSelfDrivingNudge', () => {
        it.each([
            ['query-error-tracking-issue', ISSUE_DETAIL],
            ['query-error-tracking-issue-events', { results: [{ uuid: 'event-1' }] }],
            ['query-error-tracking-issues-list', { results: [ISSUE_DETAIL] }],
        ])('names the gap and the settings link for %s', async (toolName, handlerResult) => {
            const nudge = await maybeGetSelfDrivingNudge(makeContext(makeStatus({ github_connected: false })), {
                toolName,
                handlerResult,
                featureFlags: FLAG_ON,
            })
            expect(nudge?.gap).toBe('github_missing')
            expect(nudge?.note).toContain('https://us.posthog.com/project/1/inbox?utm_source=mcp')
        })

        it.each([
            ['the flag off', { 'mcp-error-tracking-self-driving-nudge': false }],
            ['flags unevaluated', undefined],
        ])('returns undefined with %s', async (_label, featureFlags) => {
            const context = makeContext(makeStatus({ github_connected: false }))
            await expect(
                maybeGetSelfDrivingNudge(context, {
                    toolName: 'query-error-tracking-issue',
                    handlerResult: ISSUE_DETAIL,
                    featureFlags,
                })
            ).resolves.toBeUndefined()
            // The gate must short-circuit before any status read: this fires on every tool call.
            expect(context.stateManager.getOrFetchSelfDrivingStatus).not.toHaveBeenCalled()
        })

        it.each([
            ['an empty issue list', 'query-error-tracking-issues-list', { results: [] }],
            ['issue detail missing its id', 'query-error-tracking-issue', { name: 'orphan' }],
            ['a tool outside error tracking', 'query-logs', { results: [{ id: 'log-1' }] }],
        ])('returns undefined for %s', async (_label, toolName, handlerResult) => {
            await expect(
                maybeGetSelfDrivingNudge(makeContext(makeStatus({ github_connected: false })), {
                    toolName,
                    handlerResult,
                    featureFlags: FLAG_ON,
                })
            ).resolves.toBeUndefined()
        })

        it.each([
            ['the status read fails', makeContext(undefined, true)],
            ['the status is unavailable', makeContext(undefined)],
        ])('fails closed when %s', async (_label, context) => {
            await expect(
                maybeGetSelfDrivingNudge(context, {
                    toolName: 'query-error-tracking-issue',
                    handlerResult: ISSUE_DETAIL,
                    featureFlags: FLAG_ON,
                })
            ).resolves.toBeUndefined()
        })
    })
})
