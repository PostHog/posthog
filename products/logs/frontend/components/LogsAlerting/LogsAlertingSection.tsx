import { BindLogic, useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { LemonButton } from '@posthog/lemon-ui'

import { LemonModal } from 'lib/lemon-ui/LemonModal'

import { LogsAlertConfigurationApi } from 'products/logs/frontend/generated/api.schemas'

import { LogsAlertForm } from './LogsAlertForm'
import { logsAlertFormLogic } from './logsAlertFormLogic'
import { logsAlertingLogic } from './logsAlertingLogic'
import { LogsAlertList } from './LogsAlertList'

export function LogsAlertingSection(): JSX.Element {
    return (
        <BindLogic logic={logsAlertingLogic} props={{}}>
            <LogsAlertingSectionInner />
        </BindLogic>
    )
}

function LogsAlertingSectionInner(): JSX.Element {
    const { isCreating, editingAlert } = useValues(logsAlertingLogic)
    const { setIsCreating, setEditingAlert } = useActions(logsAlertingLogic)

    const isModalOpen = isCreating || editingAlert !== null

    return (
        <>
            <LogsAlertList />
            <LemonModal
                isOpen={isModalOpen}
                onClose={() => {
                    setIsCreating(false)
                    setEditingAlert(null)
                }}
                title=""
                simple
                width={720}
            >
                {isModalOpen && <LogsAlertModalContent editingAlert={editingAlert} />}
            </LemonModal>
        </>
    )
}

function LogsAlertModalContent({ editingAlert }: { editingAlert: LogsAlertConfigurationApi | null }): JSX.Element {
    const formLogicProps = { alert: editingAlert }
    const { isAlertFormSubmitting } = useValues(logsAlertFormLogic(formLogicProps))

    return (
        <Form
            logic={logsAlertFormLogic}
            props={formLogicProps}
            formKey="alertForm"
            enableFormOnSubmit
            className="LemonModal__layout"
        >
            <LemonModal.Header>
                <h3>{editingAlert ? 'Edit alert' : 'New alert'}</h3>
                <p className="text-muted text-sm m-0">Alerts are checked every minute.</p>
            </LemonModal.Header>
            <LemonModal.Content>
                <LogsAlertForm />
            </LemonModal.Content>
            <LemonModal.Footer>
                <div className="flex-1" />
                <LemonButton type="primary" htmlType="submit" loading={isAlertFormSubmitting}>
                    {editingAlert ? 'Save' : 'Create alert'}
                </LemonButton>
            </LemonModal.Footer>
        </Form>
    )
}
