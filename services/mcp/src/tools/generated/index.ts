// AUTO-GENERATED — do not edit
import type { ToolBase, ZodObjectAny } from '@/tools/types'

import { GENERATED_TOOLS as actions } from './actions'
import { GENERATED_TOOLS as agent_platform } from './agent_platform'
import { GENERATED_TOOLS as ai_observability } from './ai_observability'
import { GENERATED_TOOLS as alerts } from './alerts'
import { GENERATED_TOOLS as annotations } from './annotations'
import { GENERATED_TOOLS as batch_exports } from './batch_exports'
import { GENERATED_TOOLS as business_knowledge } from './business_knowledge'
import { GENERATED_TOOLS as cdp_function_templates } from './cdp_function_templates'
import { GENERATED_TOOLS as cdp_functions } from './cdp_functions'
import { GENERATED_TOOLS as cohorts } from './cohorts'
import { GENERATED_TOOLS as conversations } from './conversations'
import { GENERATED_TOOLS as core } from './core'
import { GENERATED_TOOLS as customer_analytics } from './customer_analytics'
import { GENERATED_TOOLS as dashboards } from './dashboards'
import { GENERATED_TOOLS as data_warehouse } from './data_warehouse'
import { GENERATED_TOOLS as docs } from './docs'
import { GENERATED_TOOLS as early_access_features } from './early_access_features'
import { GENERATED_TOOLS as email_templates } from './email_templates'
import { GENERATED_TOOLS as endpoints } from './endpoints'
import { GENERATED_TOOLS as engineering_analytics } from './engineering_analytics'
import { GENERATED_TOOLS as error_tracking } from './error_tracking'
import { GENERATED_TOOLS as error_tracking_alerts } from './error_tracking_alerts'
import { GENERATED_TOOLS as experiments } from './experiments'
import { GENERATED_TOOLS as feature_flags } from './feature_flags'
import { GENERATED_TOOLS as field_notes } from './field_notes'
import { GENERATED_TOOLS as health_issues } from './health_issues'
import { GENERATED_TOOLS as integrations } from './integrations'
import { GENERATED_TOOLS as logs } from './logs'
import { GENERATED_TOOLS as marketing_analytics } from './marketing_analytics'
import { GENERATED_TOOLS as mcp_analytics } from './mcp_analytics'
import { GENERATED_TOOLS as mcp_store } from './mcp_store'
import { GENERATED_TOOLS as metrics } from './metrics'
import { GENERATED_TOOLS as notebooks } from './notebooks'
import { GENERATED_TOOLS as persons } from './persons'
import { GENERATED_TOOLS as platform_features } from './platform_features'
import { GENERATED_TOOLS as product_analytics } from './product_analytics'
import { GENERATED_TOOLS as proxyRecords } from './proxy-records'
import { GENERATED_TOOLS as pulse } from './pulse'
import { GENERATED_TOOLS as queryWrappers } from './query-wrappers'
import { GENERATED_TOOLS as reminders } from './reminders'
import { GENERATED_TOOLS as replay } from './replay'
import { GENERATED_TOOLS as replay_vision } from './replay_vision'
import { GENERATED_TOOLS as signals } from './signals'
import { GENERATED_TOOLS as skills } from './skills'
import { GENERATED_TOOLS as subscriptions } from './subscriptions'
import { GENERATED_TOOLS as surveys } from './surveys'
import { GENERATED_TOOLS as tasks } from './tasks'
import { GENERATED_TOOLS as tracing } from './tracing'
import { GENERATED_TOOLS as user_interviews } from './user_interviews'
import { GENERATED_TOOLS as visual_review } from './visual_review'
import { GENERATED_TOOLS as warehouse_sources } from './warehouse_sources'
import { GENERATED_TOOLS as web_analytics } from './web_analytics'
import { GENERATED_TOOLS as workflows } from './workflows'

export const GENERATED_TOOL_MAP: Record<string, () => ToolBase<ZodObjectAny>> = {
    ...actions,
    ...agent_platform,
    ...ai_observability,
    ...alerts,
    ...annotations,
    ...batch_exports,
    ...business_knowledge,
    ...cdp_function_templates,
    ...cdp_functions,
    ...cohorts,
    ...conversations,
    ...core,
    ...customer_analytics,
    ...dashboards,
    ...data_warehouse,
    ...docs,
    ...early_access_features,
    ...email_templates,
    ...endpoints,
    ...engineering_analytics,
    ...error_tracking,
    ...error_tracking_alerts,
    ...experiments,
    ...feature_flags,
    ...field_notes,
    ...health_issues,
    ...integrations,
    ...logs,
    ...marketing_analytics,
    ...mcp_analytics,
    ...mcp_store,
    ...metrics,
    ...notebooks,
    ...persons,
    ...platform_features,
    ...product_analytics,
    ...proxyRecords,
    ...pulse,
    ...queryWrappers,
    ...reminders,
    ...replay,
    ...replay_vision,
    ...signals,
    ...skills,
    ...subscriptions,
    ...surveys,
    ...tasks,
    ...tracing,
    ...user_interviews,
    ...visual_review,
    ...warehouse_sources,
    ...web_analytics,
    ...workflows,
}
