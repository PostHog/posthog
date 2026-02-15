import { Spinner } from 'lib/lemon-ui/Spinner/Spinner'

export function StreamlitAppLoading(): JSX.Element {
    return (
        <div className="flex flex-col items-center justify-center py-20 text-center">
            <h2 className="text-lg font-semibold mb-2">Waking up the hedgehogs...</h2>
            <p className="text-muted mb-6">Your app is starting. This usually takes about 10-30 seconds.</p>
            <Spinner className="text-4xl" />
        </div>
    )
}
