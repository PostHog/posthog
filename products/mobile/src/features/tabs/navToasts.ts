import { createContext, useContext } from 'react'
import type { Toasts } from '@/features/views/ViewsToast'

export const NavToastsContext = createContext<Toasts | null>(null)

export function useNavToasts(): Toasts {
    const toasts = useContext(NavToastsContext)
    if (!toasts) throw new Error('Navigation toasts require TabsLayout')
    return toasts
}
