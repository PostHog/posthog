import { HedgeboxAccount, HedgeboxFile, HedgeboxUser } from '@/types'

// Sample users
export const sampleUsers: HedgeboxUser[] = [
    {
        id: 'user1',
        name: 'Sonic Hedgehog',
        email: 'sonic@hedgebox.net',
        plan: 'personal/pro',
    },
    {
        id: 'user2',
        name: 'Amy Rose',
        email: 'amy@hedgebox.net',
        plan: 'business/standard',
    },
    {
        id: 'user3',
        name: 'Knuckles Echidna',
        email: 'knuckles@hedgebox.net',
        plan: 'personal/free',
    },
]

// Sample files
export const sampleFiles: HedgeboxFile[] = [
    {
        id: 'file1',
        name: 'ring-collection-2024.jpg',
        type: 'image/jpeg',
        size: 2400000,
        uploadedAt: new Date('2024-01-15'),
    },
    {
        id: 'file2',
        name: 'emerald-locations.pdf',
        type: 'application/pdf',
        size: 850000,
        uploadedAt: new Date('2024-01-20'),
        sharedLink: 'https://hedgebox.net/files/file2/shared',
    },
    {
        id: 'file3',
        name: 'chili-dog-recipe.doc',
        type: 'application/msword',
        size: 125000,
        uploadedAt: new Date('2024-01-25'),
    },
    {
        id: 'file4',
        name: 'loop-de-loop-tutorial.mp4',
        type: 'video/mp4',
        size: 15600000,
        uploadedAt: new Date('2024-02-01'),
    },
]

// Sample account
export const sampleAccount: HedgeboxAccount = {
    id: 'account1',
    name: "Sonic's Files",
    plan: 'personal/pro',
    usedStorage: 19000000, // ~19MB
    maxStorage: 1000000000, // 1GB
    teamMembers: [sampleUsers[0]],
    files: sampleFiles,
}

// Pricing plans data
export const pricingPlans = [
    {
        name: 'Personal Free',
        price: '$0',
        period: 'forever',
        storage: '10 GB',
        features: ['Basic file sharing', 'Email support', '1 user'],
    },
    {
        name: 'Personal Pro',
        price: '$10',
        period: 'per month',
        storage: '1 TB',
        features: ['Advanced sharing', 'Priority support', '1 user', 'Version history'],
    },
    {
        name: 'Business Standard',
        price: '$10',
        period: 'per user/month',
        storage: '5 TB',
        features: ['Team collaboration', '24/7 support', 'Unlimited users', 'Admin controls'],
    },
    {
        name: 'Business Enterprise',
        price: '$20',
        period: 'per user/month',
        storage: '100 TB',
        features: ['Enterprise features', 'Dedicated support', 'SSO', 'Advanced security'],
    },
]
