import { HotTableRef } from '@handsontable/react-wrapper'
import Handsontable from 'handsontable'
import { CellValue } from 'handsontable/common'
import { CellProperties } from 'handsontable/settings'
import { actions, kea, listeners, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'
import { router, urlToAction } from 'kea-router'
import api from 'lib/api'
import { urls } from 'scenes/urls'

import type { spreadsheetsSceneLogicType } from './spreadsheetsSceneLogicType'

const NEW_SPREADSHEET_ID = 'new'

export const spreadsheetsSceneLogic = kea<spreadsheetsSceneLogicType>([
    path(['products', 'spreadsheets', 'frontend', 'spreadsheetsSceneLogic']),
    actions({
        setCurrentCellMeta: (cell: CellProperties | null) => ({ cell }),
        setCurrentCellValue: (value: string) => ({ value }),
        setData: (data: string[][]) => ({ data }),
        setHotRef: (ref: HotTableRef | null) => ({ ref }),
        setShortId: (shortId: string) => ({ shortId }),
    }),
    loaders(({ values, actions }) => ({
        serverData: [
            null as any,
            {
                loadDataFromServer: async () => {
                    const shortId = values.shortId
                    if (shortId === NEW_SPREADSHEET_ID) {
                        return null
                    }

                    const spreadsheet = await api.spreadsheets.get(shortId)
                    if (spreadsheet.data) {
                        actions.setData(spreadsheet.data as string[][])
                        return spreadsheet.data as CellValue[]
                    }
                    return null
                },
                saveDataToServer: async (data: CellValue[]) => {
                    if (!values.hotRef) {
                        return null
                    }

                    const shortId = values.shortId

                    // New spreadsheet
                    if (shortId === NEW_SPREADSHEET_ID) {
                        const spreadsheet = await api.spreadsheets.create({
                            data,
                            data_updated_at: new Date().toISOString(),
                        })

                        actions.setShortId(spreadsheet.short_id)
                        router.actions.replace(urls.spreadsheets(spreadsheet.short_id))

                        return data
                    }

                    // Existing spreadsheet
                    await api.spreadsheets.update(shortId, { data, data_updated_at: new Date().toISOString() })
                    return data
                },
            },
        ],
    })),
    reducers({
        shortId: [
            NEW_SPREADSHEET_ID as string,
            {
                setShortId: (_, { shortId }) => shortId,
            },
        ],
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
    listeners(({ values, actions }) => ({
        loadDataFromServerSuccess: ({ serverData }) => {
            if (serverData && values.hotRef) {
                values.hotRef.hotInstance?.loadData(serverData)
            }
        },
        setShortId: ({ shortId }) => {
            if (shortId !== NEW_SPREADSHEET_ID) {
                actions.loadDataFromServer()
            }
        },
    })),
    urlToAction(({ actions }) => ({
        '/spreadsheets/:id': ({ id }) => {
            if (id) {
                actions.setShortId(id)
            }
        },
    })),
])
