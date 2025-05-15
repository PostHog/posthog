import { LemonButton } from 'lib/lemon-ui/LemonButton'
import logo from './logo.png'

export function HogWars() {
    return (
        <div className='flex flex-col gap-10 mt-10'>
            <div className="flex items-center justify-center">
                <img src={logo} className='w-[400px] max-w-full' />
            </div>
            <div className="flex items-center justify-center">
                <LemonButton type="primary" onClick={() => {
                    const url = 'http://localhost:8002/'
                    window.open(url, '_blank')
                }}>Launch</LemonButton>
            </div>
        </div>
    )
}

export default HogWars
