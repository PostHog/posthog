import type { ToolBase, ZodObjectAny } from '@/tools/types'

// AUTO-GENERATED — do not edit
import { GENERATED_TOOLS as cohorts } from './cohorts'
import { GENERATED_TOOLS as error_tracking } from './error_tracking'
import { GENERATED_TOOLS as hog_function_templates } from './hog_function_templates'
import { GENERATED_TOOLS as workflows } from './workflows'

export const GENERATED_TOOL_MAP: Record<string, () => ToolBase<ZodObjectAny>> = {
    ...cohorts,
    ...hog_function_templates,
    ...error_tracking,
    ...workflows,
}
