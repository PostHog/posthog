import { actions, afterMount, connect, kea, listeners, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'

import { lemonToast } from '@posthog/lemon-ui'

import { teamLogic } from 'scenes/teamLogic'

import {
    logsSamplingRulesList,
    logsSamplingRulesPartialUpdate,
    logsSamplingRulesReorderCreate,
} from 'products/logs/frontend/generated/api'
import { LogsSamplingRuleApi } from 'products/logs/frontend/generated/api.schemas'

import type { logsSamplingSectionLogicType } from './logsSamplingSectionLogicType'

export const logsSamplingSectionLogic = kea<logsSamplingSectionLogicType>([
    path(['products', 'logs', 'frontend', 'components', 'LogsSampling', 'logsSamplingSectionLogic']),

    connect({
        values: [teamLogic, ['currentTeamId']],
    }),

    actions({
        saveRulesOrder: (orderedIds: string[]) => ({ orderedIds }),
        saveRulesOrderFinished: true,
        setRuleEnabled: (ruleId: string, enabled: boolean) => ({ ruleId, enabled }),
        setRuleEnabledFinished: true,
    }),

    reducers({
        saveRulesOrderPending: [
            false,
            {
                saveRulesOrder: () => true,
                saveRulesOrderFinished: () => false,
            },
        ],
        ruleEnabledTogglePendingId: [
            null as string | null,
            {
                setRuleEnabled: (_, { ruleId }) => ruleId,
                setRuleEnabledFinished: () => null,
            },
        ],
    }),

    loaders(({ values }) => ({
        rules: [
            [] as LogsSamplingRuleApi[],
            {
                loadRules: async () => {
                    const projectId = String(values.currentTeamId)
                    const page = await logsSamplingRulesList(projectId)
                    return page.results
                },
            },
        ],
    })),

    listeners(({ actions, values }) => ({
        saveRulesOrder: async ({ orderedIds }) => {
            const projectId = values.currentTeamId
            if (projectId === null) {
                actions.saveRulesOrderFinished()
                return
            }
            try {
                await logsSamplingRulesReorderCreate(String(projectId), { ordered_ids: orderedIds })
                lemonToast.success('Evaluation order updated')
                await actions.loadRules()
            } catch (e: unknown) {
                const err = e as { detail?: string; message?: string }
                lemonToast.error(err?.detail ?? err?.message ?? 'Failed to update order')
                await actions.loadRules()
            } finally {
                actions.saveRulesOrderFinished()
            }
        },
        setRuleEnabled: async ({ ruleId, enabled }) => {
            const projectId = values.currentTeamId
            if (projectId === null) {
                actions.setRuleEnabledFinished()
                return
            }
            try {
                await logsSamplingRulesPartialUpdate(String(projectId), ruleId, { enabled })
                await actions.loadRules()
            } catch (e: unknown) {
                const err = e as { detail?: string; message?: string }
                lemonToast.error(err?.detail ?? err?.message ?? 'Failed to update rule')
                await actions.loadRules()
            } finally {
                actions.setRuleEnabledFinished()
            }
        },
    })),

    afterMount(({ actions }) => {
        actions.loadRules()
    }),
])
