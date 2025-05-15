import './368Hedgehogs.scss'

import { IconInfo } from '@posthog/icons'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { useCallback, useRef, useState } from 'react'
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

type Board = (Hog | null)[][] // 6×6 matrix of emoji / empty

// ==========================================================================
// Helpers
const makeEmptyBoard = (): Board => Array.from({ length: BOARD_SIZE }, () => Array<Hog | null>(BOARD_SIZE).fill(null))

const genPiece = (): Piece => {
    const orientation: Orientation = Math.random() < 0.5 ? 'horizontal' : 'vertical'
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
const CritterMatchGame: React.FC = () => {
    const [board, setBoard] = useState<Board>(makeEmptyBoard())
    const [piece, setPiece] = useState<Piece>(genPiece())
    const [pointsLeft, setPointsLeft] = useState<number>(368)
    const [clearing, setClearing] = useState<Set<string>>(new Set())
    const [gameOver, setGameOver] = useState<boolean>(false)

    const clearTimer = useRef<NodeJS.Timeout | null>(null)

    // ------------------------------------------------------------------------
    // Drop handler
    const handleDrop = useCallback(
        (e: React.DragEvent<HTMLDivElement>, anchorRow: number, anchorCol: number) => {
            e.preventDefault()
            if (gameOver || clearing.size) {
                return // don't allow drops during animation
            }

            const payloadText = e.dataTransfer.getData('text/plain')
            if (!payloadText) {
                return
            }
            const { piece: droppedPiece, offset }: DragPayload = JSON.parse(payloadText)
            const { orientation, cells } = droppedPiece

            // Adjust anchor if drag started on the 2nd square
            let anchorR = anchorRow
            let anchorC = anchorCol
            if (offset === 1) {
                if (orientation === 'horizontal') {
                    anchorC -= 1
                } else {
                    anchorR -= 1
                }
            }
            if (anchorR < 0 || anchorC < 0) {
                return
            }

            // Coordinates of second cell
            const row2 = orientation === 'vertical' ? anchorR + 1 : anchorR
            const col2 = orientation === 'horizontal' ? anchorC + 1 : anchorC

            // Bounds & occupancy checks
            if (row2 >= BOARD_SIZE || col2 >= BOARD_SIZE) {
                return
            }
            if (board[anchorR][anchorC] || board[row2][col2]) {
                return
            }

            // Place piece
            const newBoard: Board = board.map((r) => r.slice()) as Board
            newBoard[anchorR][anchorC] = cells[0]
            newBoard[row2][col2] = cells[1]

            // Look for matches
            const toRemove = findMatches(newBoard)
            if (toRemove.length === 0) {
                // No matches – just commit board and new piece
                setBoard(newBoard)
                setPiece(genPiece())
                return
            }

            // Otherwise trigger vanish animation
            const removeSet = new Set(toRemove)
            setClearing(removeSet)
            setBoard(newBoard) // show board with new pieces (they'll animate)

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
                }
                setPiece(genPiece())
            }, 350) // matches CSS animation duration
        },
        [board, piece, pointsLeft, gameOver, clearing.size]
    )

    // ------------------------------------------------------------------------
    // Drag helpers
    const allowDrop: React.DragEventHandler<HTMLDivElement> = (e) => e.preventDefault()

    const handlePieceDragStart: React.DragEventHandler<HTMLDivElement> = (e) => {
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

    // ------------------------------------------------------------------------
    // Render helpers
    const isClearing = (r: number, c: number): boolean => clearing.has(cellKey(r, c))

    // ------------------------------------------------------------------------
    return (
        <div className="Game368Hedgehogs">
            <div className="cmg-container">
                <h2>
                    {gameOver ? '🎉 All the hogs are safe! Well done you! 🎉' : `${pointsLeft} hogs remaining`}
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
                <div className="cmg-board">
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

                {/* Two‑block piece – entire block draggable */}
                {!gameOver && (
                    <div
                        className="cmg-piece cmg-board"
                        draggable
                        onDragStart={handlePieceDragStart}
                        // eslint-disable-next-line react/forbid-dom-props
                        style={
                            {
                                flexDirection: piece.orientation === 'horizontal' ? 'row' : 'column',
                            } as React.CSSProperties
                        }
                    >
                        {piece.cells.map((emoji, idx) => (
                            <div key={idx} className="cmg-cell piece-cell">
                                <img src={IMAGE_MAP[emoji]} alt={emoji} />
                            </div>
                        ))}
                    </div>
                )}
            </div>
        </div>
    )
}

export default CritterMatchGame
