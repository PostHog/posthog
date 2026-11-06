import type { TransactionalEmailLogDetailApi } from 'products/messaging/frontend/generated/api.schemas'

import { buildDeliverySteps } from './emailDeliverySteps'
import { TransactionalEmailDeliveryStep } from './TransactionalEmailDeliveryStep'

export function TransactionalEmailDeliveryProgress({ email }: { email: TransactionalEmailLogDetailApi }): JSX.Element {
    const steps = buildDeliverySteps(email)
    return (
        <ol
            className="flex flex-col @2xl:flex-row gap-3 @2xl:gap-0 m-0 p-4 list-none border rounded bg-surface-primary"
            data-attr="transactional-email-delivery-progress"
        >
            {steps.map((step, index) => (
                <TransactionalEmailDeliveryStep key={step.key} step={step} next={steps[index + 1]} />
            ))}
        </ol>
    )
}
