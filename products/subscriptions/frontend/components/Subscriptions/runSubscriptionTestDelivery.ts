import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

function getErrorStatus(error: unknown): number | undefined {
    if (typeof error === 'object' && error !== null && 'status' in error) {
        const status = (error as { status: unknown }).status
        return typeof status === 'number' ? status : undefined
    }
    return undefined
}

export type SubscriptionTestDeliveryResult = 'success' | 'failure'

/** Toast + HTTP error mapping for subscription manual test delivery (scene list + insight/admin modal). */
export async function runSubscriptionTestDelivery(
    execute: () => Promise<void>
): Promise<SubscriptionTestDeliveryResult> {
    try {
        await execute()
        lemonToast.success('Test delivery started')
        return 'success'
    } catch (error: unknown) {
        if (getErrorStatus(error) === 409) {
            lemonToast.warning('Delivery already in progress')
        } else {
            lemonToast.error('Failed to deliver subscription')
        }
        return 'failure'
    }
}
