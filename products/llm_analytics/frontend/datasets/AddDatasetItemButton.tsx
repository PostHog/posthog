import { useActions } from 'kea'
import React from 'react'

import { IconPencil, IconPlusSmall } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { addDatasetItemLogic } from './addDatasetItemLogic'

export const AddDatasetItemButton = React.memo(function AddDatasetItemButton() {
    // const { datasets } = useValues(addDatasetItemLogic)
    const { setEditMode } = useActions(addDatasetItemLogic)

    return (
        <LemonButton
            type="secondary"
            icon={<IconPlusSmall />}
            sideAction={{
                icon: <IconPencil />,
                onClick: () => {
                    setEditMode('edit')
                },
                tooltip: 'Add span to dataset and edit it',
            }}
        >
            Add to dataset
        </LemonButton>
    )
})
