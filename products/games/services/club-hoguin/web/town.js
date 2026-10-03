// Builds Hog Town: the snowy plaza, its buildings, and the things a hedgehog can use.
import {
    box,
    COLORS,
    cone,
    cylinder,
    fitText,
    glow,
    glowMaterials,
    mat,
    mesh,
    pine,
    roundedPanel,
    sign,
    snowCap,
    sphere,
    THREE,
} from '/kit.js'

const DAY = {
    sky: new THREE.Color(0xbfe4ff),
    hemiSky: new THREE.Color(0xe6f3ff),
    hemiGround: new THREE.Color(0xb9cbe6),
    sun: new THREE.Color(0xfff1d6),
}
const NIGHT = {
    sky: new THREE.Color(0x101a3f),
    hemiSky: new THREE.Color(0x4a5fae),
    hemiGround: new THREE.Color(0x1c2550),
    sun: new THREE.Color(0x9fb6ff),
}

/**
 * @param {any} world the world description from the server
 * @param {HTMLCanvasElement} canvas
 */
export function createTown(world, canvas) {
    const halfWidth = world.width / 2
    const halfDepth = world.depth / 2
    // Town units to scene coordinates: x runs east, y runs south, and height runs up.
    const at = (/** @type {number} */ x, /** @type {number} */ y, height = 0) =>
        new THREE.Vector3(x - halfWidth, height, y - halfDepth)
    const place = (
        /** @type {THREE.Object3D} */ object,
        /** @type {number} */ x,
        /** @type {number} */ y,
        height = 0
    ) => {
        object.position.copy(at(x, y, height))
        scene.add(object)
        return object
    }

    const renderer = new THREE.WebGLRenderer({ canvas, antialias: true })
    renderer.outputColorSpace = THREE.SRGBColorSpace
    renderer.toneMapping = THREE.NeutralToneMapping
    renderer.toneMappingExposure = 1
    renderer.shadowMap.enabled = true
    renderer.shadowMap.type = THREE.PCFSoftShadowMap

    const scene = new THREE.Scene()
    scene.background = DAY.sky.clone()
    scene.fog = new THREE.Fog(DAY.sky.clone(), 60, 150)

    const camera = new THREE.PerspectiveCamera(26, 16 / 9, 1, 400)

    const hemisphere = new THREE.HemisphereLight(DAY.hemiSky, DAY.hemiGround, 1.25)
    const sun = new THREE.DirectionalLight(DAY.sun, 3)
    sun.position.set(-16, 30, 20)
    sun.castShadow = true
    sun.shadow.mapSize.set(2048, 2048)
    sun.shadow.camera.left = -27
    sun.shadow.camera.right = 27
    sun.shadow.camera.top = 22
    sun.shadow.camera.bottom = -22
    sun.shadow.camera.near = 1
    sun.shadow.camera.far = 90
    sun.shadow.bias = -0.0006
    sun.shadow.normalBias = 0.04
    scene.add(hemisphere, sun, sun.target)

    /** @type {Array<(dt: number, time: number) => void>} */
    const animations = []
    /** @type {Array<{ light: THREE.PointLight, day: number, night: number }>} */
    const lamps = []
    const lamp = (
        /** @type {number} */ color,
        /** @type {number} */ day,
        /** @type {number} */ night,
        distance = 14
    ) => {
        const light = new THREE.PointLight(color, day, distance, 1.6)
        lamps.push({ light, day, night })
        return light
    }

    // ---- Ground -----------------------------------------------------------------------------------------------
    const snow = mat(COLORS.snow, { flatShading: false, roughness: 1 })
    const ground = mesh(new THREE.CircleGeometry(170, 48), snow, [0, 0, 0], {
        rotation: [-Math.PI / 2, 0, 0],
        cast: false,
        receive: false,
    })
    scene.add(ground)

    // Trodden paths and the plaza, drawn on a canvas that lies on the snow.
    const paths = sign(world.width, world.depth, 26, (g, w) => {
        const u = w / world.width
        g.lineCap = 'round'
        g.lineJoin = 'round'
        const stroke = (
            /** @type {Array<[number, number]>} */ points,
            /** @type {number} */ width,
            /** @type {string} */ color
        ) => {
            g.beginPath()
            points.forEach(([x, y], index) => (index ? g.lineTo(x * u, y * u) : g.moveTo(x * u, y * u)))
            g.lineWidth = width * u
            g.strokeStyle = color
            g.stroke()
        }
        const street = /** @type {Array<[number, number]>} */ ([
            [3, 6.2],
            [37, 6.2],
        ])
        const spokes = world.objects.map((/** @type {any} */ object) => [
            [world.campfire.x, world.campfire.y + 3.2],
            [object.stand.x, object.stand.y],
        ])
        for (const [width, color] of /** @type {Array<[number, string]>} */ ([
            [2.6, 'rgba(176, 198, 224, 0.55)'],
            [1.9, 'rgba(203, 219, 238, 0.9)'],
        ])) {
            stroke(street, width, color)
            spokes.forEach((/** @type {any} */ spoke) => stroke(spoke, width * 0.7, color))
            g.beginPath()
            g.arc(world.campfire.x * u, world.campfire.y * u, (2.9 + width * 0.5) * u, 0, Math.PI * 2)
            g.fillStyle = color
            g.fill()
        }
        // Flagstones around the fire.
        for (let ring = 0; ring < 2; ring++) {
            const count = 10 + ring * 6
            for (let index = 0; index < count; index++) {
                const angle = (index / count) * Math.PI * 2 + ring * 0.3
                const radius = 1.9 + ring * 0.95
                g.beginPath()
                g.ellipse(
                    (world.campfire.x + Math.cos(angle) * radius) * u,
                    (world.campfire.y + Math.sin(angle) * radius) * u,
                    0.42 * u,
                    0.3 * u,
                    angle,
                    0,
                    Math.PI * 2
                )
                g.fillStyle = index % 2 ? 'rgba(150, 164, 186, 0.75)' : 'rgba(168, 180, 200, 0.75)'
                g.fill()
            }
        }
        // A carpet in front of the cinema.
        g.fillStyle = 'rgba(214, 48, 49, 0.85)'
        g.fillRect(12.4 * u, 4.4 * u, 2.2 * u, 1.9 * u)
    })
    paths.board.material.toneMapped = true
    paths.board.rotation.x = -Math.PI / 2
    paths.board.position.set(0, 0.02, 0)
    paths.board.receiveShadow = false
    scene.add(paths.board)
    // The path board is unlit, so one shadow catcher above it shows the shadows on the snow and on the paths.
    const shadowCatcher = mesh(
        new THREE.PlaneGeometry(130, 100),
        new THREE.ShadowMaterial({ color: 0x2c4a7c, opacity: 0.42 }),
        [0, 0.04, 0],
        { rotation: [-Math.PI / 2, 0, 0], cast: false }
    )
    scene.add(shadowCatcher)

    // ---- Pond ---------------------------------------------------------------------------------------------------
    const pond = world.pond
    const ice = mesh(
        new THREE.CircleGeometry(1, 40),
        new THREE.MeshStandardMaterial({ color: COLORS.ice, roughness: 0.12, metalness: 0.15 }),
        [0, 0.05, 0],
        { rotation: [-Math.PI / 2, 0, 0], scale: [pond.rx, pond.ry, 1], cast: false }
    )
    place(ice, pond.x, pond.y, 0.05)
    for (let index = 0; index < 26; index++) {
        const angle = (index / 26) * Math.PI * 2
        const lump = mesh(sphere(0.55, 1), snow, [0, 0, 0], {
            scale: [1 + (index % 3) * 0.18, 0.5 + (index % 2) * 0.12, 0.9],
            cast: false,
        })
        place(lump, pond.x + Math.cos(angle) * (pond.rx + 0.3), pond.y + Math.sin(angle) * (pond.ry + 0.3), 0.05)
    }
    for (const [dx, dy, length, turn] of [
        [-1.6, -0.4, 2.2, 0.5],
        [0.8, 0.5, 2.8, -0.3],
        [1.9, -0.9, 1.5, 1.1],
    ]) {
        place(
            mesh(box(length, 0.01, 0.05), mat(0xffffff, { transparent: true, opacity: 0.7 }), [0, 0, 0], {
                rotation: [0, turn, 0],
                cast: false,
            }),
            pond.x + dx,
            pond.y + dy,
            0.07
        )
    }

    // ---- Campfire -----------------------------------------------------------------------------------------------
    const fire = new THREE.Group()
    for (let index = 0; index < 9; index++) {
        const angle = (index / 9) * Math.PI * 2
        fire.add(mesh(sphere(0.28, 0), mat(COLORS.stone), [Math.cos(angle) * 0.95, 0.14, Math.sin(angle) * 0.95]))
    }
    for (let index = 0; index < 3; index++) {
        fire.add(
            mesh(cylinder(0.13, 0.13, 1.3, 6), mat(COLORS.woodDark), [0, 0.22, 0], {
                rotation: [Math.PI / 2, 0, (index / 3) * Math.PI],
            })
        )
    }
    const flames = [
        mesh(cone(0.5, 1.3, 7), glow(0xff7a1a, 1.6, 2.2, { transparent: true, opacity: 0.92 }), [0, 0.85, 0], {
            cast: false,
        }),
        mesh(cone(0.32, 0.95, 7), glow(0xffc93c, 2, 2.6), [0.08, 0.75, 0.05], { cast: false }),
        mesh(cone(0.22, 0.7, 6), glow(0xfff2b0, 2.2, 2.8), [-0.1, 0.6, -0.06], { cast: false }),
    ]
    fire.add(...flames)
    const fireLight = lamp(0xff9a3c, 6, 34, 15)
    fireLight.position.set(0, 1.4, 0)
    fire.add(fireLight)
    fire.scale.setScalar(1.25)
    place(fire, world.campfire.x, world.campfire.y)
    animations.push((_dt, time) => {
        flames.forEach((flame, index) => {
            const flicker = 1 + Math.sin(time * (9 + index * 3) + index) * 0.12
            flame.scale.set(1 + Math.sin(time * 7 + index) * 0.06, flicker, 1)
            flame.rotation.y = time * (1.5 + index)
        })
    })

    // ---- Backdrop: trees, mountains, fence -----------------------------------------------------------------------
    const treeSpots = [
        [-1.6, 0.5, 5.2],
        [0.4, 3.2, 4.2],
        [7.4, 0.2, 5.6],
        [19.9, 0.4, 5.2],
        [30.4, 0.3, 5.8],
        [39.3, 2.4, 4.6],
        [41.6, 0.4, 5.6],
        [-2.2, 6.5, 4.8],
        [-0.6, 10.5, 4],
        [-2.6, 14, 5.2],
        [-0.8, 18.5, 4.4],
        [-3.2, 21.5, 5],
        [41.2, 7, 4.6],
        [42.8, 11, 5.4],
        [40.9, 15.5, 4.2],
        [42.4, 19.5, 5],
        [41, 22.8, 4.4],
        [3.5, -2.5, 6],
        [12, -3, 6.6],
        [16.5, -2.4, 5.6],
        [24, -3.2, 6.4],
        [28.5, -2.2, 5.8],
        [35.5, -3, 6.6],
        [-5, -1, 6.4],
        [45, -2, 6.6],
        [-6.5, 9, 6],
        [46, 8, 6.2],
        [-6, 17, 5.6],
        [46.5, 16, 5.8],
        [8, -6, 7],
        [21, -6.5, 7.4],
        [33, -6, 7.2],
        [-9, 3, 7],
        [49, 3, 7],
    ]
    /** @type {THREE.Group[]} */
    const pines = []
    treeSpots.forEach(([x, y, height], index) => pines.push(place(pine(height, index % 3 === 0), x, y)))
    // Snow hills and pale peaks close the horizon behind the trees.
    for (const [x, y, radius, height] of [
        [-22, -16, 26, 9],
        [8, -22, 30, 11],
        [38, -20, 28, 10],
        [66, -14, 26, 9],
        [-40, 6, 20, 8],
        [80, 8, 20, 8],
    ]) {
        place(
            mesh(sphere(1, 2), mat(0xe9f1fa, { flatShading: false, roughness: 1 }), [0, 0, 0], {
                scale: [radius, height, radius * 0.6],
                cast: false,
            }),
            x,
            y,
            -2
        )
    }
    for (const [x, y, radius, height] of [
        [-6, -70, 22, 34],
        [22, -80, 26, 42],
        [50, -72, 22, 36],
        [-34, -62, 20, 28],
        [78, -60, 20, 28],
    ]) {
        const peak = new THREE.Group()
        peak.add(mesh(cone(radius, height, 6), mat(0xa9bfe2), [0, height / 2, 0], { cast: false, receive: false }))
        peak.add(
            mesh(cone(radius * 0.5, height * 0.5, 6), mat(0xffffff), [0, height * 0.752, 0], {
                cast: false,
                receive: false,
            })
        )
        peak.rotation.y = x
        place(peak, x, y, -3)
    }
    // A low fence along the south edge. It stays below the hedgehogs, so it does not hide them.
    for (let x = 0.5; x <= 39.5; x += 3) {
        place(mesh(box(0.22, 0.75, 0.22), mat(COLORS.wood), [0, 0, 0]), x, 21.9, 0.37)
        if (x + 3 <= 39.5) {
            place(mesh(box(3, 0.13, 0.1), mat(COLORS.wood), [0, 0, 0]), x + 1.5, 21.9, 0.55)
            place(mesh(box(3, 0.08, 0.16), snow, [0, 0, 0], { cast: false }), x + 1.5, 21.9, 0.65)
        }
    }
    // Lamp posts stand where hedgehogs cannot walk.
    for (const [x, y] of [
        [19.9, 4.3],
        [30.4, 4.3],
        [0.3, 12],
        [39.7, 12],
        [0.3, 20.4],
        [39.7, 20.4],
    ]) {
        const post = new THREE.Group()
        post.add(mesh(cylinder(0.08, 0.11, 3, 6), mat(0x2b3040), [0, 1.5, 0]))
        post.add(mesh(sphere(0.34, 1), glow(0xffe2a8, 0.35, 3.4), [0, 3.15, 0], { cast: false }))
        post.add(mesh(sphere(0.24, 1), snow, [0, 3.45, 0], { scale: [1, 0.4, 1], cast: false }))
        const light = lamp(0xffd39a, 0, 12, 9)
        light.position.set(0, 2.8, 0)
        post.add(light)
        place(post, x, y)
    }

    // ---- Things in the square that hedgehogs walk around -----------------------------------------------------------
    /** @type {THREE.Group[]} */
    const snowmen = []
    for (const decoration of world.decorations) {
        const group = new THREE.Group()
        if (decoration.kind === 'bench') {
            group.add(
                mesh(cylinder(0.32, 0.32, 1.9, 8), mat(COLORS.wood), [0, 0.34, 0], { rotation: [Math.PI / 2, 0, 0] })
            )
            group.add(mesh(box(0.42, 0.1, 1.7), snow, [0, 0.68, 0], { cast: false }))
            for (const z of [-0.96, 0.96]) {
                group.add(
                    mesh(cylinder(0.33, 0.33, 0.03, 8), mat(0xd9a877), [0, 0.34, z], { rotation: [Math.PI / 2, 0, 0] })
                )
            }
        } else if (decoration.kind === 'snowman') {
            snowmen.push(group)
            group.add(mesh(sphere(0.62, 2), snow, [0, 0.52, 0]))
            group.add(mesh(sphere(0.44, 2), snow, [0, 1.36, 0]))
            group.add(mesh(sphere(0.32, 2), snow, [0, 2, 0]))
            group.add(mesh(cone(0.07, 0.34, 6), mat(COLORS.orange), [0, 2, 0.4], { rotation: [Math.PI / 2, 0, 0] }))
            for (const x of [-0.11, 0.11]) {
                group.add(mesh(sphere(0.045, 0), mat(COLORS.ink), [x, 2.1, 0.28]))
            }
            group.add(
                mesh(new THREE.TorusGeometry(0.3, 0.09, 6, 14), mat(COLORS.red), [0, 1.72, 0], {
                    rotation: [Math.PI / 2, 0, 0],
                })
            )
            // Quills on its back make it a snow hedgehog.
            for (let quill = 0; quill < 7; quill++) {
                const angle = Math.PI + (quill - 3) * 0.32
                group.add(
                    mesh(
                        cone(0.07, 0.36, 5),
                        mat(COLORS.woodDark),
                        [Math.sin(angle) * 0.42, 1.5 + (quill % 2) * 0.22, Math.cos(angle) * 0.42],
                        { rotation: [-1.2, angle, 0] }
                    )
                )
            }
            for (const side of [-1, 1]) {
                group.add(
                    mesh(cylinder(0.03, 0.03, 0.7, 5), mat(COLORS.woodDark), [side * 0.62, 1.5, 0], {
                        rotation: [0, 0, side * -1.1],
                    })
                )
            }
        } else if (decoration.kind === 'tree') {
            const tree = pine(3.4)
            pines.push(tree)
            group.add(tree)
        } else {
            group.add(mesh(cylinder(0.08, 0.1, 2.8, 6), mat(COLORS.woodDark), [0, 1.4, 0]))
            const arrows = /** @type {Array<[string, number, string]>} */ ([
                ['← Bug jar', 2.45, '#f54e00'],
                ['Cinema ↑', 1.85, '#1d4aff'],
                ['Ship it →', 1.25, '#2ba84a'],
            ])
            for (const [text, height, color] of arrows) {
                const arrow = sign(2.2, 0.5, 110, (g, w, h) => {
                    roundedPanel(g, 4, 4, w - 8, h - 8, 14, color, '#151515', 6)
                    fitText(g, text, w / 2, h / 2 + 2, w * 0.86, 34, '#ffffff')
                })
                arrow.board.position.set(0, height, 0.12)
                group.add(arrow.board)
            }
            group.add(mesh(sphere(0.16, 1), snow, [0, 2.84, 0], { scale: [1, 0.5, 1], cast: false }))
        }
        place(group, decoration.x, decoration.y)
    }

    // ---- Buildings ----------------------------------------------------------------------------------------------
    /** @type {Record<string, any>} */
    const objects = Object.fromEntries(world.objects.map((/** @type {any} */ object) => [object.id, object]))
    /** @type {Array<{ id: string, hit: THREE.Mesh, label: THREE.Vector3 }>} */
    const interactables = []
    const addHit = (
        /** @type {string} */ id,
        /** @type {number} */ x,
        /** @type {number} */ y,
        /** @type {number} */ w,
        /** @type {number} */ h,
        /** @type {number} */ d,
        /** @type {number} */ labelHeight
    ) => {
        const hit = mesh(box(w, h, d), new THREE.MeshBasicMaterial({ visible: false }), [0, 0, 0], {
            cast: false,
            receive: false,
        })
        place(hit, x, y, h / 2)
        interactables.push({ id, hit, label: at(x, y, labelHeight) })
    }
    const window_ = glow(0xffe9a8, 0.15, 2.4)

    // Feature flag lighthouse.
    {
        const tower = new THREE.Group()
        tower.add(mesh(cylinder(1.75, 1.95, 0.7, 14), mat(COLORS.stone), [0, 0.35, 0]))
        const bands = 5
        for (let band = 0; band < bands; band++) {
            const bottom = 1.55 - band * 0.13
            tower.add(
                mesh(cylinder(bottom - 0.13, bottom, 1.15, 14), mat(band % 2 ? 0xffffff : COLORS.yellow), [
                    0,
                    1.27 + band * 1.15,
                    0,
                ])
            )
        }
        tower.add(mesh(cylinder(1.35, 1.35, 0.16, 14), mat(0x2b3040), [0, 6.5, 0]))
        const lampRoom = mesh(cylinder(0.72, 0.72, 1, 10), glow(0xfff0a0, 0.5, 3.4), [0, 7.08, 0], { cast: false })
        tower.add(lampRoom)
        tower.add(mesh(cone(1.05, 0.95, 10), mat(COLORS.orange), [0, 8.05, 0]))
        tower.add(mesh(cone(0.75, 0.5, 10), snow, [0, 8.4, 0], { cast: false }))
        tower.add(mesh(box(0.8, 1.4, 0.2), mat(0x24306b), [0, 1.2, 1.5]))
        tower.add(mesh(box(0.5, 0.6, 0.1), window_, [0, 3.6, 1.26]))
        tower.add(mesh(box(0.45, 0.55, 0.1), window_, [0, 5.3, 1.02]))
        const beam = new THREE.Group()
        const beamMaterial = new THREE.MeshBasicMaterial({
            color: 0xfff3b0,
            transparent: true,
            opacity: 0,
            depthWrite: false,
        })
        for (const direction of [1, -1]) {
            beam.add(
                mesh(cone(1.5, 13, 10), beamMaterial, [direction * 6.8, 0, 0], {
                    rotation: [0, 0, (direction * Math.PI) / 2],
                    cast: false,
                    receive: false,
                })
            )
        }
        beam.position.set(0, 7.1, 0)
        tower.add(beam)
        const towerLight = lamp(0xffe9a0, 0, 16, 12)
        towerLight.position.set(0, 7.1, 1.2)
        tower.add(towerLight)
        place(tower, 4.25, 2.75)
        animations.push((dt) => {
            beam.rotation.y += dt * 0.9
            beamMaterial.opacity = 0.2 * night.value
        })

        // The lever and the flag switch board.
        const lever = new THREE.Group()
        lever.add(mesh(box(1.1, 0.55, 0.8), mat(0x2b3040), [0, 0.28, 0]))
        lever.add(mesh(box(1.1, 0.12, 0.8), mat(COLORS.yellow), [0, 0.6, 0]))
        const arm = new THREE.Group()
        arm.add(mesh(cylinder(0.07, 0.07, 1.25, 6), mat(0xd9dee8), [0, 0.62, 0]))
        arm.add(mesh(sphere(0.2, 1), mat(COLORS.red), [0, 1.3, 0]))
        arm.position.set(0, 0.55, 0)
        lever.add(arm)
        place(lever, 6.5, 4.45)
        // The switch board hangs on the front of the tower.
        const board = sign(3.6, 1.55, 110, () => undefined)
        board.board.position.copy(at(4.25, 4.42, 3.25))
        scene.add(board.board)
        objectViews.flag = (/** @type {any} */ state) => {
            leverTarget = state.lightsOn ? 0.6 : -0.6
            board.redraw((g, w, h) => {
                roundedPanel(g, 6, 6, w - 12, h - 12, 26, '#fffdf6', '#151515', 8)
                const on = !state.lightsOn
                fitText(g, 'night-mode', w / 2, h * 0.3, w * 0.84, 70, '#151515')
                roundedPanel(g, w * 0.2, h * 0.56, w * 0.3, h * 0.3, h * 0.15, on ? '#2ba84a' : '#b8bcc4', null)
                g.beginPath()
                g.arc(on ? w * 0.43 : w * 0.27, h * 0.71, h * 0.115, 0, Math.PI * 2)
                g.fillStyle = '#ffffff'
                g.fill()
                fitText(g, on ? 'ON' : 'OFF', w * 0.68, h * 0.72, w * 0.3, 60, on ? '#2ba84a' : '#6b6f76')
            })
        }
        let leverTarget = 0.6
        animations.push((dt) => {
            arm.rotation.z += (leverTarget - arm.rotation.z) * Math.min(1, dt * 10)
        })
        addHit('flag', 5.2, 3.6, 6.4, 8.5, 3.6, 9.4)
    }

    // Alerts lighthouse. Its alarm flips fire-mode, which is separate from night.
    const fireMode = { value: 0, target: 0 }
    {
        const tower = new THREE.Group()
        tower.add(mesh(cylinder(1.3, 1.45, 0.5, 14), mat(COLORS.stone), [0, 0.25, 0]))
        for (let band = 0; band < 5; band++) {
            const bottom = 1.15 - band * 0.1
            tower.add(
                mesh(cylinder(bottom - 0.1, bottom, 0.85, 14), mat(band % 2 ? COLORS.ink : COLORS.red), [
                    0,
                    0.92 + band * 0.85,
                    0,
                ])
            )
        }
        tower.add(mesh(cylinder(1, 1, 0.14, 14), mat(0x2b3040), [0, 4.77, 0]))
        const lampRoomMaterial = mat(0xff7a1f, { emissive: 0xff4d00, emissiveIntensity: 0.25 })
        tower.add(mesh(cylinder(0.54, 0.54, 0.75, 10), lampRoomMaterial, [0, 5.2, 0], { cast: false }))
        tower.add(mesh(cone(0.8, 0.7, 10), mat(COLORS.ink), [0, 5.95, 0]))
        tower.add(mesh(box(0.6, 1.05, 0.2), mat(0x3a1414), [0, 0.9, 1.1]))
        tower.add(mesh(box(0.4, 0.45, 0.1), window_, [0, 2.7, 0.95]))
        // The flame on top shows while fire-mode is on.
        const flameMaterial = new THREE.MeshBasicMaterial({ color: 0xffb13b, transparent: true, opacity: 0.95 })
        const flame = new THREE.Group()
        flame.add(mesh(cone(0.55, 1.6, 7), flameMaterial, [0, 0.8, 0], { cast: false, receive: false }))
        flame.add(
            mesh(cone(0.3, 1, 7), new THREE.MeshBasicMaterial({ color: 0xff4d00 }), [0, 0.5, 0], {
                cast: false,
                receive: false,
            })
        )
        flame.position.set(0, 6.3, 0)
        tower.add(flame)
        const alarmLight = new THREE.PointLight(0xff6a1f, 0, 16, 1.6)
        alarmLight.position.set(0, 5.4, 1.2)
        tower.add(alarmLight)
        place(tower, 10.75, 15.9)

        // The alarm lever and the fire-mode board, like the feature flag's.
        const lever = new THREE.Group()
        lever.add(mesh(box(1.1, 0.55, 0.8), mat(0x3a1414), [0, 0.28, 0]))
        lever.add(mesh(box(1.1, 0.12, 0.8), mat(COLORS.red), [0, 0.6, 0]))
        const arm = new THREE.Group()
        arm.add(mesh(cylinder(0.07, 0.07, 1.25, 6), mat(0xd9dee8), [0, 0.62, 0]))
        arm.add(mesh(sphere(0.2, 1), mat(COLORS.yellow), [0, 1.3, 0]))
        arm.position.set(0, 0.55, 0)
        lever.add(arm)
        place(lever, 12.9, 17.2)
        const board = sign(3, 1.3, 110, () => undefined)
        board.board.position.copy(at(10.75, 17.5, 2.45))
        scene.add(board.board)
        let leverTarget = 0.6
        objectViews.fire = (/** @type {any} */ state) => {
            leverTarget = state.fireOn ? -0.6 : 0.6
            board.redraw((g, w, h) => {
                roundedPanel(g, 6, 6, w - 12, h - 12, 26, '#fffdf6', '#151515', 8)
                const on = state.fireOn
                fitText(g, 'fire-mode', w / 2, h * 0.3, w * 0.84, 70, '#151515')
                roundedPanel(g, w * 0.2, h * 0.56, w * 0.3, h * 0.3, h * 0.15, on ? '#f54e00' : '#b8bcc4', null)
                g.beginPath()
                g.arc(on ? w * 0.43 : w * 0.27, h * 0.71, h * 0.115, 0, Math.PI * 2)
                g.fillStyle = '#ffffff'
                g.fill()
                fitText(g, on ? 'ON' : 'OFF', w * 0.68, h * 0.72, w * 0.3, 60, on ? '#f54e00' : '#6b6f76')
            })
        }
        animations.push((dt, time) => {
            arm.rotation.z += (leverTarget - arm.rotation.z) * Math.min(1, dt * 10)
            const flicker = 0.8 + 0.2 * Math.sin(time * 23) * Math.sin(time * 7.3)
            flame.visible = fireMode.value > 0.02
            flame.scale.set(fireMode.value, fireMode.value * flicker, fireMode.value)
            alarmLight.intensity = 14 * fireMode.value * flicker
            lampRoomMaterial.emissiveIntensity = 0.25 + 2.4 * fireMode.value * flicker
        })
        addHit('fire', 11.4, 16.3, 5.2, 7, 3.4, 7.6)
    }

    // Replay cinema.
    {
        const cinema = new THREE.Group()
        cinema.add(mesh(box(10, 4.4, 4), mat(COLORS.blue), [0, 2.2, 0]))
        cinema.add(mesh(box(10.2, 0.5, 4.2), mat(0x12309e), [0, 0.25, 0]))
        const roofSnow = snowCap(10, 4, 7)
        roofSnow.position.y = 4.4
        cinema.add(roofSnow)
        cinema.add(mesh(box(8.6, 2.2, 0.5), mat(0xfff6e5), [0, 3.05, 2.1]))
        // Bulbs around the marquee. They chase each other.
        /** @type {THREE.Mesh[]} */
        const bulbs = []
        const bulbMaterials = [glow(0xffd23f, 1.2, 3.2), glow(0xff6b6b, 1.2, 3.2), glow(0xffffff, 1.2, 3.2)]
        for (let index = 0; index < 18; index++) {
            for (const y of [2.05, 4.05]) {
                const bulb = mesh(sphere(0.1, 1), bulbMaterials[index % 3], [-4.1 + index * (8.2 / 17), y, 2.4], {
                    cast: false,
                })
                bulbs.push(bulb)
                cinema.add(bulb)
            }
        }
        animations.push((_dt, time) => {
            bulbs.forEach((bulb, index) =>
                bulb.scale.setScalar(0.8 + 0.5 * Math.max(0, Math.sin(time * 5 - index * 0.6)))
            )
        })
        cinema.add(mesh(box(2.4, 2, 0.2), mat(0x0d1b52), [-1, 1, 2.02]))
        cinema.add(mesh(box(1.05, 1.8, 0.1), mat(0x2a3f9c), [-1.58, 0.95, 2.12]))
        cinema.add(mesh(box(1.05, 1.8, 0.1), mat(0x2a3f9c), [-0.42, 0.95, 2.12]))
        for (const [x, color] of [
            [2.4, 0xf9bd2b],
            [3.9, 0xf54e00],
        ]) {
            cinema.add(mesh(box(1.1, 1.5, 0.08), mat(0x151515), [x, 1.15, 2.03]))
            cinema.add(mesh(box(0.94, 1.34, 0.08), glow(color, 0.3, 1.2), [x, 1.15, 2.06]))
        }
        const light = lamp(0xfff0c8, 0, 16, 11)
        light.position.set(0, 2.6, 4)
        cinema.add(light)
        place(cinema, 13.5, 2.5)

        const screen = sign(8.2, 1.8, 90, () => undefined)
        screen.board.position.copy(at(13.5, 4.86, 3.05))
        scene.add(screen.board)
        const title = sign(7.4, 1.2, 80, (g, w, h) => {
            roundedPanel(g, 5, 5, w - 10, h - 10, 22, '#151515', '#f9bd2b', 7)
            fitText(g, '🎬 REPLAY CINEMA', w / 2, h / 2 + 2, w * 0.86, 56, '#fff6e5')
        })
        title.board.position.copy(at(13.5, 4.3, 5.25))
        scene.add(title.board)
        objectViews.replay = (/** @type {any} */ state) => {
            screen.redraw((g, w, h) => {
                g.fillStyle = '#101426'
                g.fillRect(0, 0, w, h)
                if (state.nowPlaying) {
                    fitText(g, 'NOW PLAYING', w / 2, h * 0.2, w * 0.9, 32, '#f9bd2b')
                    fitText(g, state.nowPlaying, w / 2, h * 0.63, w * 0.92, 48, '#ffffff', 2)
                } else {
                    fitText(g, 'Now showing: session replays', w / 2, h * 0.38, w * 0.9, 50, '#ffffff')
                    fitText(g, 'Click to put the next one on', w / 2, h * 0.76, w * 0.9, 36, '#9fb0ff', 1, 'normal')
                }
            })
        }
        addHit('replay', 13.5, 2.8, 10, 5.4, 4.6, 6.6)
    }

    // Experiments lab, with door A and door B.
    /** @type {Record<string, { panel: THREE.Group, open: number }>} */
    const doors = {}
    {
        const lab = new THREE.Group()
        lab.add(mesh(box(8, 3.7, 3.5), mat(0xe9f3f6), [0, 1.85, 0]))
        lab.add(mesh(box(8.2, 0.5, 3.7), mat(0x9fb4c0), [0, 0.25, 0]))
        lab.add(mesh(box(8.2, 0.45, 3.7), mat(COLORS.teal), [0, 3.55, 0]))
        const roofSnow = snowCap(8, 3.5, 6)
        roofSnow.position.y = 3.78
        lab.add(roofSnow)
        lab.add(mesh(box(0.9, 0.9, 0.1), window_, [0, 2.1, 1.78]))
        // A flask on the roof, with bubbles.
        const flask = new THREE.Group()
        flask.add(
            mesh(cone(0.75, 1.2, 10), glow(0x5ee0a0, 0.5, 1.8, { transparent: true, opacity: 0.85 }), [0, 0.6, 0])
        )
        flask.add(mesh(cylinder(0.18, 0.18, 0.6, 8), mat(0xdff6ff, { transparent: true, opacity: 0.8 }), [0, 1.4, 0]))
        const bubbles = [0, 1, 2].map(() => {
            const bubble = mesh(sphere(0.1, 1), glow(0xbfffe0, 1, 2.4), [0, 1.7, 0], { cast: false })
            flask.add(bubble)
            return bubble
        })
        animations.push((_dt, time) => {
            bubbles.forEach((bubble, index) => {
                const phase = (time * 0.7 + index / 3) % 1
                bubble.position.set(Math.sin(time * 2 + index * 2) * 0.15, 1.7 + phase * 1.1, 0)
                bubble.scale.setScalar(1 - phase * 0.7)
            })
        })
        flask.position.set(3.2, 4, 0.2)
        lab.add(flask)
        place(lab, 25, 2.75)

        for (const [id, letter, color] of /** @type {Array<[string, string, number]>} */ ([
            ['door-a', 'A', COLORS.teal],
            ['door-b', 'B', COLORS.orange],
        ])) {
            const x = objects[id].footprint.x + objects[id].footprint.w / 2
            place(mesh(box(2.1, 2.9, 0.16), mat(0x24303a), [0, 0, 0]), x, 4.52, 1.45)
            // The panel turns on its west edge.
            const panel = new THREE.Group()
            panel.add(mesh(box(1.7, 2.6, 0.12), mat(color), [0.85, 1.3, 0]))
            panel.add(mesh(sphere(0.1, 1), mat(COLORS.yellow), [1.45, 1.25, 0.1]))
            panel.position.copy(at(x - 0.85, 4.64, 0))
            scene.add(panel)
            doors[id] = { panel, open: 0 }
            const plate = sign(1.5, 1.5, 100, (g, w, h) => {
                g.beginPath()
                g.arc(w / 2, h / 2, w * 0.45, 0, Math.PI * 2)
                g.fillStyle = `#${color.toString(16).padStart(6, '0')}`
                g.fill()
                g.lineWidth = 10
                g.strokeStyle = '#ffffff'
                g.stroke()
                fitText(g, letter, w / 2, h / 2 + 6, w, 100, '#ffffff')
            })
            plate.board.position.copy(at(x, 4.72, 3.25))
            scene.add(plate.board)
            addHit(id, x, 4.3, 2.3, 3.2, 1.4, 4.6)
        }
        animations.push((dt) => {
            Object.values(doors).forEach((door) => {
                door.open = Math.max(0, door.open - dt)
                const target = door.open > 0 ? -1.9 : 0
                door.panel.rotation.y += (target - door.panel.rotation.y) * Math.min(1, dt * 9)
            })
        })
        const scoreboard = sign(8, 3.1, 90, () => undefined)
        scoreboard.board.position.copy(at(25, 4.3, 6))
        scene.add(scoreboard.board)
        for (const x of [21.6, 27.2]) {
            scene.add(mesh(cylinder(0.07, 0.07, 1, 6), mat(0x2b3040), at(x, 4.25, 4.2).toArray()))
        }
        objectViews.doors = (/** @type {any} */ state) => {
            scoreboard.redraw((g, w, h) => {
                roundedPanel(g, 5, 5, w - 10, h - 10, 24, '#fffdf6', '#151515', 8)
                fitText(g, '🧪 EXPERIMENT: door A or door B?', w / 2, h * 0.17, w * 0.9, 46, '#151515')
                const total = state.doorA + state.doorB
                const rows = /** @type {Array<[string, number, string]>} */ ([
                    ['A', state.doorA, '#30abc6'],
                    ['B', state.doorB, '#f54e00'],
                ])
                rows.forEach(([letter, votes, color], index) => {
                    const y = h * (0.36 + index * 0.2)
                    fitText(g, letter, w * 0.08, y + h * 0.07, 70, 54, color)
                    roundedPanel(g, w * 0.14, y, w * 0.66, h * 0.13, 10, '#e7e9ee', null)
                    if (votes > 0) {
                        roundedPanel(
                            g,
                            w * 0.14,
                            y,
                            Math.max(w * 0.03, (w * 0.66 * votes) / Math.max(total, 1)),
                            h * 0.13,
                            10,
                            color,
                            null
                        )
                    }
                    fitText(g, String(votes), w * 0.88, y + h * 0.07, 110, 50, '#151515')
                })
                const need = world.significanceVotes
                const verdict =
                    total >= need
                        ? `Significant! Ship door ${state.doorA >= state.doorB ? 'A' : 'B'} 🎉`
                        : `Not significant yet: ${total} of ${need} votes`
                fitText(g, verdict, w / 2, h * 0.86, w * 0.9, 40, total >= need ? '#2ba84a' : '#6b6f76')
            })
        }
    }

    // Max's desk.
    {
        const stall = new THREE.Group()
        stall.add(mesh(box(6, 3.6, 0.4), mat(COLORS.purple), [0, 1.8, -1.5]))
        stall.add(mesh(box(0.35, 3.3, 3), mat(0x8a1fa6), [-2.85, 1.65, -0.1]))
        stall.add(mesh(box(0.35, 3.3, 3), mat(0x8a1fa6), [2.85, 1.65, -0.1]))
        stall.add(mesh(box(5.6, 1.05, 0.9), mat(COLORS.wood), [0, 0.52, 1.25]))
        stall.add(mesh(box(5.9, 0.14, 1.15), mat(COLORS.cream), [0, 1.1, 1.25]))
        for (let stripe = 0; stripe < 8; stripe++) {
            stall.add(
                mesh(
                    box(0.76, 0.12, 2.3),
                    mat(stripe % 2 ? 0xffffff : COLORS.purple),
                    [-2.66 + stripe * 0.76, 3.5, 0.7],
                    {
                        rotation: [0.32, 0, 0],
                    }
                )
            )
        }
        const awningSnow = mesh(box(6.1, 0.16, 1), snow, [0, 3.9, -0.25], { rotation: [0.32, 0, 0], cast: false })
        stall.add(awningSnow)
        stall.add(mesh(box(0.9, 0.06, 0.6), mat(0xc9ced8), [1.5, 1.2, 1.3]))
        stall.add(
            mesh(box(0.9, 0.6, 0.06), glow(0x9fd8ff, 0.8, 2.4), [1.5, 1.5, 1.02], {
                rotation: [-0.2, 0, 0],
                cast: false,
            })
        )
        const sparkles = [0, 1, 2].map((index) => {
            const sparkle = mesh(
                new THREE.OctahedronGeometry(0.2),
                glow(0xffe066, 1.2, 3),
                [-2.2 + index * 2.2, 4.9, 0.9],
                { cast: false }
            )
            stall.add(sparkle)
            return sparkle
        })
        animations.push((_dt, time) => {
            sparkles.forEach((sparkle, index) => {
                sparkle.rotation.y = time * 2 + index
                sparkle.position.y = 4.9 + Math.sin(time * 2 + index * 2) * 0.18
            })
        })
        const light = lamp(0xf3c8ff, 0, 12, 9)
        light.position.set(0, 2.6, 1.6)
        stall.add(light)
        place(stall, 35, 2.75)
        const title = sign(4.6, 1.15, 90, (g, w, h) => {
            roundedPanel(g, 5, 5, w - 10, h - 10, 22, '#fffdf6', '#151515', 8)
            fitText(g, '✨ ASK MAX', w / 2, h / 2 + 2, w * 0.86, 60, '#b62ad9')
        })
        title.board.position.copy(at(35, 4.1, 4.7))
        scene.add(title.board)
        addHit('max', 35, 3, 6.2, 4.2, 3.6, 5.2)
    }

    // Bug jar.
    /** @type {THREE.Mesh[]} */
    const bugs = []
    {
        const jar = new THREE.Group()
        jar.add(mesh(box(2.3, 0.55, 1.9), mat(COLORS.wood), [0, 0.28, 0]))
        jar.add(mesh(box(2.4, 0.1, 2), snow, [0, 0.58, 0], { cast: false }))
        jar.add(
            mesh(
                cylinder(0.95, 0.95, 1.9, 14),
                new THREE.MeshStandardMaterial({
                    color: 0x8fd3f4,
                    transparent: true,
                    opacity: 0.42,
                    roughness: 0.1,
                    depthWrite: false,
                }),
                [0, 1.55, 0],
                { cast: false }
            )
        )
        jar.add(mesh(cylinder(0.8, 0.8, 0.26, 14), mat(COLORS.orange), [0, 2.62, 0]))
        for (const y of [0.64, 2.46]) {
            jar.add(
                mesh(new THREE.TorusGeometry(0.95, 0.05, 6, 20), mat(0x4f9fc4), [0, y, 0], {
                    rotation: [Math.PI / 2, 0, 0],
                    cast: false,
                })
            )
        }
        jar.add(
            mesh(box(0.08, 1.3, 0.02), mat(0xffffff, { transparent: true, opacity: 0.75 }), [-0.5, 1.6, 0.82], {
                cast: false,
            })
        )
        const bugColors = [0xe5383b, 0x2ba84a, 0xf9bd2b, 0x1d4aff, 0xb62ad9]
        for (let index = 0; index < 24; index++) {
            const bug = mesh(sphere(0.13, 0), glow(bugColors[index % 5], 0.4, 1.6), [0, 1, 0], { cast: false })
            bug.visible = false
            bugs.push(bug)
            jar.add(bug)
        }
        animations.push((_dt, time) => {
            bugs.forEach((bug, index) => {
                const speed = 0.8 + (index % 5) * 0.25
                const radius = 0.25 + ((index * 7) % 10) * 0.055
                bug.position.set(
                    Math.cos(time * speed + index * 1.7) * radius,
                    0.85 + ((index * 13) % 10) * 0.14 + Math.sin(time * 3 + index) * 0.08,
                    Math.sin(time * speed + index * 1.7) * radius
                )
            })
        })
        place(jar, 5.3, 15.6)
        const counter = sign(3.2, 1.3, 100, () => undefined)
        counter.board.position.copy(at(5.3, 15.6, 3.6))
        scene.add(counter.board)
        objectViews.bugs = (/** @type {any} */ state) => {
            bugs.forEach((bug, index) => (bug.visible = index < state.bugsCaught + 3))
            counter.redraw((g, w, h) => {
                roundedPanel(g, 5, 5, w - 10, h - 10, 20, '#fffdf6', '#151515', 8)
                fitText(g, `🐛 ${state.bugsCaught} caught`, w / 2, h / 2 + 2, w * 0.84, 70, '#151515')
            })
        }
        addHit('bugs', 5.3, 15.8, 2.8, 3.2, 2.6, 5.2)
    }

    // Ship it: the launch pad, the rocket, and the big button.
    const rocket = new THREE.Group()
    // Rockets in the air. Each launch sends a copy of the rocket on the pad, so the pad is never empty.
    /** @type {Array<{ group: THREE.Group, flame: THREE.Mesh, light: THREE.PointLight, age: number }>} */
    const flights = []
    let buttonPressedAt = -1
    let launchRocket = () => undefined
    const MAX_ROCKETS = 6
    const flameMaterial = glow(0xffa51f, 2.4, 3, { transparent: true, opacity: 0.9 })
    {
        const pad = new THREE.Group()
        pad.add(mesh(cylinder(1.9, 2.05, 0.3, 16), mat(0x4a5162), [0, 0.15, 0]))
        pad.add(
            mesh(new THREE.TorusGeometry(1.5, 0.08, 6, 24), mat(COLORS.yellow), [0, 0.31, 0], {
                rotation: [Math.PI / 2, 0, 0],
                cast: false,
            })
        )
        for (const y of [0.9, 1.9, 2.9]) {
            pad.add(mesh(box(0.5, 0.08, 0.5), mat(COLORS.red), [-1.45, y, -0.6]))
        }
        for (const [x, z] of [
            [-1.7, -0.85],
            [-1.2, -0.85],
            [-1.7, -0.35],
            [-1.2, -0.35],
        ]) {
            pad.add(mesh(box(0.08, 3.2, 0.08), mat(COLORS.red), [x, 1.6, z]))
        }
        rocket.add(mesh(cylinder(0.55, 0.6, 2.3, 12), mat(0xffffff), [0, 1.65, 0]))
        rocket.add(mesh(cone(0.55, 1.1, 12), mat(COLORS.orange), [0, 3.35, 0]))
        rocket.add(mesh(sphere(0.24, 1), glow(0x7fd4ff, 0.6, 1.6), [0, 2.2, 0.48]))
        rocket.add(mesh(cylinder(0.62, 0.62, 0.18, 12), mat(COLORS.blue), [0, 1.1, 0]))
        for (let fin = 0; fin < 3; fin++) {
            const angle = (fin / 3) * Math.PI * 2 + 0.5
            rocket.add(
                mesh(box(0.1, 0.9, 0.6), mat(COLORS.orange), [Math.cos(angle) * 0.72, 0.85, Math.sin(angle) * 0.72], {
                    rotation: [0, -angle + Math.PI / 2, 0],
                })
            )
        }
        const flame = mesh(
            cone(0.42, 1.6, 8),
            glow(0xffa51f, 2.4, 3, { transparent: true, opacity: 0.9 }),
            [0, -0.2, 0],
            {
                rotation: [Math.PI, 0, 0],
                cast: false,
            }
        )
        flame.visible = false
        rocket.add(flame)
        rocket.position.y = 0.3
        pad.add(rocket)
        // The button.
        pad.add(mesh(box(0.9, 0.95, 0.9), mat(0x4a5162), [0, 0.48, 1.9]))
        const button = mesh(cylinder(0.34, 0.38, 0.24, 12), glow(COLORS.red, 0.5, 1.8), [0, 1.06, 1.9])
        pad.add(button)
        const rocketLight = lamp(0xffa51f, 0, 0, 16)
        rocketLight.position.set(0, 1, 0)
        rocket.add(rocketLight)
        place(pad, 34, 15.1)
        animations.push((dt, time) => {
            const pressed = time - buttonPressedAt < 0.3
            button.position.y += ((pressed ? 0.98 : 1.06) - button.position.y) * Math.min(1, dt * 20)
            for (let index = flights.length - 1; index >= 0; index--) {
                const flight = flights[index]
                flight.age += dt
                flight.flame.scale.set(1, 0.8 + Math.sin(time * 40) * 0.25, 1)
                if (flight.age < 0.5) {
                    // The rocket shakes before it lifts off.
                    flight.group.position.set(Math.sin(time * 60) * 0.05, 0.3, Math.cos(time * 50) * 0.05)
                } else {
                    const lift = flight.age - 0.5
                    flight.group.position.set(0, 0.3 + lift * lift * 4.5, 0)
                    if (Math.random() < 0.3) {
                        puff(at(34, 15.1, Math.max(0.6, flight.group.position.y - 0.4)), 0xe8eef6, 1)
                    }
                }
                if (flight.age > 4) {
                    pad.remove(flight.group)
                    flights.splice(index, 1)
                }
            }
            rocketLight.intensity = flights.length > 0 ? 50 : 0
            rocket.visible = flights.every((flight) => flight.age > 0.5)
        })
        launchRocket = () => {
            buttonPressedAt = performance.now() / 1000
            const group = rocket.clone()
            group.visible = true
            // Every rocket shares one flame material and the pad's light. Lights are the expensive part of a
            // scene, so a rage click never adds one. Past six rockets in the air, the oldest one is gone.
            const ownFlame = mesh(cone(0.42, 1.6, 8), flameMaterial, [0, -0.2, 0], {
                rotation: [Math.PI, 0, 0],
                cast: false,
            })
            group.add(ownFlame)
            pad.add(group)
            flights.push({ group, flame: ownFlame, age: 0 })
            while (flights.length > MAX_ROCKETS) {
                pad.remove(flights.shift().group)
            }
            puff(at(34, 15.1, 0.5), 0xe8eef6, 8)
        }
        const counter = sign(4, 1.4, 100, () => undefined)
        counter.board.position.copy(at(30.6, 16.3, 2.4))
        scene.add(counter.board)
        scene.add(mesh(cylinder(0.06, 0.06, 1.6, 6), mat(0x2b3040), at(30.6, 16.25, 0.9).toArray()))
        objectViews.ship = (/** @type {any} */ state) => {
            counter.redraw((g, w, h) => {
                roundedPanel(g, 5, 5, w - 10, h - 10, 20, '#fffdf6', '#151515', 8)
                fitText(g, `🚀 ${state.deploys} shipped today`, w / 2, h / 2 + 2, w * 0.88, 64, '#151515')
            })
        }
        addHit('ship', 34, 15.6, 4.2, 4.6, 4.4, 5.2)
    }

    // ---- Particles: snowfall, puffs, confetti ---------------------------------------------------------------------
    const flakeCount = 520
    const flakePositions = new Float32Array(flakeCount * 3)
    for (let index = 0; index < flakeCount; index++) {
        flakePositions[index * 3] = (Math.random() - 0.5) * 60
        flakePositions[index * 3 + 1] = Math.random() * 20
        flakePositions[index * 3 + 2] = (Math.random() - 0.5) * 36
    }
    const flakes = new THREE.Points(
        new THREE.BufferGeometry().setAttribute('position', new THREE.BufferAttribute(flakePositions, 3)),
        new THREE.PointsMaterial({ color: 0xffffff, size: 0.16, transparent: true, opacity: 0.9, depthWrite: false })
    )
    scene.add(flakes)
    animations.push((dt, time) => {
        for (let index = 0; index < flakeCount; index++) {
            flakePositions[index * 3] += Math.sin(time * 0.6 + index) * dt * 0.4
            flakePositions[index * 3 + 1] -= dt * (1.1 + (index % 5) * 0.25)
            if (flakePositions[index * 3 + 1] < 0) {
                flakePositions[index * 3 + 1] = 20
            }
        }
        flakes.geometry.attributes.position.needsUpdate = true
    })

    /** @type {Array<{ mesh: THREE.Mesh, velocity: THREE.Vector3, life: number, maxLife: number, gravity: number, spin: number, grow: number }>} */
    const particles = []
    // The most particles alive at once. Past that, the oldest one goes, so a rage click cannot pile them up.
    const MAX_PARTICLES = 240
    function keepParticleBudget() {
        while (particles.length >= MAX_PARTICLES) {
            const oldest = particles.shift()
            scene.remove(oldest.mesh)
            oldest.mesh.material.dispose()
        }
    }
    const particleGeometry = { puff: sphere(0.3, 0), confetti: box(0.16, 0.16, 0.03) }
    function puff(/** @type {THREE.Vector3} */ position, /** @type {number} */ color, count = 6) {
        for (let index = 0; index < count; index++) {
            keepParticleBudget()
            const piece = mesh(
                particleGeometry.puff,
                new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.85 }),
                position.toArray(),
                { cast: false, receive: false }
            )
            scene.add(piece)
            particles.push({
                mesh: piece,
                velocity: new THREE.Vector3(
                    (Math.random() - 0.5) * 2.4,
                    0.6 + Math.random() * 1.2,
                    (Math.random() - 0.5) * 2.4
                ),
                life: 0,
                maxLife: 0.9 + Math.random() * 0.5,
                gravity: 0,
                spin: 0,
                grow: 1.6,
            })
        }
    }
    function confetti(/** @type {THREE.Vector3} */ position, /** @type {number[]} */ colors, count = 36) {
        for (let index = 0; index < count; index++) {
            keepParticleBudget()
            const piece = mesh(
                particleGeometry.confetti,
                new THREE.MeshBasicMaterial({ color: colors[index % colors.length], transparent: true }),
                position.toArray(),
                { cast: false, receive: false }
            )
            scene.add(piece)
            particles.push({
                mesh: piece,
                velocity: new THREE.Vector3(
                    (Math.random() - 0.5) * 5,
                    4 + Math.random() * 4,
                    (Math.random() - 0.3) * 4
                ),
                life: 0,
                maxLife: 1.6 + Math.random() * 0.6,
                gravity: 9,
                spin: 6 + Math.random() * 8,
                grow: 0,
            })
        }
    }
    animations.push((dt) => {
        for (let index = particles.length - 1; index >= 0; index--) {
            const particle = particles[index]
            particle.life += dt
            particle.velocity.y -= particle.gravity * dt
            particle.mesh.position.addScaledVector(particle.velocity, dt)
            particle.mesh.rotation.x += particle.spin * dt
            particle.mesh.rotation.z += particle.spin * 0.7 * dt
            const age = particle.life / particle.maxLife
            particle.mesh.scale.setScalar(1 + particle.grow * age)
            particle.mesh.material.opacity = Math.max(0, 1 - age * age)
            if (age >= 1 || particle.mesh.position.y < 0) {
                scene.remove(particle.mesh)
                particle.mesh.material.dispose()
                particles.splice(index, 1)
            }
        }
    })

    // Footprints that a walking hedgehog leaves in the snow. They fade out.
    const printGeometry = new THREE.CircleGeometry(0.16, 8)
    /** @type {Array<{ mesh: THREE.Mesh, age: number }>} */
    const prints = []
    function footprint(/** @type {number} */ x, /** @type {number} */ y) {
        const print = mesh(
            printGeometry,
            new THREE.MeshBasicMaterial({ color: 0x9db6d6, transparent: true, opacity: 0.55, depthWrite: false }),
            at(x, y, 0.045).toArray(),
            { rotation: [-Math.PI / 2, 0, 0], cast: false, receive: false }
        )
        scene.add(print)
        prints.push({ mesh: print, age: 0 })
    }
    animations.push((dt) => {
        for (let index = prints.length - 1; index >= 0; index--) {
            const print = prints[index]
            print.age += dt
            print.mesh.material.opacity = 0.55 * Math.max(0, 1 - print.age / 4)
            if (print.age >= 4) {
                scene.remove(print.mesh)
                print.mesh.material.dispose()
                prints.splice(index, 1)
            }
        }
    })

    // The rainbow: a sheet over the snow that ripples through every color while the emote lasts.
    const rainbowMaterial = new THREE.ShaderMaterial({
        transparent: true,
        depthWrite: false,
        uniforms: { uTime: { value: 0 }, uStrength: { value: 0 } },
        vertexShader:
            'varying vec2 vUv; void main() { vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }',
        fragmentShader: `
            uniform float uTime; uniform float uStrength; varying vec2 vUv;
            vec3 hue(float h) { return clamp(abs(mod(h * 6.0 + vec3(0.0, 4.0, 2.0), 6.0) - 3.0) - 1.0, 0.0, 1.0); }
            void main() {
                vec2 p = vUv * vec2(40.0, 22.0);
                float d = length(p - vec2(20.0, 11.5));
                float ripple = 0.5 + 0.5 * sin(d * 1.1 - uTime * 5.0);
                float h = fract(d * 0.07 - uTime * 0.3 + 0.08 * sin(p.x * 0.35 + uTime * 1.7) + 0.08 * sin(p.y * 0.5 - uTime * 1.3));
                gl_FragColor = vec4(hue(h), (0.5 + 0.4 * ripple) * uStrength);
            }`,
    })
    const rainbow = new THREE.Mesh(new THREE.PlaneGeometry(world.width, world.depth), rainbowMaterial)
    rainbow.rotation.x = -Math.PI / 2
    rainbow.position.y = 0.06
    rainbow.visible = false
    scene.add(rainbow)
    let rainbowUntil = 0
    animations.push((dt, time) => {
        const left = rainbowUntil - time
        const target = left > 0 ? Math.min(1, left) : 0
        rainbowMaterial.uniforms.uStrength.value +=
            (target - rainbowMaterial.uniforms.uStrength.value) * Math.min(1, dt * 4)
        rainbowMaterial.uniforms.uTime.value = time
        rainbow.visible = rainbowMaterial.uniforms.uStrength.value > 0.01
    })

    // A ring on the ground where the player clicked.
    const marker = mesh(
        new THREE.RingGeometry(0.34, 0.5, 28),
        new THREE.MeshBasicMaterial({ color: COLORS.orange, transparent: true, opacity: 0, depthWrite: false }),
        [0, 0.08, 0],
        { rotation: [-Math.PI / 2, 0, 0], cast: false, receive: false }
    )
    scene.add(marker)
    let markerAge = 1
    animations.push((dt) => {
        markerAge += dt
        marker.scale.setScalar(0.6 + markerAge * 1.8)
        marker.material.opacity = Math.max(0, 0.9 - markerAge * 1.5)
    })

    // Stars for the night sky.
    const starPositions = new Float32Array(220 * 3)
    for (let index = 0; index < 220; index++) {
        starPositions[index * 3] = (Math.random() - 0.5) * 260
        starPositions[index * 3 + 1] = 22 + Math.random() * 70
        starPositions[index * 3 + 2] = -70 - Math.random() * 30
    }
    const stars = new THREE.Points(
        new THREE.BufferGeometry().setAttribute('position', new THREE.BufferAttribute(starPositions, 3)),
        new THREE.PointsMaterial({
            color: 0xffffff,
            size: 0.7,
            transparent: true,
            opacity: 0,
            fog: false,
            depthWrite: false,
        })
    )
    scene.add(stars)

    // ---- Day and night --------------------------------------------------------------------------------------------
    const night = { value: 0, target: 0 }
    function applyNight() {
        const n = night.value
        scene.background.lerpColors(DAY.sky, NIGHT.sky, n)
        scene.fog.color.copy(scene.background)
        hemisphere.color.lerpColors(DAY.hemiSky, NIGHT.hemiSky, n)
        hemisphere.groundColor.lerpColors(DAY.hemiGround, NIGHT.hemiGround, n)
        hemisphere.intensity = 1.25 - n * 0.6
        sun.color.lerpColors(DAY.sun, NIGHT.sun, n)
        sun.intensity = 3 - n * 2.3
        shadowCatcher.material.opacity = 0.42 - n * 0.14
        glowMaterials.forEach(
            ({ material, day, night: atNight }) => (material.emissiveIntensity = day + (atNight - day) * n)
        )
        lamps.forEach(({ light, day, night: atNight }) => (light.intensity = day + (atNight - day) * n))
        stars.material.opacity = n
        paths.board.material.color.setScalar(1 - n * 0.55)
    }

    // Fire-mode: the trees char and glow, their snow melts away, and the snowman sinks into a puddle. Back to 0 undoes it.
    const CHARRED = new THREE.Color(0x3b2416)
    const puddles = snowmen.map((snowman) => {
        const puddle = mesh(cylinder(1.1, 1.1, 0.04, 16), mat(COLORS.ice, { flatShading: false }), [0, 0.02, 0], {
            cast: false,
        })
        puddle.scale.setScalar(0.001)
        snowman.parent.add(puddle)
        puddle.position.copy(snowman.position)
        return puddle
    })
    // Every tree gets a flame on top, which only shows in fire-mode.
    const treeFlameMaterial = new THREE.MeshBasicMaterial({ color: 0xffa02e, transparent: true, opacity: 0.9 })
    const treeFlames = pines.map((tree) => {
        const height = tree.userData.height
        const flame = mesh(cone(height * 0.16, height * 0.5, 6), treeFlameMaterial, [0, height * 0.98, 0], {
            cast: false,
            receive: false,
        })
        flame.scale.setScalar(0.001)
        flame.userData.phase = Math.random() * 7
        tree.add(flame)
        return flame
    })
    function applyFire() {
        const f = fireMode.value
        pines.forEach((tree) => {
            const { foliage, foliageColor, caps } = tree.userData
            foliage.color.lerpColors(foliageColor, CHARRED, f)
            foliage.emissive.setHex(0xff3d00)
            foliage.emissiveIntensity = f * 0.3
            caps.forEach((cap) => cap.scale.setScalar(Math.max(0.001, 1 - f)))
        })
        snowmen.forEach((snowman, index) => {
            snowman.scale.set(1 + f * 0.15, 1 - f * 0.5, 1 + f * 0.15)
            puddles[index].scale.setScalar(Math.max(0.001, f))
        })
    }
    // Embers rise from the burning trees around the square, and the flames flicker.
    let emberDebt = 0
    animations.push((dt, time) => {
        if (fireMode.value < 0.02) {
            return
        }
        treeFlames.forEach((flame) => {
            const flicker =
                0.75 + 0.25 * Math.sin(time * 19 + flame.userData.phase) * Math.sin(time * 6 + flame.userData.phase)
            flame.scale.set(fireMode.value, fireMode.value * flicker, fireMode.value)
        })
        if (fireMode.value < 0.3) {
            return
        }
        emberDebt += dt * 5 * fireMode.value
        while (emberDebt >= 1) {
            emberDebt -= 1
            const tree = pines[Math.floor(Math.random() * pines.length)]
            const top = tree.getWorldPosition(new THREE.Vector3())
            top.y += tree.userData.height * 0.7
            puff(top, Math.random() < 0.5 ? 0xff7a1f : 0xffc14d, 1)
        }
    })

    // ---- Camera ---------------------------------------------------------------------------------------------------
    const focus = new THREE.Vector3(0, 1.6, -1.2)
    const fromFocus = new THREE.Vector3(0, Math.sin(0.5), Math.cos(0.5))
    // The camera moves back until these points are all in view.
    const mustSee = [at(-0.4, 22.3), at(world.width + 0.4, 22.3), at(1, 0, 10.4), at(world.width - 1, 0, 10.4)]
    function fitCamera(/** @type {number} */ width, /** @type {number} */ height) {
        const ratio = Math.min(window.devicePixelRatio || 1, 2)
        renderer.setPixelRatio(ratio)
        renderer.setSize(width, height, false)
        camera.aspect = width / height
        camera.updateProjectionMatrix()
        // The toolbar covers the bottom of the stage, so the town stays above it.
        // In a pane there is no toolbar to leave room for.
        const bottom = document.body.classList.contains('pane') ? -0.97 : -1 + Math.min(0.3, 130 / height)
        let near = 20
        let far = 260
        for (let pass = 0; pass < 22; pass++) {
            const distance = (near + far) / 2
            camera.position.copy(focus).addScaledVector(fromFocus, distance)
            camera.lookAt(focus)
            camera.updateMatrixWorld()
            const fits = mustSee.every((point) => {
                const projected = point.clone().project(camera)
                return Math.abs(projected.x) <= 0.985 && projected.y <= 0.97 && projected.y >= bottom
            })
            if (fits) {
                far = distance
            } else {
                near = distance
            }
        }
        camera.position.copy(focus).addScaledVector(fromFocus, far)
        camera.lookAt(focus)
        camera.updateMatrixWorld()
        // The fog starts behind the town, so it softens only the trees and mountains in the distance.
        scene.fog.near = far + 26
        scene.fog.far = far + 170
    }

    let shownObjects = ''
    const raycaster = new THREE.Raycaster()
    const groundPlane = new THREE.Plane(new THREE.Vector3(0, 1, 0), 0)

    return {
        THREE,
        scene,
        camera,
        renderer,
        at,
        interactables,
        fitCamera,
        /** What is under a point of the stage: an object to use, or a spot on the ground. */
        pick(/** @type {number} */ ndcX, /** @type {number} */ ndcY) {
            raycaster.setFromCamera(new THREE.Vector2(ndcX, ndcY), camera)
            const hit = raycaster.intersectObjects(interactables.map((entry) => entry.hit))[0]
            if (hit) {
                return { objectId: /** @type {any} */ (interactables.find((entry) => entry.hit === hit.object)).id }
            }
            const point = raycaster.ray.intersectPlane(groundPlane, new THREE.Vector3())
            return point ? { x: point.x + halfWidth, y: point.z + halfDepth } : null
        },
        showMarker(/** @type {number} */ x, /** @type {number} */ y) {
            marker.position.copy(at(x, y, 0.08))
            markerAge = 0
        },
        /** Shows the state of every object: the scoreboard, the counters, the cinema screen, day or night. */
        setObjects(/** @type {any} */ state, instant = false) {
            night.target = state.lightsOn ? 0 : 1
            fireMode.target = state.fireOn ? 1 : 0
            if (instant) {
                night.value = night.target
                fireMode.value = fireMode.target
                applyFire()
            }
            // The boards are canvases. They are drawn again only when what they show is different.
            const key = JSON.stringify(state)
            if (key === shownObjects) {
                return
            }
            shownObjects = key
            Object.values(objectViews).forEach((view) => view(state))
        },
        /** Plays the effect for one use of an object. */
        playPoke(/** @type {string} */ objectId) {
            const object = objects[objectId]
            const spot = at(object.stand.x, object.stand.y, 1.2)
            if (objectId === 'ship') {
                launchRocket()
            } else if (objectId === 'door-a' || objectId === 'door-b') {
                doors[objectId].open = 1.4
                confetti(
                    at(object.stand.x, 4.9, 2.4),
                    objectId === 'door-a' ? [0x30abc6, 0xffffff, 0x9be3f2] : [0xf54e00, 0xffffff, 0xffc29e]
                )
            } else if (objectId === 'bugs') {
                confetti(at(5.3, 15.6, 2.9), [0xe5383b, 0x2ba84a, 0xf9bd2b], 14)
            } else if (objectId === 'flag') {
                puff(at(6.4, 4.45, 1.6), 0xfff3b0, 8)
            } else if (objectId === 'fire') {
                puff(at(12.9, 17.2, 1.6), 0xff7a1f, 8)
            } else if (objectId === 'replay') {
                confetti(at(13.5, 4.9, 4.2), [0xffd23f, 0xff6b6b, 0xffffff], 20)
            } else {
                confetti(spot, [0xffe066, 0xb62ad9, 0xffffff], 18)
            }
        },
        puff,
        footprint,
        /** Turns the snow into a rainbow for this many seconds. */
        rainbow(/** @type {number} */ seconds) {
            rainbowUntil = performance.now() / 1000 + seconds
        },
        nightValue: () => night.value,
        update(/** @type {number} */ dt, /** @type {number} */ time) {
            if (night.value !== night.target) {
                night.value +=
                    Math.sign(night.target - night.value) * Math.min(Math.abs(night.target - night.value), dt * 1.2)
                applyNight()
            }
            if (fireMode.value !== fireMode.target) {
                fireMode.value +=
                    Math.sign(fireMode.target - fireMode.value) *
                    Math.min(Math.abs(fireMode.target - fireMode.value), dt * 0.45)
                applyFire()
            }
            animations.forEach((animate) => animate(dt, time))
            renderer.render(scene, camera)
        },
        applyNight,
    }
}

/** @type {Record<string, (state: any) => void>} */
const objectViews = {}
