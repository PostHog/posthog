// The ambient ASCII field behind the composer and hero screens: a WebGL
// fragment shader that quantizes a slow noise field into a monospace density
// ramp. The glyphs come from a texture atlas built at the exact device-pixel
// cell size, so the same shader stays crisp at any container size or DPR.

import type { Rgb } from "@posthog/ui/primitives/cssColor";

/** Density ramp, coarse to fine. Index 0 is blank so sparse areas read as empty. */
const GLYPH_RAMP = " .:-=+*";

/** Cell size in CSS pixels, at roughly a monospace character's aspect ratio. */
const CELL_WIDTH = 13;
const CELL_HEIGHT = 20;

const MAX_PIXEL_RATIO = 2;
const TARGET_FRAME_MS = 1000 / 30;
const ATLAS_FONT_STACK =
  'ui-monospace, SFMono-Regular, Menlo, Consolas, "Liberation Mono", monospace';

const VERTEX_SHADER = `
attribute vec2 aPosition;

void main() {
  gl_Position = vec4(aPosition, 0.0, 1.0);
}
`;

const FRAGMENT_SHADER = `
precision mediump float;

uniform vec2 uResolution;
uniform vec2 uCell;
uniform float uTime;
uniform float uGlyphCount;
uniform sampler2D uAtlas;
uniform vec3 uInk;
uniform vec3 uAccent;

float hash(vec2 p) {
  return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453123);
}

float valueNoise(vec2 p) {
  vec2 cell = floor(p);
  vec2 f = fract(p);
  vec2 blend = f * f * (3.0 - 2.0 * f);
  return mix(
    mix(hash(cell), hash(cell + vec2(1.0, 0.0)), blend.x),
    mix(hash(cell + vec2(0.0, 1.0)), hash(cell + vec2(1.0, 1.0)), blend.x),
    blend.y
  );
}

void main() {
  vec2 grid = gl_FragCoord.xy / uCell;
  vec2 cellId = floor(grid);
  vec2 inCell = fract(grid);

  // Two octaves drifting at different rates, so the field never reads as a
  // single sliding texture.
  vec2 p = cellId * 0.09;
  float field = valueNoise(p + vec2(uTime * 0.06, uTime * -0.025));
  field = mix(field, valueNoise(p * 2.3 - vec2(uTime * 0.03, 0.0)), 0.35);
  // Value noise clusters around its midpoint; stretch it so the ramp's coarse
  // and fine ends both get used instead of everything landing on ':' and '-'.
  field = smoothstep(0.2, 0.8, field);

  // Thin out toward the top so whatever floats above the field — a composer, a
  // heading — sits on near-empty background.
  float rise = gl_FragCoord.y / uResolution.y;
  float density = pow(field, 1.6) * (1.0 - rise * 0.5);
  // Dither per cell so neighbours don't quantize to the same glyph in long
  // horizontal runs, which read as dashed rules rather than as text.
  density = clamp(density + (hash(cellId) - 0.5) * 0.08, 0.0, 1.0);

  float index = min(floor(density * uGlyphCount), uGlyphCount - 1.0);
  float coverage = texture2D(
    uAtlas,
    vec2((index + inCell.x) / uGlyphCount, inCell.y)
  ).a;

  // Only the densest glyphs pick up the brand accent; the rest stay neutral.
  vec3 tint = mix(uInk, uAccent, smoothstep(0.6, 1.0, density) * 0.5);
  float alpha = coverage * mix(0.55, 1.0, density);
  gl_FragColor = vec4(tint, 1.0) * alpha;
}
`;

export interface AsciiShaderColors {
  /** Neutral glyph color, e.g. a resolved gray token. */
  ink: Rgb;
  /** Accent the densest glyphs lean toward, e.g. the resolved `--accent-9`. */
  accent: Rgb;
}

interface AsciiShaderOptions extends AsciiShaderColors {
  /** When false the field paints one static frame instead of running a loop. */
  animate: boolean;
}

interface Uniforms {
  resolution: WebGLUniformLocation | null;
  cell: WebGLUniformLocation | null;
  time: WebGLUniformLocation | null;
  glyphCount: WebGLUniformLocation | null;
  atlas: WebGLUniformLocation | null;
  ink: WebGLUniformLocation | null;
  accent: WebGLUniformLocation | null;
}

function compile(
  gl: WebGLRenderingContext,
  type: number,
  source: string,
): WebGLShader | null {
  const shader = gl.createShader(type);
  if (!shader) {
    return null;
  }
  gl.shaderSource(shader, source);
  gl.compileShader(shader);
  if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
    gl.deleteShader(shader);
    return null;
  }
  return shader;
}

function buildProgram(gl: WebGLRenderingContext): WebGLProgram | null {
  const vertex = compile(gl, gl.VERTEX_SHADER, VERTEX_SHADER);
  const fragment = compile(gl, gl.FRAGMENT_SHADER, FRAGMENT_SHADER);
  if (!vertex || !fragment) {
    return null;
  }
  const program = gl.createProgram();
  if (!program) {
    return null;
  }
  gl.attachShader(program, vertex);
  gl.attachShader(program, fragment);
  gl.linkProgram(program);
  // The shaders are owned by the linked program from here on.
  gl.deleteShader(vertex);
  gl.deleteShader(fragment);
  if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
    gl.deleteProgram(program);
    return null;
  }
  return program;
}

/** A horizontal strip of the ramp's glyphs, one per cell, white on transparent. */
function drawAtlas(cellWidth: number, cellHeight: number): HTMLCanvasElement {
  const canvas = document.createElement("canvas");
  canvas.width = cellWidth * GLYPH_RAMP.length;
  canvas.height = cellHeight;
  const ctx = canvas.getContext("2d");
  if (!ctx) {
    return canvas;
  }
  ctx.fillStyle = "#ffffff";
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.font = `${Math.round(cellHeight * 0.78)}px ${ATLAS_FONT_STACK}`;
  for (let i = 0; i < GLYPH_RAMP.length; i++) {
    ctx.fillText(
      GLYPH_RAMP[i],
      i * cellWidth + cellWidth / 2,
      cellHeight / 2 + cellHeight * 0.04,
    );
  }
  return canvas;
}

export class AsciiShader {
  private readonly gl: WebGLRenderingContext;
  private readonly canvas: HTMLCanvasElement;
  private readonly program: WebGLProgram;
  private readonly uniforms: Uniforms;
  private readonly buffer: WebGLBuffer;
  private readonly atlas: WebGLTexture;

  private readonly animate: boolean;
  private colors: AsciiShaderColors;
  private pixelRatio = 0;
  private cellWidth = 0;
  private cellHeight = 0;
  private atlasKey = "";
  private frame: number | null = null;
  private lastFrameMs = 0;
  private disposed = false;
  // Wall-clock elapsed, not performance.now(): mediump floats can't hold an
  // epoch, and a frozen Date (as under the visual-regression runner) pins the
  // field to a single deterministic frame.
  private readonly startedAt = Date.now();

  /** Returns null when WebGL is unavailable — callers should fall back. */
  static create(
    canvas: HTMLCanvasElement,
    options: AsciiShaderOptions,
  ): AsciiShader | null {
    if (typeof WebGLRenderingContext === "undefined") {
      return null;
    }
    let gl: WebGLRenderingContext | null = null;
    try {
      gl = canvas.getContext("webgl", {
        alpha: true,
        antialias: false,
        depth: false,
        stencil: false,
        powerPreference: "low-power",
      }) as WebGLRenderingContext | null;
    } catch {
      return null;
    }
    if (!gl) {
      return null;
    }
    const program = buildProgram(gl);
    const buffer = gl.createBuffer();
    const atlas = gl.createTexture();
    if (!program || !buffer || !atlas) {
      return null;
    }
    return new AsciiShader(canvas, gl, program, buffer, atlas, options);
  }

  private constructor(
    canvas: HTMLCanvasElement,
    gl: WebGLRenderingContext,
    program: WebGLProgram,
    buffer: WebGLBuffer,
    atlas: WebGLTexture,
    options: AsciiShaderOptions,
  ) {
    this.canvas = canvas;
    this.gl = gl;
    this.program = program;
    this.buffer = buffer;
    this.atlas = atlas;
    this.animate = options.animate;
    this.colors = { ink: options.ink, accent: options.accent };

    this.uniforms = {
      resolution: gl.getUniformLocation(program, "uResolution"),
      cell: gl.getUniformLocation(program, "uCell"),
      time: gl.getUniformLocation(program, "uTime"),
      glyphCount: gl.getUniformLocation(program, "uGlyphCount"),
      atlas: gl.getUniformLocation(program, "uAtlas"),
      ink: gl.getUniformLocation(program, "uInk"),
      accent: gl.getUniformLocation(program, "uAccent"),
    };

    gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
    gl.bufferData(
      gl.ARRAY_BUFFER,
      new Float32Array([-1, -1, 1, -1, -1, 1, -1, 1, 1, -1, 1, 1]),
      gl.STATIC_DRAW,
    );
    const position = gl.getAttribLocation(program, "aPosition");
    gl.enableVertexAttribArray(position);
    gl.vertexAttribPointer(position, 2, gl.FLOAT, false, 0, 0);

    gl.bindTexture(gl.TEXTURE_2D, atlas);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    // The atlas is drawn top-down on a 2D canvas; flip so v=0 is its bottom.
    gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, 1);

    // biome-ignore lint/correctness/useHookAtTopLevel: gl.useProgram is a WebGL call, not a React hook
    gl.useProgram(program);
    gl.uniform1i(this.uniforms.atlas, 0);
    gl.uniform1f(this.uniforms.glyphCount, GLYPH_RAMP.length);
    gl.clearColor(0, 0, 0, 0);
  }

  setColors(colors: AsciiShaderColors): void {
    this.colors = colors;
    this.paint();
  }

  /** Sizes the drawing buffer to a CSS-pixel box, rebuilding the atlas on DPR change. */
  resize(cssWidth: number, cssHeight: number): void {
    if (this.disposed || cssWidth <= 0 || cssHeight <= 0) {
      return;
    }
    const ratio = Math.min(window.devicePixelRatio || 1, MAX_PIXEL_RATIO);
    const width = Math.max(1, Math.round(cssWidth * ratio));
    const height = Math.max(1, Math.round(cssHeight * ratio));
    if (
      this.canvas.width === width &&
      this.canvas.height === height &&
      this.pixelRatio === ratio
    ) {
      return;
    }
    this.pixelRatio = ratio;
    this.canvas.width = width;
    this.canvas.height = height;
    this.cellWidth = Math.max(4, Math.round(CELL_WIDTH * ratio));
    this.cellHeight = Math.max(6, Math.round(CELL_HEIGHT * ratio));
    this.gl.viewport(0, 0, width, height);
    this.uploadAtlas();
    this.paint();
  }

  start(): void {
    if (this.disposed) {
      return;
    }
    this.stop();
    if (!this.animate) {
      this.paint();
      return;
    }
    this.lastFrameMs = 0;
    this.frame = requestAnimationFrame(this.tick);
  }

  stop(): void {
    if (this.frame !== null) {
      cancelAnimationFrame(this.frame);
      this.frame = null;
    }
  }

  dispose(): void {
    if (this.disposed) {
      return;
    }
    this.disposed = true;
    this.stop();
    const { gl } = this;
    gl.deleteTexture(this.atlas);
    gl.deleteBuffer(this.buffer);
    gl.deleteProgram(this.program);
    gl.getExtension("WEBGL_lose_context")?.loseContext();
  }

  private readonly tick = (nowMs: number): void => {
    this.frame = requestAnimationFrame(this.tick);
    // A background doesn't need every frame; 30fps halves the GPU work.
    if (nowMs - this.lastFrameMs < TARGET_FRAME_MS) {
      return;
    }
    this.lastFrameMs = nowMs;
    this.paint();
  };

  private uploadAtlas(): void {
    const key = `${this.cellWidth}x${this.cellHeight}`;
    if (key === this.atlasKey) {
      return;
    }
    this.atlasKey = key;
    const { gl } = this;
    gl.bindTexture(gl.TEXTURE_2D, this.atlas);
    gl.texImage2D(
      gl.TEXTURE_2D,
      0,
      gl.RGBA,
      gl.RGBA,
      gl.UNSIGNED_BYTE,
      drawAtlas(this.cellWidth, this.cellHeight),
    );
  }

  private paint(): void {
    if (this.disposed || this.canvas.width === 0 || this.cellWidth === 0) {
      return;
    }
    const { gl, uniforms } = this;
    // biome-ignore lint/correctness/useHookAtTopLevel: gl.useProgram is a WebGL call, not a React hook
    gl.useProgram(this.program);
    gl.activeTexture(gl.TEXTURE0);
    gl.bindTexture(gl.TEXTURE_2D, this.atlas);
    gl.uniform2f(uniforms.resolution, this.canvas.width, this.canvas.height);
    gl.uniform2f(uniforms.cell, this.cellWidth, this.cellHeight);
    gl.uniform1f(uniforms.time, (Date.now() - this.startedAt) / 1000);
    gl.uniform3fv(uniforms.ink, this.colors.ink as unknown as number[]);
    gl.uniform3fv(uniforms.accent, this.colors.accent as unknown as number[]);
    gl.clear(gl.COLOR_BUFFER_BIT);
    gl.drawArrays(gl.TRIANGLES, 0, 6);
  }
}
