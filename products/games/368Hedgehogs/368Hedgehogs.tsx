import './368Hedgehogs.scss'

import { useCallback, useRef, useState } from 'react'

import { IconInfo } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { Tooltip } from 'lib/lemon-ui/Tooltip'

// ==========================================================================
export type Hog = 'hog1' | 'hog2' | 'hog3' | 'hog4'
export type Orientation = 'horizontal' | 'vertical'

interface Piece {
    orientation: Orientation
    cells: [Hog, Hog]
}

interface DragPayload {
    piece: Piece
    offset: 0 | 1
}

const BOARD_SIZE = 6
const EMOJIS: Hog[] = ['hog1', 'hog2', 'hog3', 'hog4']

const IMAGE_MAP: Record<Hog, string> = {
    hog1: '/static/hedgehog/burning-money-hog.png',
    hog2: '/static/hedgehog/police-hog.png',
    hog3: '/static/hedgehog/sleeping-hog.png',
    hog4: '/static/hedgehog/warning-hog.png',
}

type Board = (Hog | null)[][] // 6×6 grid

// ==========================================================================
// Helpers
const makeEmptyBoard = (): Board => Array.from({ length: BOARD_SIZE }, () => Array<Hog | null>(BOARD_SIZE).fill(null))

// Generate a piece that **can actually be placed** on the current board.
// Returns null if the board has no legal placement left.
const genPieceForBoard = (board: Board): Piece | null => {
    // Collect every orientation that has **any** legal anchor position.
    const legalOrientations: Orientation[] = []

    for (let r = 0; r < BOARD_SIZE; r++) {
        for (let c = 0; c < BOARD_SIZE; c++) {
            if (board[r][c] !== null) {
                continue // anchor occupied
            }
            // Horizontal: need right neighbour
            if (c + 1 < BOARD_SIZE && board[r][c + 1] === null) {
                legalOrientations.push('horizontal')
            }
            // Vertical: need cell below
            if (r + 1 < BOARD_SIZE && board[r + 1][c] === null) {
                legalOrientations.push('vertical')
            }
        }
    }

    if (legalOrientations.length === 0) {
        return null // No space left for **any** piece – game over
    }

    const orientation = legalOrientations[Math.floor(Math.random() * legalOrientations.length)] as Orientation
    const cells: [Hog, Hog] = [
        EMOJIS[Math.floor(Math.random() * EMOJIS.length)],
        EMOJIS[Math.floor(Math.random() * EMOJIS.length)],
    ]
    return { orientation, cells }
}

const cellKey = (r: number, c: number): string => `${r}-${c}`

// Find matches but do NOT clear; return coordinates to remove
function findMatches(board: Board): string[] {
    const matches: boolean[][] = makeEmptyBoard().map((row) => row.map(() => false))

    // Horizontal
    for (let r = 0; r < BOARD_SIZE; r++) {
        let c = 0
        while (c < BOARD_SIZE) {
            const emoji = board[r][c]
            if (!emoji) {
                c++
                continue
            }
            let len = 1
            while (c + len < BOARD_SIZE && board[r][c + len] === emoji) {
                len++
            }
            if (len >= 3) {
                for (let k = 0; k < len; k++) {
                    matches[r][c + k] = true
                }
            }
            c += len
        }
    }

    // Vertical
    for (let c = 0; c < BOARD_SIZE; c++) {
        let r = 0
        while (r < BOARD_SIZE) {
            const emoji = board[r][c]
            if (!emoji) {
                r++
                continue
            }
            let len = 1
            while (r + len < BOARD_SIZE && board[r + len][c] === emoji) {
                len++
            }
            if (len >= 3) {
                for (let k = 0; k < len; k++) {
                    matches[r + k][c] = true
                }
            }
            r += len
        }
    }

    const coords: string[] = []
    matches.forEach((row, r) =>
        row.forEach((flag, c) => {
            if (flag) {
                coords.push(cellKey(r, c))
            }
        })
    )
    return coords
}

// ==========================================================================
// Main component
const CritterMatchGame: React.FC = () => {
    // Build an *initial* board once so we can derive both board & first piece from it.
    const initialBoard = makeEmptyBoard()

    // Game state
    const [board, setBoard] = useState<Board>(initialBoard)
    const [piece, setPiece] = useState<Piece | null>(() => genPieceForBoard(initialBoard))
    const [pointsLeft, setPointsLeft] = useState<number>(368)
    const [clearing, setClearing] = useState<Set<string>>(new Set())
    const [gameOver, setGameOver] = useState<boolean>(false)

    // Refs & timers
    const clearTimer = useRef<NodeJS.Timeout | null>(null)
    const boardRef = useRef<HTMLDivElement>(null)

    // ------------------------------------------------------------------------
    // Shared drop logic (desktop D-n-D + mobile pointer)
    const attemptPlacePiece = useCallback(
        (anchorR: number, anchorC: number, droppedPiece: Piece | null, offset: 0 | 1): void => {
            if (gameOver || clearing.size || !droppedPiece) {
                return
            }

            const { orientation, cells } = droppedPiece

            // Adjust anchor when user grabbed the 2nd square
            if (offset === 1) {
                if (orientation === 'horizontal') {
                    anchorC -= 1
                } else {
                    anchorR -= 1
                }
            }

            // Bounds
            if (anchorR < 0 || anchorC < 0) {
                return
            }
            const row2 = orientation === 'vertical' ? anchorR + 1 : anchorR
            const col2 = orientation === 'horizontal' ? anchorC + 1 : anchorC
            if (row2 >= BOARD_SIZE || col2 >= BOARD_SIZE) {
                return
            }

            // Occupancy
            if (board[anchorR][anchorC] || board[row2][col2]) {
                return
            }

            // Place piece
            const newBoard: Board = board.map((r) => r.slice()) as Board
            newBoard[anchorR][anchorC] = cells[0]
            newBoard[row2][col2] = cells[1]

            // Matches?
            const toRemove = findMatches(newBoard)
            if (toRemove.length === 0) {
                setBoard(newBoard)
                const nextPiece = genPieceForBoard(newBoard)
                if (!nextPiece) {
                    setGameOver(true)
                } else {
                    setPiece(nextPiece)
                }
                return
            }

            // Trigger vanish animation
            const removeSet = new Set(toRemove)
            setClearing(removeSet)
            setBoard(newBoard)

            // After animation, actually clear cells & update score
            if (clearTimer.current) {
                clearTimeout(clearTimer.current)
            }
            clearTimer.current = setTimeout(() => {
                const afterClear: Board = newBoard.map((row, r) =>
                    row.map((cell, c) => (removeSet.has(cellKey(r, c)) ? null : cell))
                )
                setBoard(afterClear)
                setClearing(new Set())
                const newPoints = pointsLeft - removeSet.size
                setPointsLeft(newPoints)
                if (newPoints <= 0) {
                    setGameOver(true)
                    return
                }
                const nextPiece = genPieceForBoard(afterClear)
                if (!nextPiece) {
                    setGameOver(true)
                } else {
                    setPiece(nextPiece)
                }
            }, 350) // matches CSS animation duration
        },
        [board, pointsLeft, gameOver, clearing.size]
    )

    // ------------------------------------------------------------------------
    // Desktop HTML5 drag-and-drop handlers
    const handleDrop = useCallback(
        (e: React.DragEvent<HTMLDivElement>, anchorRow: number, anchorCol: number) => {
            e.preventDefault()
            const payloadText = e.dataTransfer.getData('text/plain')
            if (!payloadText) {
                return
            }
            const { piece: droppedPiece, offset }: DragPayload = JSON.parse(payloadText)
            attemptPlacePiece(anchorRow, anchorCol, droppedPiece, offset)
        },
        [attemptPlacePiece]
    )

    const allowDrop: React.DragEventHandler<HTMLDivElement> = (e) => e.preventDefault()

    const handlePieceDragStart: React.DragEventHandler<HTMLDivElement> = (e) => {
        if (!piece) {
            return
        }
        const rect = (e.currentTarget as HTMLDivElement).getBoundingClientRect()
        const relX = e.clientX - rect.left
        const relY = e.clientY - rect.top

        let offset: 0 | 1 = 0
        if (
            (piece.orientation === 'horizontal' && relX > rect.width / 2) ||
            (piece.orientation === 'vertical' && relY > rect.height / 2)
        ) {
            offset = 1
        }

        const payload: DragPayload = { piece, offset }
        e.dataTransfer.effectAllowed = 'move'
        e.dataTransfer.setData('text/plain', JSON.stringify(payload))
    }

    const restartGame = useCallback(() => {
        // Cancel pending clear animation, if any
        if (clearTimer.current) {
            clearTimeout(clearTimer.current)
            clearTimer.current = null
        }

        const freshBoard = makeEmptyBoard()
        setBoard(freshBoard)
        setPiece(genPieceForBoard(freshBoard))
        setPointsLeft(368)
        setClearing(new Set())
        setGameOver(false)
    }, [])

    // ------------------------------------------------------------------------
    // Mobile / touch support using Pointer events
    const [dragStyle, setDragStyle] = useState<React.CSSProperties>({})
    const dragOffsetPx = useRef<{ x: number; y: number }>({ x: 0, y: 0 })
    const dragOffsetCell = useRef<0 | 1>(0)
    const isTouchDragging = useRef<boolean>(false)

    const onPointerDown = (e: React.PointerEvent<HTMLDivElement>): void => {
        if (e.pointerType === 'mouse' || !piece) {
            return // desktop uses native drag-and-drop or no piece available
        }
        e.preventDefault()

        // Which half of the piece was touched?
        const rect = (e.currentTarget as HTMLDivElement).getBoundingClientRect()
        const relX = e.clientX - rect.left
        const relY = e.clientY - rect.top

        let offset: 0 | 1 = 0
        if (
            (piece.orientation === 'horizontal' && relX > rect.width / 2) ||
            (piece.orientation === 'vertical' && relY > rect.height / 2)
        ) {
            offset = 1
        }
        dragOffsetCell.current = offset
        dragOffsetPx.current = { x: relX, y: relY }
        isTouchDragging.current = true

        // Move the original element with the finger
        setDragStyle({
            position: 'fixed',
            left: e.clientX - relX,
            top: e.clientY - relY,
            zIndex: 1000,
            touchAction: 'none',
        })
        ;(e.currentTarget as HTMLElement).setPointerCapture(e.pointerId)
    }

    const onPointerMove = (e: React.PointerEvent<HTMLDivElement>): void => {
        if (!isTouchDragging.current) {
            return
        }
        e.preventDefault()
        setDragStyle((prev) => ({
            ...prev,
            left: e.clientX - dragOffsetPx.current.x,
            top: e.clientY - dragOffsetPx.current.y,
        }))
    }

    const onPointerUp = (e: React.PointerEvent<HTMLDivElement>): void => {
        if (!isTouchDragging.current) {
            return
        }
        e.preventDefault()

        // Determine which cell the finger is over
        const boardEl = boardRef.current
        if (boardEl) {
            const boardRect = boardEl.getBoundingClientRect()
            const cellSize = boardRect.width / BOARD_SIZE
            const col = Math.floor((e.clientX - boardRect.left) / cellSize)
            const row = Math.floor((e.clientY - boardRect.top) / cellSize)
            attemptPlacePiece(row, col, piece, dragOffsetCell.current)
        }

        // Reset drag state
        isTouchDragging.current = false
        setDragStyle({})
        dragOffsetCell.current = 0
    }

    // ------------------------------------------------------------------------
    // Render helpers
    const isClearing = (r: number, c: number): boolean => clearing.has(cellKey(r, c))

    // ------------------------------------------------------------------------
    return (
        <div className="Game368Hedgehogs">
            <div className="cmg-container">
                <h2 className="flex gap-2 items-center">
                    {gameOver ? (
                        pointsLeft > 0 ? (
                            <>
                                <span>Game over.</span>
                                <LemonButton type="primary" onClick={restartGame}>
                                    Try again?
                                </LemonButton>
                            </>
                        ) : (
                            '🎉 All the hogs are safe! Well done you! 🎉'
                        )
                    ) : (
                        `${pointsLeft} hogs remaining`
                    )}
                    {!gameOver ? (
                        <Tooltip
                            title="Drag the hogs onto the board. Get 3 in a row to save them. Heavily inspired by 368chickens.com"
                            delayMs={0}
                        >
                            <IconInfo className="ml-2" />
                        </Tooltip>
                    ) : null}
                </h2>

                {/* Board */}
                <div className="cmg-board" ref={boardRef}>
                    {board.map((row, r) =>
                        row.map((cell, c) => (
                            <div
                                key={cellKey(r, c)}
                                className={`cmg-cell ${isClearing(r, c) ? 'vanish' : ''}`}
                                onDragOver={allowDrop}
                                onDrop={(e) => handleDrop(e, r, c)}
                            >
                                {cell && <img src={IMAGE_MAP[cell]} alt={cell} />}
                            </div>
                        ))
                    )}
                </div>

                {/* Two-block piece – entire block draggable */}
                {!gameOver && piece && (
                    <div className="cmg-piece-holder">
                        <div
                            className="cmg-piece cmg-board"
                            draggable
                            onDragStart={handlePieceDragStart}
                            onPointerDown={onPointerDown}
                            onPointerMove={onPointerMove}
                            onPointerUp={onPointerUp}
                            // eslint-disable-next-line react/forbid-dom-props
                            style={{
                                flexDirection: piece.orientation === 'horizontal' ? 'row' : 'column',
                                ...dragStyle,
                            }}
                        >
                            {piece.cells.map((emoji, idx) => (
                                <div key={idx} className="cmg-cell piece-cell">
                                    <img src={IMAGE_MAP[emoji]} alt={emoji} />
                                </div>
                            ))}
                        </div>
                    </div>
                )}
            </div>
        </div>
    )
}

export default CritterMatchGame
