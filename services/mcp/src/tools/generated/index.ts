import type { ToolBase, ZodObjectAny } from '@/tools/types'

// AUTO-GENERATED — do not edit
import { GENERATED_TOOLS as cohorts } from './cohorts'
import { GENERATED_TOOLS as error_tracking } from './error_tracking'

export const GENERATED_TOOL_MAP: Record<string, () => ToolBase<ZodObjectAny>> = {
    ...cohorts,
    ...error_tracking,
}
