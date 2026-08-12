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
): void {
  const url = resolveSoundUrl(sound, customSounds);
  if (!url) return;

  if (currentAudio) {
    currentAudio.pause();
    currentAudio = null;
  }

  const audio = new Audio(url);
  audio.volume = Math.max(0, Math.min(100, volume)) / 100;
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
