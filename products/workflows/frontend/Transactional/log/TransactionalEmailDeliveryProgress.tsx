import type { TransactionalEmailLogDetailApi } from 'products/messaging/frontend/generated/api.schemas'

import { buildDeliverySteps } from './emailDeliverySteps'
import { TransactionalEmailDeliveryStep } from './TransactionalEmailDeliveryStep'

export function TransactionalEmailDeliveryProgress({ email }: { email: TransactionalEmailLogDetailApi }): JSX.Element {
    const steps = buildDeliverySteps(email)
    const failureReason = steps.find((step) => step.state === 'failed')?.detail
    return (
        <div className="border rounded bg-surface-primary overflow-hidden">
            <ol
                className="flex flex-col @2xl:flex-row gap-3 @2xl:gap-0 m-0 p-4 list-none"
                data-attr="transactional-email-delivery-progress"
            >
                {steps.map((step, index) => (
                    <TransactionalEmailDeliveryStep key={step.key} step={step} next={steps[index + 1]} />
                ))}
            </ol>
            {failureReason && (
                <div
                    className="border-t border-danger bg-danger-highlight text-danger px-4 py-2 text-sm"
                    data-attr="transactional-email-failure-reason"
                >
                    {failureReason}
                </div>
            )}
        </div>
    )
}
