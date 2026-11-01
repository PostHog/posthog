import type { Meta, StoryObj } from '@storybook/react'

import { LemonDialog, LemonDialogProps } from 'lib/lemon-ui/LemonDialog'

import {
    ALLOW_AI_ANALYSIS_DIALOG,
    TAKE_OVER_DIALOG,
    aiAnalysisOffDialogProps,
    confirmDialogProps,
} from './saveScannerEnabled'

// The dialogs `saveScannerEnabled` opens before a scanner can turn on, rendered inline with the same props.
const meta: Meta<LemonDialogProps> = {
    title: 'Scenes-App/Replay Vision/TurnOnScannerDialogs',
    render: (props) => <LemonDialog {...props} inline />,
}
export default meta

type Story = StoryObj<LemonDialogProps>

export const AllowAIAnalysis: Story = { args: confirmDialogProps(ALLOW_AI_ANALYSIS_DIALOG) }

export const AIAnalysisOffForMember: Story = { args: aiAnalysisOffDialogProps() }

export const TakeOverScanner: Story = { args: confirmDialogProps(TAKE_OVER_DIALOG) }
