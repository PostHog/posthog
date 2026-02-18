// AUTO-GENERATED — do not edit
import type { ToolBase, ZodObjectAny } from '@/tools/types'

import { GENERATED_TOOLS as actions } from './actions'
import { GENERATED_TOOLS as error_tracking } from './error_tracking'

export const GENERATED_TOOL_MAP: Record<string, () => ToolBase<ZodObjectAny>> = {
    ...actions,
    ...error_tracking,
}
