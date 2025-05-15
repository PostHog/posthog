import { LemonInput } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { dayjs } from 'lib/dayjs'
import { forwardRef, useMemo } from 'react'

import { spreadsheetsSceneLogic } from '../spreadsheetsSceneLogic'

export const FormulaBar = forwardRef<HTMLDivElement>((_, ref): JSX.Element => {
    const { setCurrentCellValue, setData } = useActions(spreadsheetsSceneLogic)
    const { currentCellMeta, currentCellValue, data, hotRef, isSaving, serverData } = useValues(spreadsheetsSceneLogic)

    const lastSavedText = useMemo(() => {
        if (isSaving) {
            return 'Saving...'
        }

        if (serverData?.data_updated_at) {
            return `Saved ${dayjs(serverData.data_updated_at).fromNow()}`
        }

        return ''
    }, [serverData, isSaving])

    return (
        <div className="flex" ref={ref}>
            <span className="flex items-center min-w-[40px] justify-center bg-white dark:bg-black">
                {currentCellMeta
                    ? `${hotRef?.hotInstance?.getColHeader(currentCellMeta?.col)}${currentCellMeta?.row + 1}`
                    : '-'}
            </span>
            <LemonInput
                value={currentCellValue ?? ''}
                onChange={(value) => {
                    if (!currentCellMeta) {
                        return
                    }

                    const newData = [...data]
                    newData[currentCellMeta.row][currentCellMeta.col] = value
                    setData(newData)
                    setCurrentCellValue(value)
                }}
                className="flex-grow border-l-[color:var(--border-primary)] border-r-[color:var(--border-primary)] rounded-none border-0 border-l border-r border-solid"
            />
            {lastSavedText && (
                <span className="flex items-center px-2 justify-center bg-white dark:bg-black">{lastSavedText}</span>
            )}
        </div>
    )
})

FormulaBar.displayName = 'FormulaBar'
