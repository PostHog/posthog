// AUTO-GENERATED — do not edit
import type { ToolBase, ZodObjectAny } from '@/tools/types'

import { GENERATED_TOOLS as actions } from './actions'
import { GENERATED_TOOLS as alerts } from './alerts'
import { GENERATED_TOOLS as annotations } from './annotations'
import { GENERATED_TOOLS as cdp_function_templates } from './cdp_function_templates'
import { GENERATED_TOOLS as cdp_functions } from './cdp_functions'
import { GENERATED_TOOLS as cohorts } from './cohorts'
import { GENERATED_TOOLS as conversations } from './conversations'
import { GENERATED_TOOLS as core } from './core'
import { GENERATED_TOOLS as customer_analytics } from './customer_analytics'
import { GENERATED_TOOLS as dashboards } from './dashboards'
import { GENERATED_TOOLS as data_warehouse } from './data_warehouse'
import { GENERATED_TOOLS as early_access_features } from './early_access_features'
import { GENERATED_TOOLS as endpoints } from './endpoints'
import { GENERATED_TOOLS as error_tracking } from './error_tracking'
import { GENERATED_TOOLS as evaluation_reports } from './evaluation_reports'
import { GENERATED_TOOLS as evaluations } from './evaluations'
import { GENERATED_TOOLS as experiments } from './experiments'
import { GENERATED_TOOLS as feature_flags } from './feature_flags'
import { GENERATED_TOOLS as integrations } from './integrations'
import { GENERATED_TOOLS as llm_analytics } from './llm_analytics'
import { GENERATED_TOOLS as logs } from './logs'
import { GENERATED_TOOLS as notebooks } from './notebooks'
import { GENERATED_TOOLS as persons } from './persons'
import { GENERATED_TOOLS as platform_features } from './platform_features'
import { GENERATED_TOOLS as product_analytics } from './product_analytics'
import { GENERATED_TOOLS as prompts } from './prompts'
import { GENERATED_TOOLS as proxyRecords } from './proxy-records'
import { GENERATED_TOOLS as queryWrappers } from './query-wrappers'
import { GENERATED_TOOLS as replay } from './replay'
import { GENERATED_TOOLS as sdk_doctor } from './sdk_doctor'
import { GENERATED_TOOLS as skills } from './skills'
import { GENERATED_TOOLS as surveys } from './surveys'
import { GENERATED_TOOLS as web_analytics } from './web_analytics'
import { GENERATED_TOOLS as workflows } from './workflows'

export const GENERATED_TOOL_MAP: Record<string, () => ToolBase<ZodObjectAny>> = {
    ...actions,
    ...alerts,
    ...annotations,
    ...cdp_function_templates,
    ...cdp_functions,
    ...cohorts,
    ...conversations,
    ...core,
    ...customer_analytics,
    ...dashboards,
    ...data_warehouse,
    ...early_access_features,
    ...endpoints,
    ...error_tracking,
    ...evaluation_reports,
    ...evaluations,
    ...experiments,
    ...feature_flags,
    ...integrations,
    ...llm_analytics,
    ...logs,
    ...notebooks,
    ...persons,
    ...platform_features,
    ...product_analytics,
    ...prompts,
    ...proxyRecords,
    ...queryWrappers,
    ...replay,
    ...sdk_doctor,
    ...skills,
    ...surveys,
    ...web_analytics,
    ...workflows,
}
