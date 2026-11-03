import { useContext } from 'react'
import { type ScaledSize, useWindowDimensions } from 'react-native'

import { SceneDimensionsContext } from './sceneDimensions'

export function useSceneDimensions(): ScaledSize {
    const window = useWindowDimensions()
    const scene = useContext(SceneDimensionsContext)
    return { ...window, ...scene }
}
