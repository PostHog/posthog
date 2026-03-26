'use client'

import React, { ReactNode, createContext, useContext, useEffect, useState } from 'react'

import { sampleUsers } from './data'
import { posthog } from './posthog'

interface User {
    id: string
    name: string
    email: string
    plan: string
    avatar?: string
}

interface AuthContextType {
    user: User | null
    login: (email: string, password: string) => Promise<boolean>
    signup: (name: string, email: string, password: string, plan: string) => Promise<boolean>
    logout: () => void
    isLoading: boolean
}

const AuthContext = createContext<AuthContextType | undefined>(undefined)

export function AuthProvider({ children }: { children: ReactNode }): React.JSX.Element {
    const [user, setUser] = useState<User | null>(null)
    const [isLoading, setIsLoading] = useState(true)

    // Load user from localStorage on mount
    useEffect(() => {
        const savedUser = localStorage.getItem('hedgebox_user')
        if (savedUser) {
            try {
                const userData = JSON.parse(savedUser)
                setUser(userData)
                // Re-identify user on page load
                posthog.identify(userData.id, userData)
            } catch {
                localStorage.removeItem('hedgebox_user')
            }
        }
        setIsLoading(false)
    }, [])

    const login = async (email: string /* password is intentionally unused in demo */): Promise<boolean> => {
        setIsLoading(true)

        try {
            // Simulate API call
            await new Promise((resolve) => setTimeout(resolve, 1500))

            // Find existing user or create new one
            let userData = sampleUsers.find((u) => u.email === email)
            if (!userData) {
                // Create fake user based on email
                const name = email.split('@')[0].replace(/[._]/g, ' ')
                userData = {
                    id: `user_${Date.now()}`,
                    name: name
                        .split(' ')
                        .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
                        .join(' '),
                    email,
                    plan: 'personal/free',
                }
            }

            const userWithAvatar = {
                ...userData,
                avatar: `https://api.dicebear.com/7.x/adventurer/svg?seed=${encodeURIComponent(userData.email)}&backgroundColor=1e40af`,
            }

            setUser(userWithAvatar)
            localStorage.setItem('hedgebox_user', JSON.stringify(userWithAvatar))

            // Track successful login
            posthog.capture('logged_in')
            posthog.identify(userWithAvatar.id, userWithAvatar)

            return true
        } catch {
            return false
        } finally {
            setIsLoading(false)
        }
    }

    const signup = async (name: string, email: string, password: string, plan: string): Promise<boolean> => {
        setIsLoading(true)

        try {
            // Simulate API call
            await new Promise((resolve) => setTimeout(resolve, 2000))

            const userData = {
                id: `user_${Date.now()}`,
                name,
                email,
                plan,
                avatar: `https://api.dicebear.com/7.x/adventurer/svg?seed=${encodeURIComponent(email)}&backgroundColor=1e40af`,
            }

            setUser(userData)
            localStorage.setItem('hedgebox_user', JSON.stringify(userData))

            // Track successful signup
            posthog.capture('signed_up', {
                from_invite: false,
            })
            posthog.identify(userData.id, userData)

            return true
        } catch {
            return false
        } finally {
            setIsLoading(false)
        }
    }

    const logout = (): void => {
        setUser(null)
        localStorage.removeItem('hedgebox_user')
        posthog.capture('logged_out')
        posthog.reset()
    }

    return <AuthContext.Provider value={{ user, login, signup, logout, isLoading }}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthContextType {
    const context = useContext(AuthContext)
    if (context === undefined) {
        throw new Error('useAuth must be used within an AuthProvider')
    }
    return context
}
