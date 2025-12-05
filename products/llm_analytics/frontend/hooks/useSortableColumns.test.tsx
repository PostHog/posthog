import { render } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { useSortableColumns } from './useSortableColumns'

describe('useSortableColumns', () => {
    it('renders sortable column title with DESC indicator', () => {
        const setSort = jest.fn()
        const TestComponent = (): JSX.Element => {
            const { renderSortableColumnTitle } = useSortableColumns({ column: 'cost', direction: 'DESC' }, setSort)
            return <div>{renderSortableColumnTitle('cost', 'Cost')}</div>
        }

        const { container } = render(<TestComponent />)
        expect(container.textContent).toContain('Cost')
        expect(container.textContent).toContain('▼')
    })

    it('renders sortable column title with ASC indicator', () => {
        const setSort = jest.fn()
        const TestComponent = (): JSX.Element => {
            const { renderSortableColumnTitle } = useSortableColumns({ column: 'cost', direction: 'ASC' }, setSort)
            return <div>{renderSortableColumnTitle('cost', 'Cost')}</div>
        }

        const { container } = render(<TestComponent />)
        expect(container.textContent).toContain('Cost')
        expect(container.textContent).toContain('▲')
    })

    it('renders sortable column title without indicator for non-sorted column', () => {
        const setSort = jest.fn()
        const TestComponent = (): JSX.Element => {
            const { renderSortableColumnTitle } = useSortableColumns({ column: 'cost', direction: 'DESC' }, setSort)
            return <div>{renderSortableColumnTitle('traces', 'Traces')}</div>
        }

        const { container } = render(<TestComponent />)
        expect(container.textContent).toContain('Traces')
        expect(container.textContent).not.toContain('▼')
        expect(container.textContent).not.toContain('▲')
    })

    it('toggles from DESC to ASC when clicking same column', async () => {
        const setSort = jest.fn()
        const TestComponent = (): JSX.Element => {
            const { renderSortableColumnTitle } = useSortableColumns({ column: 'cost', direction: 'DESC' }, setSort)
            return <div>{renderSortableColumnTitle('cost', 'Cost')}</div>
        }

        const { container } = render(<TestComponent />)
        const element = container.querySelector('span')!
        await userEvent.click(element)

        expect(setSort).toHaveBeenCalledWith('cost', 'ASC')
    })

    it('defaults to DESC when clicking different column', async () => {
        const setSort = jest.fn()
        const TestComponent = (): JSX.Element => {
            const { renderSortableColumnTitle } = useSortableColumns({ column: 'cost', direction: 'DESC' }, setSort)
            return <div>{renderSortableColumnTitle('traces', 'Traces')}</div>
        }

        const { container } = render(<TestComponent />)
        const element = container.querySelector('span')!
        await userEvent.click(element)

        expect(setSort).toHaveBeenCalledWith('traces', 'DESC')
    })

    it('toggles from ASC to DESC when clicking same column', async () => {
        const setSort = jest.fn()
        const TestComponent = (): JSX.Element => {
            const { renderSortableColumnTitle } = useSortableColumns({ column: 'cost', direction: 'ASC' }, setSort)
            return <div>{renderSortableColumnTitle('cost', 'Cost')}</div>
        }

        const { container } = render(<TestComponent />)
        const element = container.querySelector('span')!
        await userEvent.click(element)

        expect(setSort).toHaveBeenCalledWith('cost', 'DESC')
    })

    it('applies correct styling for clickable column', () => {
        const setSort = jest.fn()
        const TestComponent = (): JSX.Element => {
            const { renderSortableColumnTitle } = useSortableColumns({ column: 'cost', direction: 'DESC' }, setSort)
            return <div>{renderSortableColumnTitle('cost', 'Cost')}</div>
        }

        const { container } = render(<TestComponent />)
        const element = container.querySelector('span')!

        expect(element.style.cursor).toBe('pointer')
        expect(element.style.userSelect).toBe('none')
        expect(element.className).toContain('flex')
        expect(element.className).toContain('items-center')
        expect(element.className).toContain('gap-1')
    })
})
