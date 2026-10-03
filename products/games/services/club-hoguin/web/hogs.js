// The hedgehogs: pixel sprites that stand upright in the town and walk smoothly between polls.
import { THREE } from '/kit.js'
import { positionAt } from '/walk.js'

const FRAME_WIDTH = 2.9
// The camera looks down at the town, which makes an upright sprite look short. The extra height undoes that.
const FRAME_HEIGHT = 3.3
// The feet are this far above the bottom edge of a frame, as a share of the frame height.
const FEET = 0.06
const NIGHT_TINT = new THREE.Color(0x8d9bd6)
const WHITE = new THREE.Color(0xffffff)

export async function loadSprites() {
    const [texture, atlas] = await Promise.all([
        new THREE.TextureLoader().loadAsync('/assets/sprites.png'),
        fetch('/assets/sprites.json').then((response) => response.json()),
    ])
    texture.colorSpace = THREE.SRGBColorSpace
    texture.magFilter = THREE.NearestFilter
    texture.minFilter = THREE.NearestFilter
    texture.generateMipmaps = false
    /** @type {Map<string, Array<{ x: number, y: number, w: number, h: number }>>} */
    const animations = new Map()
    for (const name of Object.keys(atlas.frames).sort()) {
        const animation = name.includes('/tile') ? name.slice(0, name.lastIndexOf('/')) : name.replace('.png', '')
        animations.set(animation, [...(animations.get(animation) ?? []), atlas.frames[name].frame])
    }
    return { texture, animations, width: atlas.meta.size.w, height: atlas.meta.size.h }
}

/**
 * @param {ReturnType<typeof import('/town.js').createTown>} town
 * @param {Awaited<ReturnType<typeof loadSprites>>} sprites
 * @param {any} world
 * @param {() => number} serverNow the server clock, estimated
 */
export function createHogs(town, sprites, world, serverNow) {
    const geometry = new THREE.PlaneGeometry(1, 1)
    geometry.translate(0, 0.5 - FEET, 0)
    const shadowGeometry = new THREE.CircleGeometry(0.62, 20)
    const shadowMaterial = new THREE.MeshBasicMaterial({
        color: 0x1b2f55,
        transparent: true,
        opacity: 0.28,
        depthWrite: false,
    })

    function makeLayer() {
        const texture = sprites.texture.clone()
        texture.needsUpdate = true
        const layer = new THREE.Mesh(
            geometry,
            new THREE.MeshBasicMaterial({ map: texture, alphaTest: 0.5, toneMapped: false })
        )
        layer.scale.set(FRAME_WIDTH, FRAME_HEIGHT, 1)
        return layer
    }

    /** @param {THREE.Mesh} layer @param {{ x: number, y: number, w: number, h: number }} frame @param {boolean} flip */
    function showFrame(layer, frame, flip) {
        const map = /** @type {THREE.Texture} */ (/** @type {THREE.MeshBasicMaterial} */ (layer.material).map)
        const w = frame.w / sprites.width
        map.repeat.set(flip ? -w : w, frame.h / sprites.height)
        map.offset.set((flip ? frame.x + frame.w : frame.x) / sprites.width, 1 - (frame.y + frame.h) / sprites.height)
    }

    /** @param {string} skin @param {string} name */
    const animation = (skin, name) =>
        sprites.animations.get(`skins/${skin}/${name}`) ?? sprites.animations.get(`skins/${skin}/idle`) ?? []

    /** @type {Map<string, any>} */
    const hogs = new Map()

    /** @param {any} view */
    function add(view) {
        const group = new THREE.Group()
        const body = makeLayer()
        const shadow = new THREE.Mesh(shadowGeometry, shadowMaterial)
        shadow.rotation.x = -Math.PI / 2
        shadow.position.y = 0.06
        shadow.scale.set(1, 0.6, 1)
        group.add(shadow, body)
        let hat = null
        const hatName = view.hat
        if (hatName) {
            hat = makeLayer()
            hat.position.z = 0.02
            hat.userData.frame = /** @type {any} */ (sprites.animations.get(`accessories/${hatName}`))[0]
            group.add(hat)
        }
        town.scene.add(group)
        const hog = {
            view,
            group,
            body,
            hat,
            x: view.x,
            y: view.y,
            // The walk the hedgehog is on. Its position at any moment follows from this and the clock.
            walk: { from: { x: view.x, y: view.y }, path: view.path ?? [], at: view.at ?? serverNow() },
            facing: view.facing,
            moving: false,
            bubble: /** @type {string | null} */ (view.bubble ?? null),
            bubbleUntil: view.bubble ? serverNow() + world.limits.bubbleMs : 0,
            // An animation that plays once on top of walking and standing, such as a jump or a wave.
            once: /** @type {{ name: string, start: number, fps: number } | null} */ (null),
            sincePrint: 0,
            hiddenUntil: 0,
            bornAt: performance.now() / 1000,
        }
        hogs.set(view.id, hog)
        return hog
    }

    return {
        hogs,
        add,
        /** Takes a full snapshot: hedgehogs that are gone leave, new ones arrive, the rest take the snapshot's walk. */
        sync(/** @type {any[]} */ players, /** @type {number} */ at) {
            const ids = new Set(players.map((player) => player.id))
            for (const [id, hog] of hogs) {
                if (!ids.has(id) && !hog.view.npc) {
                    this.remove(id)
                }
            }
            for (const view of players) {
                const hog = hogs.get(view.id) ?? this.join({ ...view, at })
                hog.view = view
                hog.walk = { from: { x: view.x, y: view.y }, path: view.path, at }
                hog.bubble = view.bubble
                hog.bubbleUntil = view.bubble ? at + world.limits.bubbleMs : 0
            }
        },
        join(/** @type {any} */ view) {
            const hog = add(view)
            town.puff(town.at(view.x, view.y, 1), 0xffffff, 8)
            return hog
        },
        remove(/** @type {string} */ id) {
            const hog = hogs.get(id)
            if (hog) {
                town.puff(town.at(hog.x, hog.y, 1), 0xffffff, 8)
                town.scene.remove(hog.group)
                hogs.delete(id)
            }
        },
        /** @param {string} id @param {{ from: { x: number, y: number }, path: Array<{ x: number, y: number }>, at: number }} walk */
        walk(id, walk) {
            const hog = hogs.get(id)
            if (hog) {
                hog.walk = walk
            }
        },
        /** @param {string} id @param {string} text @param {number} at */
        say(id, text, at) {
            const hog = hogs.get(id)
            if (hog) {
                hog.bubble = text
                hog.bubbleUntil = at + world.limits.bubbleMs
            }
        },
        /** @param {string} id @param {string} name */
        playOnce(id, name, fps = 14) {
            const hog = hogs.get(id)
            if (hog) {
                hog.once = { name, start: performance.now() / 1000, fps }
            }
        },
        /** Hides a hedgehog for a moment, for a walk through a door. */
        hide(/** @type {string} */ id, /** @type {number} */ seconds) {
            const hog = hogs.get(id)
            if (hog) {
                hog.hiddenUntil = performance.now() / 1000 + seconds
            }
        },
        update(/** @type {number} */ dt, /** @type {number} */ time) {
            const tint = WHITE.clone().lerp(NIGHT_TINT, town.nightValue() * 0.55)
            const serverTime = serverNow()
            for (const hog of hogs.values()) {
                if (!hog.view.npc) {
                    const position = positionAt(hog.walk, world.walkSpeed, serverTime)
                    const walked = Math.hypot(position.x - hog.x, position.y - hog.y)
                    hog.x = position.x
                    hog.y = position.y
                    hog.moving = position.moving
                    hog.facing = position.facing ?? hog.facing
                    hog.sincePrint += walked
                    if (hog.moving && hog.sincePrint > 0.7) {
                        hog.sincePrint = 0
                        town.footprint(hog.x + (hog.printSide = -(hog.printSide ?? 1)) * 0.14, hog.y + 0.05)
                    }
                    if (hog.bubble && serverTime > hog.bubbleUntil) {
                        hog.bubble = null
                    }
                }

                let frames = animation(hog.view.skin, hog.moving ? 'walk' : (hog.view.idle ?? 'idle'))
                let index = Math.floor(time * (hog.moving ? 16 : 8)) % Math.max(1, frames.length)
                if (hog.once) {
                    const onceFrames = animation(hog.view.skin, hog.once.name)
                    const onceIndex = Math.floor((time - hog.once.start) * hog.once.fps)
                    if (onceIndex < onceFrames.length && !hog.moving) {
                        frames = onceFrames
                        index = Math.max(0, onceIndex)
                    } else {
                        hog.once = null
                    }
                }
                const flip = hog.facing === 'left'
                showFrame(hog.body, frames[index], flip)
                hog.body.material.color.copy(tint)
                if (hog.hat) {
                    showFrame(hog.hat, hog.hat.userData.frame, flip)
                    hog.hat.material.color.copy(tint)
                    // The head dips on every other walk frame, and the hat goes with it.
                    hog.hat.position.y = hog.moving && index % 2 ? -FRAME_HEIGHT / 80 : 0
                }
                // A new hedgehog pops up from the snow.
                const grown = Math.min(1, (time - hog.bornAt) * 4)
                hog.group.scale.setScalar(0.4 + 0.6 * grown)
                hog.group.visible = time >= hog.hiddenUntil
                hog.group.position.copy(town.at(hog.x, hog.y, 0))
            }
        },
    }
}
