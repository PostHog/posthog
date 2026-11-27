import { createContext } from 'react'

export const SceneDimensionsContext = createContext<{ width: number; height: number } | null>(null)
