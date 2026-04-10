// AUTO-GENERATED — do not edit
import type { ToolBase, ZodObjectAny } from '@/tools/types'

import { GENERATED_TOOLS as actions } from './actions'
import { GENERATED_TOOLS as activity_logs } from './activity_logs'
import { GENERATED_TOOLS as alerts } from './alerts'
import { GENERATED_TOOLS as annotations } from './annotations'
import { GENERATED_TOOLS as cdp_function_templates } from './cdp_function_templates'
import { GENERATED_TOOLS as cdp_functions } from './cdp_functions'
import { GENERATED_TOOLS as cohorts } from './cohorts'
import { GENERATED_TOOLS as dashboards } from './dashboards'
import { GENERATED_TOOLS as data_warehouse } from './data_warehouse'
import { GENERATED_TOOLS as early_access_features } from './early_access_features'
import { GENERATED_TOOLS as endpoints } from './endpoints'
import { GENERATED_TOOLS as error_tracking } from './error_tracking'
import { GENERATED_TOOLS as feature_flags } from './feature_flags'
import { GENERATED_TOOLS as integrations } from './integrations'
import { GENERATED_TOOLS as llm_analytics } from './llm_analytics'
import { GENERATED_TOOLS as logs } from './logs'
import { GENERATED_TOOLS as notebooks } from './notebooks'
import { GENERATED_TOOLS as persons } from './persons'
import { GENERATED_TOOLS as platform_features } from './platform_features'
import { GENERATED_TOOLS as prompts } from './prompts'
import { GENERATED_TOOLS as proxyRecords } from './proxy-records'
import { GENERATED_TOOLS as queryWrappers } from './query-wrappers'
import { GENERATED_TOOLS as surveys } from './surveys'
import { GENERATED_TOOLS as workflows } from './workflows'

export const GENERATED_TOOL_MAP: Record<string, () => ToolBase<ZodObjectAny>> = {
    ...actions,
    ...activity_logs,
    ...alerts,
    ...annotations,
    ...cdp_function_templates,
    ...cdp_functions,
    ...cohorts,
    ...dashboards,
    ...data_warehouse,
    ...early_access_features,
    ...endpoints,
    ...error_tracking,
    ...feature_flags,
    ...integrations,
    ...llm_analytics,
    ...logs,
    ...notebooks,
    ...persons,
    ...platform_features,
    ...prompts,
    ...proxyRecords,
    ...queryWrappers,
    ...surveys,
    ...workflows,
}
