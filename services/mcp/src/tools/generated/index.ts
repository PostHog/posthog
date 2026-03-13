import type { ToolBase, ZodObjectAny } from '@/tools/types'

import { GENERATED_TOOLS as actions } from './actions'
// AUTO-GENERATED — do not edit
import { GENERATED_TOOLS as activity_logs } from './activity_logs'
import { GENERATED_TOOLS as cdp_function_templates } from './cdp_function_templates'
import { GENERATED_TOOLS as cdp_functions } from './cdp_functions'
import { GENERATED_TOOLS as cohorts } from './cohorts'
import { GENERATED_TOOLS as error_tracking } from './error_tracking'
import { GENERATED_TOOLS as prompts } from './prompts'
import { GENERATED_TOOLS as workflows } from './workflows'

export const GENERATED_TOOL_MAP: Record<string, () => ToolBase<ZodObjectAny>> = {
    ...activity_logs,
    ...actions,
    ...cdp_function_templates,
    ...cdp_functions,
    ...cohorts,
    ...error_tracking,
    ...prompts,
    ...workflows,
}
