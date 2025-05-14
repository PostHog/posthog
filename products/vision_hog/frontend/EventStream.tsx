import { LiveEventsTable } from 'products/vision_hog/frontend/LiveEventsTable'

export function EventStream(): JSX.Element {
    return (
        <div>
            <h2 className="text-lg font-semibold mb-4">Events</h2>
            <LiveEventsTable />
        </div>
    )
}
