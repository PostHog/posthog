import { actions, afterMount, connect, kea, key, listeners, path, props, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'

import { lemonToast } from '@posthog/lemon-ui'

import { Scene } from 'scenes/sceneTypes'
import { teamLogic } from 'scenes/teamLogic'

import { Breadcrumb } from '~/types'

import {
    buildSamplingFormDefaults,
    logsSamplingFormLogic,
} from 'products/logs/frontend/components/LogsSampling/logsSamplingFormLogic'
import { fetchSamplingRuleDropTotalsLast24h } from 'products/logs/frontend/components/LogsSampling/samplingRuleDropImpact'
import { logsSamplingRulesDestroy, logsSamplingRulesRetrieve } from 'products/logs/frontend/generated/api'
import { LogsSamplingRuleApi } from 'products/logs/frontend/generated/api.schemas'
import { logsDropRulesSettingsUrl } from 'products/logs/frontend/logsDropRulesSettingsUrl'

import type { logsSamplingDetailSceneLogicType } from './logsSamplingDetailSceneLogicType'

export interface LogsSamplingDetailSceneLogicProps {
    id: string
}

export const logsSamplingDetailSceneLogic = kea<logsSamplingDetailSceneLogicType>([
    path((key) => [
        'products',
        'logs',
        'frontend',
        'scenes',
        'LogsSamplingDetailScene',
        'logsSamplingDetailSceneLogic',
        key,
    ]),
    props({} as LogsSamplingDetailSceneLogicProps),
    key((props) => props.id),

    connect((props: LogsSamplingDetailSceneLogicProps) => ({
        values: [teamLogic, ['currentTeamId']],
        actions: [logsSamplingFormLogic({ rule: { id: props.id } as LogsSamplingRuleApi }), ['resetSamplingForm']],
    })),

    actions({
        deleteRule: true,
    }),

    loaders(({ values, props }) => ({
        rule: [
            null as LogsSamplingRuleApi | null,
            {
                loadRule: async () => logsSamplingRulesRetrieve(String(values.currentTeamId), props.id),
            },
        ],
        ruleDropImpact24h: [
            null as number | null,
            {
                loadRuleDropImpact24h: async (_, breakpoint) => {
                    await breakpoint(1)
                    const map = await fetchSamplingRuleDropTotalsLast24h([props.id])
                    return map[props.id] ?? 0
                },
            },
        ],
    })),

    selectors({
        breadcrumbs: [
            () => [],
            (): Breadcrumb[] => [
                {
                    key: Scene.Logs,
                    name: 'Logs',
                    path: logsDropRulesSettingsUrl(),
                    iconType: 'logs',
                },
                { key: Scene.LogsSamplingDetail, name: 'Drop rule', iconType: 'logs' },
            ],
        ],
    }),

    listeners(({ actions, values, props }) => ({
        loadRuleSuccess: () => {
            if (values.rule) {
                actions.resetSamplingForm(buildSamplingFormDefaults(values.rule))
            }
            actions.loadRuleDropImpact24h(undefined)
        },
        deleteRule: async () => {
            try {
                await logsSamplingRulesDestroy(String(values.currentTeamId), props.id)
                lemonToast.success('Rule deleted')
                router.actions.push(logsDropRulesSettingsUrl())
            } catch (e: any) {
                lemonToast.error(e?.detail ?? e?.message ?? 'Failed to delete')
            }
        },
    })),

    afterMount(({ actions }) => {
        actions.loadRule()
    }),
])
