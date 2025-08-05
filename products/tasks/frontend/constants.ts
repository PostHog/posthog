import { TaskStatus, OriginProduct } from './types'

// Status display constants
export const STATUS_LABELS: Record<TaskStatus, string> = {
    [TaskStatus.BACKLOG]: 'Backlog',
    [TaskStatus.TODO]: 'To Do',
    [TaskStatus.IN_PROGRESS]: 'In Progress',
    [TaskStatus.TESTING]: 'Testing',
    [TaskStatus.DONE]: 'Done',
}

export const STATUS_COLORS: Record<TaskStatus, string> = {
    [TaskStatus.BACKLOG]: 'bg-stone-100 text-stone-800',
    [TaskStatus.TODO]: 'bg-blue-100 text-blue-800',
    [TaskStatus.IN_PROGRESS]: 'bg-amber-100 text-amber-800',
    [TaskStatus.TESTING]: 'bg-violet-100 text-violet-800',
    [TaskStatus.DONE]: 'bg-green-100 text-green-800',
}

// Origin product display constants
export const ORIGIN_PRODUCT_LABELS: Record<OriginProduct, string> = {
    [OriginProduct.ERROR_TRACKING]: 'Error Tracking',
    [OriginProduct.EVAL_CLUSTERS]: 'Eval Clusters',
    [OriginProduct.USER_CREATED]: 'User Created',
    [OriginProduct.SUPPORT_QUEUE]: 'Support Queue',
}

export const ORIGIN_PRODUCT_COLORS: Record<OriginProduct, string> = {
    [OriginProduct.ERROR_TRACKING]: 'bg-red-100 text-red-800',
    [OriginProduct.EVAL_CLUSTERS]: 'bg-sky-100 text-sky-800',
    [OriginProduct.USER_CREATED]: 'bg-emerald-100 text-emerald-800',
    [OriginProduct.SUPPORT_QUEUE]: 'bg-orange-100 text-orange-800',
}
