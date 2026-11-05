import { FlappyHogGame } from 'products/games/FlappyHog/FlappyHogGame'

const FlappyHogPage: React.FC = () => {
    return (
        <div className="flex flex-col items-center p-4">
            <FlappyHogGame />
        </div>
    )
}

export default FlappyHogPage
