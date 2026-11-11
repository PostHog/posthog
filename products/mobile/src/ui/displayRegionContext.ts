import { createContext, useContext } from 'react'
import { type ReservedRegion, useReservedRegions } from 'react-native-reserved-regions'

export const DisplayRegionContext = createContext<readonly ReservedRegion[] | null>(null)

export function useDisplayRegions(): readonly ReservedRegion[] {
    const regions = useReservedRegions()
    return useContext(DisplayRegionContext) ?? regions
}
