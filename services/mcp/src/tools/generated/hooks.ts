// AUTO-GENERATED — do not edit

import hooks0 from '@/tools/dataWarehouse/viewGetHooks'
import hooks1 from '@/tools/engineeringAnalytics/redactFailureLogsHooks'
import hooks2 from '@/tools/experiments/createExperimentHooks'
import hooks3 from '@/tools/experiments/getExperimentHooks'
import hooks4 from '@/tools/experiments/launchExperimentHooks'
import hooks5 from '@/tools/experiments/listExperimentsHooks'
import hooks6 from '@/tools/experiments/updateExperimentHooks'
import hooks7 from '@/tools/featureFlags/conditionIdHooks'
import hooks8 from '@/tools/featureFlags/createFeatureFlagHooks'
import hooks9 from '@/tools/featureFlags/updateFeatureFlagHooks'
import hooks10 from '@/tools/logs/groupByRedactionHooks'
import hooks11 from '@/tools/logs/redactCredentialsHooks'
import hooks12 from '@/tools/replay/sessionRecordingGetHooks'
import hooks13 from '@/tools/signals/inboxMySettingsHooks'
import type { ToolHooks } from '@/tools/tool-hooks'
import hooks14 from '@/tools/workflows/broadcastLinkHooks'
import hooks15 from '@/tools/workflows/dataSuggestionCreateHooks'
import hooks16 from '@/tools/workflows/testSenderNoteHooks'

export const GENERATED_TOOL_HOOKS: Record<string, ToolHooks<any>> = {
    'dataWarehouse/viewGetHooks': hooks0,
    'engineeringAnalytics/redactFailureLogsHooks': hooks1,
    'experiments/createExperimentHooks': hooks2,
    'experiments/getExperimentHooks': hooks3,
    'experiments/launchExperimentHooks': hooks4,
    'experiments/listExperimentsHooks': hooks5,
    'experiments/updateExperimentHooks': hooks6,
    'featureFlags/conditionIdHooks': hooks7,
    'featureFlags/createFeatureFlagHooks': hooks8,
    'featureFlags/updateFeatureFlagHooks': hooks9,
    'logs/groupByRedactionHooks': hooks10,
    'logs/redactCredentialsHooks': hooks11,
    'replay/sessionRecordingGetHooks': hooks12,
    'signals/inboxMySettingsHooks': hooks13,
    'workflows/broadcastLinkHooks': hooks14,
    'workflows/dataSuggestionCreateHooks': hooks15,
    'workflows/testSenderNoteHooks': hooks16,
}
