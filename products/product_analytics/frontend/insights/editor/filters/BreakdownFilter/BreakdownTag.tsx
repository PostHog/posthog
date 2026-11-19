import './BreakdownTag.scss'

import clsx from 'clsx'
import { BindLogic, useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconEllipsis, IconX } from '@posthog/icons'
import { LemonButton, LemonButtonDropdown, LemonButtonWithDropdown } from '@posthog/lemon-ui'

import { useQuillSurface } from 'lib/components/QuillSurface/quillSurfaceContext'
import { PopoverReferenceContext } from 'lib/lemon-ui/Popover/Popover'
import { insightLogic } from 'scenes/insights/insightLogic'

import { BreakdownType } from '~/types'

import { BreakdownTagLabel } from './BreakdownTagLabel'
import { breakdownTagLogic } from './breakdownTagLogic'
import { BreakdownTagMenu } from './BreakdownTagMenu'
import { QuillEditableBreakdownTag } from './QuillEditableBreakdownTag'
import { TaxonomicBreakdownPopover } from './TaxonomicBreakdownPopover'
import { useBreakdownPropertyName } from './useBreakdownPropertyName'

type EditableBreakdownTagProps = {
    breakdown: string | number
    breakdownType: BreakdownType
    isTrends: boolean
    disablePropertyInfo?: boolean
    size?: 'small' | 'medium'
}

export function EditableBreakdownTag({
    breakdown,
    breakdownType,
    isTrends,
    disablePropertyInfo,
    size = 'medium',
}: EditableBreakdownTagProps): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const [filterOpen, setFilterOpen] = useState(false)
    const [menuOpen, setMenuOpen] = useState(false)

    const logicProps = { insightProps, breakdown, breakdownType, isTrends }
    const { removeBreakdown } = useActions(breakdownTagLogic(logicProps))
    const { isMultipleBreakdownsEnabled, isHistogramable, isNormalizeable, taxonomicBreakdownType } = useValues(
        breakdownTagLogic(logicProps)
    )
    const quillSurface = useQuillSurface()
    const hasMenu = !isMultipleBreakdownsEnabled || isHistogramable || isNormalizeable

    if (quillSurface) {
        return (
            <BindLogic logic={breakdownTagLogic} props={logicProps}>
                <QuillEditableBreakdownTag
                    breakdown={breakdown}
                    breakdownType={breakdownType}
                    taxonomicBreakdownType={taxonomicBreakdownType}
                    hasMenu={hasMenu}
                    filterOpen={filterOpen}
                    setFilterOpen={setFilterOpen}
                    menuOpen={menuOpen}
                    setMenuOpen={setMenuOpen}
                    onRemove={removeBreakdown}
                    disablePropertyInfo={disablePropertyInfo}
                />
            </BindLogic>
        )
    }

    return (
        <BindLogic logic={breakdownTagLogic} props={logicProps}>
            <TaxonomicBreakdownPopover
                open={filterOpen}
                setOpen={setFilterOpen}
                breakdownValue={breakdown}
                breakdownType={breakdownType}
                taxonomicType={taxonomicBreakdownType}
            >
                {hasMenu ? (
                    <div className="max-w-full">
                        {/* :TRICKY: we don't want the close button to be active when the edit popover is open.
                         * Therefore we're wrapping the lemon tag a context provider to override the parent context. */}
                        <PopoverReferenceContext.Provider value={null}>
                            <BreakdownTag
                                breakdown={breakdown}
                                breakdownType={breakdownType}
                                // display remove button only if we can edit and don't have a separate menu
                                onClick={() => {
                                    setFilterOpen(!filterOpen)
                                }}
                                popover={{
                                    overlay: <BreakdownTagMenu />,
                                    closeOnClickInside: false,
                                    onVisibilityChange: (visible) => {
                                        setMenuOpen(visible)
                                    },
                                }}
                                disablePropertyInfo={disablePropertyInfo || filterOpen || menuOpen}
                                size={size}
                            />
                        </PopoverReferenceContext.Provider>
                    </div>
                ) : (
                    <div className="max-w-full">
                        {/* If multiple breakdowns are enabled and it's not a numeric or URL property, enable the delete button */}
                        <BreakdownTag
                            breakdown={breakdown}
                            breakdownType={breakdownType}
                            onClose={removeBreakdown}
                            onClick={() => {
                                setFilterOpen(!filterOpen)
                            }}
                            disablePropertyInfo={disablePropertyInfo || filterOpen || menuOpen}
                            size={size}
                        />
                    </div>
                )}
            </TaxonomicBreakdownPopover>
        </BindLogic>
    )
}

export type BreakdownTagProps = {
    breakdown: string | number
    breakdownType: BreakdownType | null | undefined
    disablePropertyInfo?: boolean
    onClose?: () => void
    onClick?: (e: React.MouseEvent<HTMLDivElement | HTMLButtonElement>) => void
    popover?: LemonButtonDropdown
    size?: 'small' | 'medium'
}

export function BreakdownTag({
    breakdown,
    breakdownType = 'event',
    disablePropertyInfo,
    onClose,
    onClick,
    popover,
    size = 'medium',
}: BreakdownTagProps): JSX.Element {
    const propertyName = useBreakdownPropertyName(breakdown, breakdownType)

    const clickable = onClick !== undefined
    const closeable = onClose !== undefined
    const ButtonComponent = clickable ? 'button' : 'div'

    return (
        <ButtonComponent
            className={clsx('BreakdownTag', `BreakdownTag--${size}`, {
                'BreakdownTag--clickable': clickable,
            })}
            data-attr="breakdown-tag"
            type={ButtonComponent === 'button' ? 'button' : undefined}
            title={String(propertyName)}
            onClick={onClick}
        >
            <BreakdownTagLabel
                propertyName={propertyName}
                breakdownType={breakdownType}
                disablePropertyInfo={disablePropertyInfo}
            />
            {popover?.overlay && (
                <LemonButtonWithDropdown
                    size="xsmall"
                    icon={<IconEllipsis />}
                    onClick={(e) => {
                        e.stopPropagation()
                    }}
                    dropdown={popover}
                    className="p-0.5"
                    data-attr="breakdown-tag-options"
                />
            )}

            {closeable && (
                <LemonButton
                    size="xsmall"
                    icon={<IconX />}
                    onClick={(e) => {
                        e.stopPropagation()
                        onClose()
                    }}
                    className="p-0.5"
                    data-attr="breakdown-tag-close"
                />
            )}
        </ButtonComponent>
    )
}
