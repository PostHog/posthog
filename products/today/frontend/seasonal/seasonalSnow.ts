const SNOW_MS = 1600
const FLAKE_LIFE_MS = 2600
const MAX_FLAKES = 120
const FLAKE_COLOR = '255, 255, 255'

interface Flake {
    x: number
    y: number
    speed: number
    radius: number
    phase: number
    alpha: number
    born: number
}

export class SeasonalSnow {
    private flakes: Flake[] = []
    private until = 0

    start(now: number): void {
        this.until = now + SNOW_MS
    }

    step(now: number, width: number, height: number): void {
        if (now < this.until && this.flakes.length < MAX_FLAKES) {
            for (let i = 0; i < 2; i++) {
                const depth = Math.random()
                this.flakes.push({
                    x: Math.random() * width,
                    y: -10 - Math.random() * 40,
                    speed: 2.6 + depth * 3,
                    radius: 1.4 + depth * 3,
                    phase: Math.random() * Math.PI * 2,
                    alpha: 0.6 + depth * 0.4,
                    born: now,
                })
            }
        }
        this.flakes = this.flakes.filter((flake) => {
            flake.y += flake.speed
            flake.phase += 0.03
            flake.x += Math.sin(flake.phase) * 0.4
            if (flake.y > height * 0.7 || now - flake.born > FLAKE_LIFE_MS) {
                flake.alpha -= 0.03
            }
            return flake.alpha > 0 && flake.y < height
        })
    }

    draw(context: CanvasRenderingContext2D, card: DOMRect | null): void {
        for (const flake of this.flakes) {
            if (card && flake.x > card.left && flake.x < card.right && flake.y > card.top && flake.y < card.bottom) {
                continue
            }
            context.beginPath()
            context.arc(flake.x, flake.y, flake.radius, 0, Math.PI * 2)
            context.fillStyle = `rgba(${FLAKE_COLOR}, ${flake.alpha})`
            context.fill()
        }
    }
}
