// AUTO-GENERATED — do not edit

import hooks0 from '@/tools/dataWarehouse/viewGetHooks'
import hooks1 from '@/tools/engineeringAnalytics/redactFailureLogsHooks'
import hooks2 from '@/tools/experiments/createExperimentHooks'
import hooks3 from '@/tools/experiments/getExperimentHooks'
import hooks4 from '@/tools/experiments/listExperimentsHooks'
import hooks5 from '@/tools/experiments/updateExperimentHooks'
import hooks6 from '@/tools/featureFlags/conditionIdHooks'
import hooks7 from '@/tools/featureFlags/updateFeatureFlagHooks'
import hooks8 from '@/tools/logs/groupByRedactionHooks'
import hooks9 from '@/tools/logs/redactCredentialsHooks'
import hooks10 from '@/tools/replay/sessionRecordingGetHooks'
import hooks11 from '@/tools/signals/inboxMySettingsHooks'
import type { ToolHooks } from '@/tools/tool-hooks'
import hooks12 from '@/tools/workflows/broadcastLinkHooks'
import hooks13 from '@/tools/workflows/dataSuggestionCreateHooks'

export const GENERATED_TOOL_HOOKS: Record<string, ToolHooks<any>> = {
    'dataWarehouse/viewGetHooks': hooks0,
    'engineeringAnalytics/redactFailureLogsHooks': hooks1,
    'experiments/createExperimentHooks': hooks2,
    'experiments/getExperimentHooks': hooks3,
    'experiments/listExperimentsHooks': hooks4,
    'experiments/updateExperimentHooks': hooks5,
    'featureFlags/conditionIdHooks': hooks6,
    'featureFlags/updateFeatureFlagHooks': hooks7,
    'logs/groupByRedactionHooks': hooks8,
    'logs/redactCredentialsHooks': hooks9,
    'replay/sessionRecordingGetHooks': hooks10,
    'signals/inboxMySettingsHooks': hooks11,
    'workflows/broadcastLinkHooks': hooks12,
    'workflows/dataSuggestionCreateHooks': hooks13,
}
