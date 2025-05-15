import { HotTableRef } from '@handsontable/react-wrapper'
import Handsontable from 'handsontable'
import { CellValue } from 'handsontable/common'
import { CellProperties } from 'handsontable/settings'
import { actions, kea, listeners, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'
import { router, urlToAction } from 'kea-router'
import { subscriptions } from 'kea-subscriptions'
import api from 'lib/api'
import { urls } from 'scenes/urls'

import { Spreadsheet, SpreadsheetCellFormatting, SpreadsheetSettings } from '~/types'

import type { spreadsheetsSceneLogicType } from './spreadsheetsSceneLogicType'

const NEW_SPREADSHEET_ID = 'new'
const DEFAULT_ROWS_COUNT = 50
export const DEFAULT_COLUMNS_COUNT = 26 * 2
export const DEFAULT_COLUMN_WIDTH = 100

export const spreadsheetsSceneLogic = kea<spreadsheetsSceneLogicType>([
    path(['products', 'spreadsheets', 'frontend', 'spreadsheetsSceneLogic']),
    actions(({ values }) => ({
        setCurrentCellMeta: (cell: CellProperties | null) => ({ cell }),
        setCurrentCellValue: (value: string) => ({ value }),
        setData: (data: string[][]) => ({ data }),
        setHotRef: (ref: HotTableRef | null) => ({ ref }),
        setShortId: (shortId: string) => ({ shortId }),
        setIsSaving: (isSaving: boolean) => ({ isSaving }),
        setSettings: (settings: SpreadsheetSettings) => ({ settings }),
        setFormatting: (formatting: (SpreadsheetCellFormatting | null)[][]) => ({ formatting }),
        updateColumnWidth: (size: number, columnIndex: number) => ({ size, columnIndex }),
        toggleBoldCell: (row: number, column: number) => ({ row, column, settings: values.settings }),
    })),
    loaders(({ values, actions }) => ({
        serverData: [
            null as Spreadsheet | null,
            {
                loadDataFromServer: async () => {
                    const shortId = values.shortId
                    if (shortId === NEW_SPREADSHEET_ID) {
                        return null
                    }

                    const spreadsheet = await api.spreadsheets.get(shortId)
                    if (spreadsheet.settings) {
                        actions.setSettings(spreadsheet.settings)
                    }
                    if (spreadsheet.formatting) {
                        actions.setFormatting(spreadsheet.formatting)
                    }

                    if (spreadsheet.data) {
                        actions.setData(spreadsheet.data as string[][])
                        return spreadsheet
                    }

                    return null
                },
                saveDataToServer: async (
                    {
                        data,
                        settings,
                        formatting,
                    }: {
                        data?: CellValue[]
                        settings?: SpreadsheetSettings
                        formatting?: (SpreadsheetCellFormatting | null)[][] | null
                    },
                    breakpoint
                ) => {
                    if (!values.hotRef) {
                        return null
                    }

                    await breakpoint(500)

                    const shortId = values.shortId

                    // New spreadsheet
                    if (shortId === NEW_SPREADSHEET_ID) {
                        const spreadsheet = await api.spreadsheets.create({
                            ...(data ? { data } : {}),
                            ...(settings ? { settings } : {}),
                            ...(formatting ? { formatting } : {}),
                            data_updated_at: new Date().toISOString(),
                        })

                        actions.setShortId(spreadsheet.short_id)
                        router.actions.replace(urls.spreadsheets(spreadsheet.short_id))

                        return spreadsheet
                    }

                    // Existing spreadsheet
                    const spreadsheet = await api.spreadsheets.update(shortId, {
                        ...(data ? { data } : {}),
                        ...(settings ? { settings } : {}),
                        ...(formatting ? { formatting } : {}),
                        data_updated_at: new Date().toISOString(),
                    })
                    return spreadsheet
                },
            },
        ],
    })),
    reducers({
        settings: [
            {} as SpreadsheetSettings,
            {
                setSettings: (_, { settings }) => settings,
                updateColumnWidth: (state, { size, columnIndex }) => {
                    const settings = { ...state }

                    if (!settings.columnWidths) {
                        settings.columnWidths = Array(state.columnCount ?? DEFAULT_COLUMNS_COUNT).fill(
                            DEFAULT_COLUMN_WIDTH
                        )
                    }

                    settings.columnWidths[columnIndex] = size

                    return settings
                },
            },
        ],
        formatting: [
            null as (SpreadsheetCellFormatting | null)[][] | null,
            {
                setFormatting: (_, { formatting }) => formatting,
                toggleBoldCell: (state, { row, column, settings }) => {
                    let formatting = state ? { ...state } : null

                    if (!formatting) {
                        formatting = Array.from({ length: settings.rowCount ?? DEFAULT_ROWS_COUNT }, () =>
                            Array(settings.columnCount ?? DEFAULT_COLUMNS_COUNT).fill(null)
                        ) as SpreadsheetCellFormatting[][]
                    }

                    const currentFormatting = formatting[row][column]
                    if (!currentFormatting || !('bold' in currentFormatting)) {
                        formatting[row][column] = { bold: true }
                    } else {
                        formatting[row][column] = { ...formatting[row][column], bold: !formatting[row][column]?.bold }
                    }

                    return formatting
                },
            },
        ],
        isSaving: [
            false as boolean,
            {
                saveDataToServer: () => true,
                saveDataToServerSuccess: () => false,
                saveDataToServerFailure: () => true,
            },
        ],
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
            Handsontable.helper.createEmptySpreadsheetData(DEFAULT_ROWS_COUNT, DEFAULT_COLUMNS_COUNT),
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
            if (values.hotRef && serverData) {
                if (serverData?.data) {
                    values.hotRef.hotInstance?.loadData(serverData.data)
                }

                if (serverData?.settings?.columnWidths) {
                    // values.hotRef.hotInstance?.updateSettings({
                    //     colWidths: serverData.settings.columnWidths.map((n) => n ?? DEFAULT_COLUMN_WIDTH),
                    // })
                }
            }
        },
        setShortId: ({ shortId }) => {
            if (shortId !== NEW_SPREADSHEET_ID) {
                actions.loadDataFromServer()
            }
        },
        // setSettings: ({ settings }) => {
        //     if (!values.hotRef) {
        //         return
        //     }

        //     if (settings.columnWidths) {
        //         values.hotRef.hotInstance?.updateSettings({
        //             colWidths: settings.columnWidths.map((n) => n ?? DEFAULT_COLUMN_WIDTH),
        //         })
        //     }
        // },
    })),
    subscriptions(({ actions }) => ({
        settings: (settings: SpreadsheetSettings) => {
            actions.saveDataToServer({ settings })
        },
        formatting: (formatting: (SpreadsheetCellFormatting | null)[][] | null) => {
            actions.saveDataToServer({ formatting })
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
