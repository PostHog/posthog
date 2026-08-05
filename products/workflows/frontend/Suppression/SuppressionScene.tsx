import { SuppressionList } from './SuppressionList'

export function SuppressionScene(): JSX.Element {
    return (
        <div className="space-y-4" data-attr="suppression-scene">
            <div>
                <h2 className="text-xl font-semibold">Suppression list</h2>
                <p className="mt-2">
                    Email addresses that workflows will never send to. Addresses are added automatically after they
                    repeatedly soft-bounce (their mail server keeps rejecting or timing out), or you can add them
                    manually. Remove an address to start sending to it again.
                </p>
            </div>
            <SuppressionList />
        </div>
    )
}
