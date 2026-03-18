import { useRouter } from 'next/navigation'
import { useEffect } from 'react'

import { useAuth } from './auth'

export const useAuthRedirect = (): void => {
    const { isLoading, user } = useAuth()
    const router = useRouter()

    useEffect(() => {
        if (!isLoading && !user) {
            router.push('/login')
        }
    }, [isLoading, user, router])
}
