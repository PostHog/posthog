import type {
  BuiltInCompletionSound,
  CompletionSound,
  CustomSound,
} from "@posthog/ui/features/settings/settingsStore";
import bubblesUrl from "../assets/sounds/bubbles.mp3";
import daniloUrl from "../assets/sounds/danilo.mp3";
import dropUrl from "../assets/sounds/drop.mp3";
import guitarUrl from "../assets/sounds/guitar.mp3";
import icqUrl from "../assets/sounds/icq.mp3";
import knockUrl from "../assets/sounds/knock.mp3";
import meepUrl from "../assets/sounds/meep.mp3";
import meepSmolUrl from "../assets/sounds/meep-smol.mp3";
import msnUrl from "../assets/sounds/msn.mp3";
import reviUrl from "../assets/sounds/revi.mp3";
import ringUrl from "../assets/sounds/ring.mp3";
import shootUrl from "../assets/sounds/shoot.mp3";
import slideUrl from "../assets/sounds/slide.mp3";
import switchUrl from "../assets/sounds/switch.mp3";
import wilhelmUrl from "../assets/sounds/wilhelm.mp3";

const CUSTOM_SOUND_PREFIX = "custom:";

const SOUND_URLS: Record<Exclude<BuiltInCompletionSound, "none">, string> = {
  guitar: guitarUrl,
  danilo: daniloUrl,
  revi: reviUrl,
  meep: meepUrl,
  "meep-smol": meepSmolUrl,
  bubbles: bubblesUrl,
  drop: dropUrl,
  knock: knockUrl,
  ring: ringUrl,
  shoot: shootUrl,
  slide: slideUrl,
  switch: switchUrl,
  wilhelm: wilhelmUrl,
  icq: icqUrl,
  msn: msnUrl,
};

const MIN_RATE = 1 / 3;
const MAX_RATE = 3;
const FAST_MS = 30 * 1000;
const NORMAL_START_MS = 2 * 60 * 1000;
const NORMAL_END_MS = 4 * 60 * 1000;
const SLOW_MS = 30 * 60 * 1000;

// Maps a task's duration to an audio playback rate so a quick task rings fast
// (and high-pitched) while a long one drags slow (and low). Anchored at: <=30s
// -> 3x, the 2-4min "normal" band -> 1x, >=30min -> 1/3x, with smooth
// log-interpolation across the two ramps so the rate doesn't jump at the edges.
export function playbackRateForTaskDuration(durationMs: number): number {
  if (!Number.isFinite(durationMs) || durationMs <= FAST_MS) return MAX_RATE;
  if (durationMs >= SLOW_MS) return MIN_RATE;
  if (durationMs >= NORMAL_START_MS && durationMs <= NORMAL_END_MS) return 1;

  if (durationMs < NORMAL_START_MS) {
    const frac =
      (Math.log(durationMs) - Math.log(FAST_MS)) /
      (Math.log(NORMAL_START_MS) - Math.log(FAST_MS));
    return MAX_RATE ** (1 - frac);
  }

  const frac =
    (Math.log(durationMs) - Math.log(NORMAL_END_MS)) /
    (Math.log(SLOW_MS) - Math.log(NORMAL_END_MS));
  return MIN_RATE ** frac;
}

let currentAudio: HTMLAudioElement | null = null;

function pickRandom(pool: string[]): string | null {
  if (pool.length === 0) return null;
  return pool[Math.floor(Math.random() * pool.length)];
}

// Resolves the playable URL for a completion sound: a bundled asset URL for the
// built-ins, the inline data URL of a user-installed custom sound, or a fresh
// random pick per call for the `random-*` modes. Returns null for `none`, an
// unknown built-in, a `custom:` id no longer installed (e.g. the active sound
// was deleted), or `random-custom` with no sounds installed — callers then
// play nothing.
export function resolveSoundUrl(
  sound: CompletionSound,
  customSounds: CustomSound[],
): string | null {
  if (sound === "none") return null;
  const customUrls = customSounds.map((s) => s.dataUrl);
  if (sound === "random-all") {
    return pickRandom([...Object.values(SOUND_URLS), ...customUrls]);
  }
  if (sound === "random-custom") return pickRandom(customUrls);
  if (sound.startsWith(CUSTOM_SOUND_PREFIX)) {
    const id = sound.slice(CUSTOM_SOUND_PREFIX.length);
    return customSounds.find((s) => s.id === id)?.dataUrl ?? null;
  }
  return SOUND_URLS[sound as Exclude<BuiltInCompletionSound, "none">] ?? null;
}

export function playCompletionSound(
  sound: CompletionSound,
  volume = 80,
  customSounds: CustomSound[] = [],
  playbackRate = 1,
): void {
  const url = resolveSoundUrl(sound, customSounds);
  if (!url) return;

  if (currentAudio) {
    currentAudio.pause();
    currentAudio = null;
  }

  const audio = new Audio(url);
  audio.volume = Math.max(0, Math.min(100, volume)) / 100;
  audio.playbackRate = playbackRate;
  currentAudio = audio;
  audio.play().catch(() => {
    // Audio play can fail if user hasn't interacted with the page yet
  });
  audio.addEventListener("ended", () => {
    if (currentAudio === audio) {
      currentAudio = null;
    }
  });
}
