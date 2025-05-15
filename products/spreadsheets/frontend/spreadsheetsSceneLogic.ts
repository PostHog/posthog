import { HotTableRef } from '@handsontable/react-wrapper'
import Handsontable from 'handsontable'
import { CellProperties } from 'handsontable/settings'
import { actions, kea, path, reducers } from 'kea'

import type { spreadsheetsSceneLogicType } from './spreadsheetsSceneLogicType'

export const spreadsheetsSceneLogic = kea<spreadsheetsSceneLogicType>([
    path(['products', 'spreadsheets', 'frontend', 'spreadsheetsSceneLogic']),
    actions({
        setCurrentCellMeta: (cell: CellProperties | null) => ({ cell }),
        setCurrentCellValue: (value: string) => ({ value }),
        setData: (data: string[][]) => ({ data }),
        setHotRef: (ref: HotTableRef | null) => ({ ref }),
    }),
    reducers({
        hotRef: [
            null as HotTableRef | null,
            {
                setHotRef: (_, { ref }) => ref,
            },
        ],
        data: [
            Handsontable.helper.createEmptySpreadsheetData(50, 26 * 2),
            {
                setData: (_, { data }) => data,
            },
        ],
        currentCellMeta: [
            null as CellProperties | null,
            {
                setCurrentCellMeta: (_, { cell }) => cell,
            },
        ],
        currentCellValue: [
            '' as string,
            {
                setCurrentCellValue: (_, { value }) => value,
            },
        ],
    }),
])
