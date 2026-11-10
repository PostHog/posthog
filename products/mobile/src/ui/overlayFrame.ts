import { createContext } from 'react'

import type { DisplayRect } from './displayRegions'

export const OverlayFrameContext = createContext<DisplayRect | null>(null)
