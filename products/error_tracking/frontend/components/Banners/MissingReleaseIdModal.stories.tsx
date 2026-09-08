import { Meta } from '@storybook/react'
import { useActions } from 'kea'

import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'

import { MissingReleaseIdModal, MissingReleaseIdModalProps } from './MissingReleaseIdModal'
import { missingReleaseIdModalLogic } from './missingReleaseIdModalLogic'

const meta: Meta<typeof MissingReleaseIdModal> = {
    title: 'ErrorTracking/MissingReleaseIdModal',
    component: MissingReleaseIdModal,
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
    },
}

export default meta

function OpenedModal(props: MissingReleaseIdModalProps): JSX.Element {
    const { openModal } = useActions(missingReleaseIdModalLogic)
    useOnMountEffect(() => openModal())
    return <MissingReleaseIdModal {...props} />
}

export function WebSdk(): JSX.Element {
    return <OpenedModal runtime="web" />
}

export function NodeSdk(): JSX.Element {
    return <OpenedModal runtime="node" />
}

export function UnknownSdk(): JSX.Element {
    return <OpenedModal runtime="go" />
}
