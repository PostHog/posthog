import { OptOutCategories } from './OptOutCategories'
import { OptOutList } from './OptOutList'

export function OptOutScene(): JSX.Element {
    return (
        <div className="space-y-8">
            <div>
                <h2 className="text-xl font-semibold mb-4">Message categories</h2>
                <OptOutCategories />
            </div>

            <div>
                <h2 className="text-xl font-semibold mb-4">Marketing opt-out list</h2>
                <OptOutList />
            </div>
        </div>
    )
}
