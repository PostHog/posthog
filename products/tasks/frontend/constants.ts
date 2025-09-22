import { OriginProduct } from './types'

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
