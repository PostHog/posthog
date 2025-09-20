import { OriginProduct } from './types'

// Stage display constants (now dynamic based on workflow stages)
export const STAGE_LABELS: Record<string, string> = {
    'backlog': 'Backlog',
    'todo': 'To Do',
    'in_progress': 'In Progress',
    'testing': 'Testing',
    'done': 'Done',
    'input': 'Input',
    'complete': 'Complete',
}

export const STAGE_COLORS: Record<string, string> = {
    'backlog': 'bg-stone-100 text-stone-800',
    'todo': 'bg-blue-100 text-blue-800',
    'in_progress': 'bg-amber-100 text-amber-800',
    'testing': 'bg-violet-100 text-violet-800',
    'done': 'bg-green-100 text-green-800',
    'input': 'bg-gray-100 text-gray-800',
    'complete': 'bg-green-100 text-green-800',
}

// Origin product display constants
export const ORIGIN_PRODUCT_LABELS: Record<OriginProduct, string> = {
    [OriginProduct.ERROR_TRACKING]: 'Error Tracking',
    [OriginProduct.EVAL_CLUSTERS]: 'Eval Clusters',
    [OriginProduct.USER_CREATED]: 'User Created',
    [OriginProduct.SUPPORT_QUEUE]: 'Support Queue',
    [OriginProduct.SESSION_SUMMARIES]: 'Session Summaries',
}

export const ORIGIN_PRODUCT_COLORS: Record<OriginProduct, string> = {
    [OriginProduct.ERROR_TRACKING]: 'bg-red-100 text-red-800',
    [OriginProduct.EVAL_CLUSTERS]: 'bg-sky-100 text-sky-800',
    [OriginProduct.USER_CREATED]: 'bg-emerald-100 text-emerald-800',
    [OriginProduct.SUPPORT_QUEUE]: 'bg-orange-100 text-orange-800',
    [OriginProduct.SESSION_SUMMARIES]: 'bg-purple-100 text-purple-800',
}
