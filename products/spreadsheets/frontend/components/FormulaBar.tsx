import { LemonInput } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'

import { spreadsheetsSceneLogic } from '../spreadsheetsSceneLogic'

export const FormulaBar = (): JSX.Element => {
    const { setCurrentCellValue, setData } = useActions(spreadsheetsSceneLogic)
    const { currentCellMeta, currentCellValue, data, hotRef } = useValues(spreadsheetsSceneLogic)

    return (
        <div className="flex">
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
                className="flex-grow border-l-[color:var(--border-primary)] rounded-none border-0 border-l border-solid"
            />
        </div>
    )
}
