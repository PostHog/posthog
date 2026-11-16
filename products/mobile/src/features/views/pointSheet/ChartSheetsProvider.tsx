import { createContext, type ReactElement, type ReactNode, useCallback, useContext, useMemo, useState } from 'react'

import type { ChartTooltipPoint } from '@/ui/chart/types'
import { AboutSheet } from '../about/AboutSheet'
import { trackChartAboutOpened, trackChartPointSheetOpened } from '../analytics'
import { useViewsContext } from '../useViewsContext'
import type { ChartSheetSource } from './chartSheetSource'
import { PointSheet, type PointSheetRequest } from './PointSheet'

export type PointSheetEntry = 'tooltip' | 'more' | 'accessibility'
export type AboutSheetEntry = 'icon' | 'point_sheet' | 'accessibility'

export interface ChartSheets {
    /** Opens the Point sheet for a tapped tooltip: `MetricChart`'s `onPressTooltip`. */
    openPoint: (source: ChartSheetSource, point: ChartTooltipPoint, entry?: PointSheetEntry) => void
    /** Opens "About this chart". */
    openAbout: (source: ChartSheetSource, entry?: AboutSheetEntry) => void
}

const ChartSheetsContext = createContext<ChartSheets | null>(null)

/**
 * Hosts the Point sheet and the About sheet for every chart below it. The sheets draw through `OverlayPortal`, so
 * place an `OverlayHost` above this provider and outside the `ChartSelectionProvider`: a touch in a sheet then does
 * not close the pinned tooltip behind it.
 */
export function ChartSheetsProvider({ children }: { children: ReactNode }): ReactElement {
    const { identity } = useViewsContext()
    return <SessionChartSheets key={identity}>{children}</SessionChartSheets>
}

function SessionChartSheets({ children }: { children: ReactNode }): ReactElement {
    const [point, setPoint] = useState<PointSheetRequest | null>(null)
    const [about, setAbout] = useState<ChartSheetSource | null>(null)

    const openAbout = useCallback((source: ChartSheetSource, entry: AboutSheetEntry = 'icon') => {
        trackChartAboutOpened({ entry })
        setPoint(null)
        setAbout(source)
    }, [])
    const openPoint = useCallback(
        (source: ChartSheetSource, chartPoint: ChartTooltipPoint, entry: PointSheetEntry = 'tooltip') => {
            trackChartPointSheetOpened({ entry })
            setAbout(null)
            setPoint({ source, point: chartPoint })
        },
        []
    )
    const value = useMemo<ChartSheets>(() => ({ openPoint, openAbout }), [openPoint, openAbout])
    const closePoint = useCallback(() => setPoint(null), [])
    const closeAbout = useCallback(() => setAbout(null), [])
    const aboutFromPoint = useCallback((source: ChartSheetSource) => openAbout(source, 'point_sheet'), [openAbout])

    return (
        <ChartSheetsContext.Provider value={value}>
            {children}
            <PointSheet request={point} onClose={closePoint} onOpenAbout={aboutFromPoint} />
            <AboutSheet source={about} onClose={closeAbout} />
        </ChartSheetsContext.Provider>
    )
}

/** The Point and About sheets of the nearest `ChartSheetsProvider`. */
export function useChartSheets(): ChartSheets {
    const sheets = useContext(ChartSheetsContext)
    if (!sheets) {
        throw new Error('useChartSheets needs a ChartSheetsProvider above it.')
    }
    return sheets
}
