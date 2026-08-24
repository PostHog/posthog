import { existsSync } from "node:fs";
import {
  cp,
  mkdir,
  readdir,
  readFile,
  rename,
  rm,
  writeFile,
} from "node:fs/promises";
import { basename, dirname, join } from "node:path";
import { Saga } from "@posthog/shared";
import { extractZip, unzipAsync } from "./extract-zip";

/**
 * Overlays previously-downloaded skills on top of the runtime plugin dir.
 * Each skill directory in the cache replaces the same-named one in the plugin.
 */
export async function overlayDownloadedSkills(
  runtimeSkillsDir: string,
  runtimePluginDir: string,
): Promise<void> {
  if (!existsSync(runtimeSkillsDir)) {
    return;
  }

  const destSkillsDir = join(runtimePluginDir, "skills");
  await mkdir(destSkillsDir, { recursive: true });

  const entries = await readdir(runtimeSkillsDir, { withFileTypes: true });
  for (const entry of entries) {
    if (entry.isDirectory()) {
      const src = join(runtimeSkillsDir, entry.name);
      const dest = join(destSkillsDir, entry.name);
      await rm(dest, { recursive: true, force: true });
      await cp(src, dest, { recursive: true });
    }
  }
}

export interface UpdateSkillsInput {
  runtimeSkillsDir: string;
  runtimePluginDir: string;
  tempDir: string;
  skillsZipUrl: string;
  contextMillZipUrl: string;
  downloadFile: (url: string, destPath: string) => Promise<void>;
}

export interface UpdateSkillsOutput {
  updated: boolean;
}

export class UpdateSkillsSaga extends Saga<
  UpdateSkillsInput,
  UpdateSkillsOutput
> {
  readonly sagaName = "UpdateSkillsSaga";

  protected async execute(
    input: UpdateSkillsInput,
  ): Promise<UpdateSkillsOutput> {
    const newSkillsDir = `${input.runtimeSkillsDir}.new`;

    // Step 1: create staging dir
    await this.step({
      name: "create-staging-dir",
      execute: async () => {
        await rm(newSkillsDir, { recursive: true, force: true });
        await mkdir(newSkillsDir, { recursive: true });
        return newSkillsDir;
      },
      rollback: async (dir) => {
        await rm(dir, { recursive: true, force: true });
      },
    });

    // Step 2: download skills (non-fatal)
    await this.readOnlyStep("download-skills", async () => {
      try {
        await this.downloadAndMergeSkills(
          input.skillsZipUrl,
          input.tempDir,
          newSkillsDir,
          input.downloadFile,
        );
      } catch (err) {
        this.log.warn("Failed to download skills", {
          error: err instanceof Error ? err.message : String(err),
        });
      }
    });

    // Step 2b: download context-mill omnibus skills (non-fatal)
    await this.readOnlyStep("download-context-mill-skills", async () => {
      if (!input.contextMillZipUrl) return;
      try {
        await this.downloadAndMergeContextMillSkills(
          input.contextMillZipUrl,
          input.tempDir,
          newSkillsDir,
          input.downloadFile,
        );
      } catch (err) {
        this.log.warn("Failed to download context-mill skills", {
          error: err instanceof Error ? err.message : String(err),
        });
      }
    });

    // Step 3: validate skills. An empty staging dir means both downloads
    // produced nothing this cycle (e.g. a transient network failure — the
    // download steps above are intentionally non-fatal). The existing skills
    // cache and the bundled skills remain in place, so this is a no-op cycle,
    // not a failure: skip the swap and try again on the next interval rather
    // than throwing, which would surface a misleading "no skills" exception.
    const stagedSkillCount = await this.readOnlyStep(
      "validate-skills",
      async () => {
        const entries = await readdir(newSkillsDir);
        return entries.length;
      },
    );

    if (stagedSkillCount === 0) {
      // Both downloads produced nothing this cycle. Clean up the empty
      // staging dir, then decide whether this is a recoverable no-op or a
      // genuine failure based on whether we have skills to fall back on.
      await rm(newSkillsDir, { recursive: true, force: true });

      const hasCachedSkills =
        existsSync(input.runtimeSkillsDir) &&
        (await readdir(input.runtimeSkillsDir)).length > 0;

      if (hasCachedSkills) {
        // A transient blip (e.g. network failure — the download steps above
        // are non-fatal) shouldn't surface as an error: the previously
        // downloaded skills are still in place. Skip the swap and retry next
        // interval.
        this.log.warn(
          "No skills downloaded this cycle; keeping existing skills cache",
        );
        return { updated: false };
      }

      // Nothing downloaded and no cache to fall back on. Surface a clear,
      // actionable message rather than the opaque "No skills found from any
      // source" — it tells the user what happened, that they're not stuck
      // (bundled skills still work), and that it will recover on its own.
      throw new Error(
        "Couldn't download skills from PostHog (the skills and context-mill " +
          "sources both returned nothing, likely a temporary network or " +
          "server issue) and no previously downloaded skills were cached. " +
          "The skills bundled with this version of PostHog are still " +
          "available, and PostHog will retry automatically on the next " +
          "update.",
      );
    }

    // Step 4: atomic swap
    const oldSkillsDir = `${input.runtimeSkillsDir}.old`;
    await this.step({
      name: "swap-skills-cache",
      execute: async () => {
        await rm(oldSkillsDir, { recursive: true, force: true });
        const hadExisting = existsSync(input.runtimeSkillsDir);
        if (hadExisting) {
          await rename(input.runtimeSkillsDir, oldSkillsDir);
        }
        await rename(newSkillsDir, input.runtimeSkillsDir);
        await rm(oldSkillsDir, { recursive: true, force: true });
        return hadExisting;
      },
      rollback: async (hadExisting) => {
        try {
          if (existsSync(input.runtimeSkillsDir)) {
            await rename(input.runtimeSkillsDir, newSkillsDir);
          }
          if (hadExisting && existsSync(oldSkillsDir)) {
            await rename(oldSkillsDir, input.runtimeSkillsDir);
          }
        } catch {
          // Best-effort rollback
        }
      },
    });

    // Step 5: overlay skills (non-fatal)
    await this.readOnlyStep("overlay-skills", async () => {
      try {
        await overlayDownloadedSkills(
          input.runtimeSkillsDir,
          input.runtimePluginDir,
        );
      } catch (err) {
        this.log.warn("Failed to overlay skills", {
          error: err instanceof Error ? err.message : String(err),
        });
      }
    });

    return { updated: true };
  }

  /**
   * Downloads a skills zip from `url`, extracts it, and merges skill directories into `destDir`.
   */
  private async downloadAndMergeSkills(
    url: string,
    tempDir: string,
    destDir: string,
    downloadFile: (url: string, destPath: string) => Promise<void>,
  ): Promise<void> {
    const zipPath = join(tempDir, "skills.zip");
    await downloadFile(url, zipPath);

    const extractDir = join(tempDir, "extracted");
    await mkdir(extractDir, { recursive: true });
    await extractZip(zipPath, extractDir);

    const skillsSource = await this.findSkillsDir(extractDir);
    if (!skillsSource) {
      this.log.warn("No skills directory found in archive");
      return;
    }

    const entries = await readdir(skillsSource, { withFileTypes: true });
    for (const entry of entries) {
      if (entry.isDirectory()) {
        const src = join(skillsSource, entry.name);
        const dest = join(destDir, entry.name);
        await rm(dest, { recursive: true, force: true });
        await cp(src, dest, { recursive: true });
      }
    }
  }

  /**
   * Finds the skills directory inside an extracted zip.
   * Handles: skills/ at root, nested (e.g. posthog/skills/), or skill dirs directly at root.
   */
  private async findSkillsDir(extractDir: string): Promise<string | null> {
    const direct = join(extractDir, "skills");
    if (existsSync(direct)) {
      return direct;
    }

    const entries = await readdir(extractDir, { withFileTypes: true });
    for (const entry of entries) {
      if (entry.isDirectory()) {
        const nested = join(extractDir, entry.name, "skills");
        if (existsSync(nested)) {
          return nested;
        }
      }
    }

    const hasSkillDirs = entries.some(
      (e) =>
        e.isDirectory() && existsSync(join(extractDir, e.name, "SKILL.md")),
    );
    if (hasSkillDirs) {
      return extractDir;
    }

    return null;
  }

  /**
   * Downloads context-mill zip-of-zips, extracts omnibus-* inner zips,
   * strips the "omnibus-" prefix, patches SKILL.md, and merges into destDir.
   */
  private async downloadAndMergeContextMillSkills(
    url: string,
    tempDir: string,
    destDir: string,
    downloadFile: (url: string, destPath: string) => Promise<void>,
  ): Promise<void> {
    const zipPath = join(tempDir, "context-mill.zip");
    await downloadFile(url, zipPath);

    const extractDir = join(tempDir, "cm-extracted");
    await mkdir(extractDir, { recursive: true });
    await extractZip(zipPath, extractDir);

    const files = await readdir(extractDir);
    for (const file of files) {
      if (!file.startsWith("omnibus-") || !file.endsWith(".zip")) continue;

      const strippedName = file.replace(/^omnibus-/, "").replace(/\.zip$/, "");
      const innerZipPath = join(extractDir, file);
      const innerZipData = await readFile(innerZipPath);
      const innerEntries = await unzipAsync(new Uint8Array(innerZipData));
      const skillDestDir = join(destDir, strippedName);
      await mkdir(skillDestDir, { recursive: true });

      for (const [innerFile, innerContent] of Object.entries(innerEntries)) {
        if (innerFile.endsWith("/")) {
          await mkdir(join(skillDestDir, innerFile), { recursive: true });
        } else {
          const fullPath = join(skillDestDir, innerFile);
          await mkdir(dirname(fullPath), { recursive: true });
          if (basename(innerFile) === "SKILL.md") {
            const text = new TextDecoder().decode(innerContent);
            const patched = text.replace(/^(name:\s*)omnibus-/m, "$1");
            await writeFile(fullPath, patched);
          } else {
            await writeFile(fullPath, innerContent);
          }
        }
      }
    }
  }
}
