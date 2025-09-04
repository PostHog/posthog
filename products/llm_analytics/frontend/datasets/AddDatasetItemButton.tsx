import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import React from 'react'

import { IconDatabase, IconExternal, IconPencil } from '@posthog/icons'
import { LemonButton, LemonDivider, LemonDropdown, LemonInput, LemonSkeleton } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'
import { urls } from 'scenes/urls'

import { addDatasetItemLogic } from './addDatasetItemLogic'
import { useKeyboardNavigation } from './useKeyboardNavigation'

export const AddDatasetItemButton = React.memo(function AddDatasetItemButton() {
    const { dropdownVisible } = useValues(addDatasetItemLogic)
    const { setEditMode, setDropdownVisible } = useActions(addDatasetItemLogic)

    return (
        <LemonDropdown
            overlay={<OverlayMenu />}
            visible={dropdownVisible}
            onVisibilityChange={setDropdownVisible}
            closeOnClickInside={false}
        >
            <LemonButton
                type="secondary"
                size="xsmall"
                icon={<IconDatabase />}
                sideAction={{
                    icon: <IconPencil />,
                    onClick: () => {
                        if (!dropdownVisible) {
                            setEditMode('edit')
                        }
                        setDropdownVisible(!dropdownVisible)
                    },
                    tooltip: 'Add span to dataset and edit it',
                }}
                onClick={() => {
                    setDropdownVisible(!dropdownVisible)
                }}
            >
                Add to dataset
            </LemonButton>
        </LemonDropdown>
    )
})

function OverlayMenu(): JSX.Element {
    const { datasets, isLoadingDatasets } = useValues(addDatasetItemLogic)
    const { setSearchFormValue } = useActions(addDatasetItemLogic)

    const { referenceRef, itemsRef, focusedItemIndex } = useKeyboardNavigation<HTMLDivElement, HTMLButtonElement>(
        datasets?.length ?? 0,
        0,
        { enabled: !isLoadingDatasets }
    )

    return (
        <Form logic={addDatasetItemLogic} formKey="searchForm" className="w-xs">
            <LemonField name="search" label="Search" labelClassName="sr-only">
                <LemonInput placeholder="Find a dataset" autoFocus />
            </LemonField>
            <LemonDivider className="my-0 mt-2" />
            <div
                className={clsx('overflow-y-auto max-h-64 py-2', isLoadingDatasets ? 'space-y-4' : 'space-y-2')}
                ref={referenceRef}
            >
                {isLoadingDatasets ? (
                    <>
                        <LemonSkeleton active className="h-4 w-full" />
                        <LemonSkeleton active className="h-4 w-full" />
                        <LemonSkeleton active className="h-4 w-full" />
                        <LemonSkeleton active className="h-4 w-full" />
                        <LemonSkeleton active className="h-4 w-full" />
                    </>
                ) : datasets && datasets.length > 0 ? (
                    datasets.map((dataset, index) => (
                        <LemonButton
                            key={dataset.id}
                            ref={itemsRef?.current?.[index]}
                            fullWidth
                            size="small"
                            active={focusedItemIndex === index}
                            htmlType="submit"
                            onClick={() => {
                                setSearchFormValue('datasetId', dataset.id)
                            }}
                        >
                            <span className="line-clamp-1">{dataset.name}</span>
                        </LemonButton>
                    ))
                ) : (
                    <p className="text-muted text-sm">No datasets found</p>
                )}
            </div>
            <LemonDivider className="my-0 mb-2" />
            <LemonButton
                fullWidth
                size="small"
                to={urls.llmAnalyticsDataset('new')}
                sideIcon={<IconExternal />}
                targetBlank
            >
                Create new dataset
            </LemonButton>
        </Form>
    )
}
