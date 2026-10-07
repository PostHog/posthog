import { MakeLogicType, connect, kea, path, selectors } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { FeatureFlagsSet, featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { isObject } from 'lib/utils/guards'

import type { IntegrationConfigApi } from 'products/integrations/frontend/generated/api.schemas'

import type { IntegrationType } from '../../../../frontend/src/types'

export type FirstRunSender = Pick<IntegrationConfigApi, 'id' | 'display_name' | 'config'>

export interface firstRunSenderLogicValues {
    featureFlags: FeatureFlagsSet
    integrations: IntegrationType[] | null
    integrationsLoading: boolean
    firstRunEnabled: boolean
    firstRunSender: FirstRunSender | null
    firstRunSenderLoading: boolean
}

export interface firstRunSenderLogicMeta {
    __keaTypeGenInternalSelectorTypes: {
        firstRunEnabled: (featureFlags: FeatureFlagsSet) => boolean
        firstRunSender: (integrations: IntegrationType[] | null, firstRunEnabled: boolean) => FirstRunSender | null
        firstRunSenderLoading: (integrationsLoading: boolean, firstRunEnabled: boolean) => boolean
    }
}

export type firstRunSenderLogicType = MakeLogicType<
    firstRunSenderLogicValues,
    Record<string, never>,
    Record<string, any>,
    firstRunSenderLogicMeta
>

export const firstRunSenderLogic = kea<firstRunSenderLogicType>([
    path(['products', 'workflows', 'frontend', 'firstRun', 'firstRunSenderLogic']),
    connect({
        values: [featureFlagLogic, ['featureFlags'], integrationsLogic, ['integrations', 'integrationsLoading']],
    }),
    selectors({
        firstRunEnabled: [
            (s) => [s.featureFlags],
            (featureFlags: FeatureFlagsSet): boolean => !!featureFlags[FEATURE_FLAGS.WORKFLOWS_FIRST_RUN],
        ],
        firstRunSender: [
            (s) => [s.integrations, s.firstRunEnabled],
            (integrations: IntegrationType[] | null, firstRunEnabled: boolean): FirstRunSender | null =>
                firstRunEnabled
                    ? (integrations?.find(
                          (sender) =>
                              sender.kind === 'email' &&
                              isObject(sender.config) &&
                              sender.config.provider !== 'sandbox' &&
                              sender.config.verified === true
                      ) ?? null)
                    : null,
        ],
        firstRunSenderLoading: [
            (s) => [s.integrationsLoading, s.firstRunEnabled],
            (loading: boolean, firstRunEnabled: boolean): boolean => firstRunEnabled && loading,
        ],
    }),
])
