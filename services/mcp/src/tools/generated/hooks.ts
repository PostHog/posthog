// AUTO-GENERATED — do not edit

import hooks0 from '@/tools/dataWarehouse/viewGetHooks'
import hooks1 from '@/tools/engineeringAnalytics/redactFailureLogsHooks'
import hooks2 from '@/tools/experiments/createExperimentHooks'
import hooks3 from '@/tools/experiments/getExperimentHooks'
import hooks4 from '@/tools/experiments/listExperimentsHooks'
import hooks5 from '@/tools/experiments/updateExperimentHooks'
import hooks6 from '@/tools/featureFlags/conditionIdHooks'
import hooks7 from '@/tools/featureFlags/createFeatureFlagHooks'
import hooks8 from '@/tools/featureFlags/updateFeatureFlagHooks'
import hooks9 from '@/tools/groups/findGroupHooks'
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
    'experiments/listExperimentsHooks': hooks4,
    'experiments/updateExperimentHooks': hooks5,
    'featureFlags/conditionIdHooks': hooks6,
    'featureFlags/createFeatureFlagHooks': hooks7,
    'featureFlags/updateFeatureFlagHooks': hooks8,
    'groups/findGroupHooks': hooks9,
    'logs/groupByRedactionHooks': hooks10,
    'logs/redactCredentialsHooks': hooks11,
    'replay/sessionRecordingGetHooks': hooks12,
    'signals/inboxMySettingsHooks': hooks13,
    'workflows/broadcastLinkHooks': hooks14,
    'workflows/dataSuggestionCreateHooks': hooks15,
    'workflows/testSenderNoteHooks': hooks16,
}
