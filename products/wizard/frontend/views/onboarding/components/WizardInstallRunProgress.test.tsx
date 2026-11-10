import { render, screen } from '@testing-library/react'

import type { WizardRunApi, WizardRunTaskApi } from '../../../generated/api.schemas'
import { WizardInstallRunProgress } from './WizardInstallRunProgress'

describe('WizardInstallRunProgress', () => {
    it('keeps the active task visible as the run progresses', () => {
        const tasks = Array.from({ length: 6 }, (_, index) => ({
            name: `Task ${index}`,
            status: index === 4 ? 'running' : index < 4 ? 'completed' : 'created',
        })) as WizardRunTaskApi[]

        render(
            <WizardInstallRunProgress
                run={{ status: 'running', stage: 'executing_wizard' } as WizardRunApi}
                tasks={tasks}
            />
        )

        expect(screen.getByText('Task 3')).toBeTruthy()
        expect(screen.getByText('Task 4')).toBeTruthy()
        expect(screen.getByText('Task 5')).toBeTruthy()
        expect(screen.queryByText('Task 0')).toBeNull()
    })
})
