import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { beforeEach, describe, expect, it } from "vitest";
import type { Environment } from "./schemas";
import { EnvironmentService } from "./service";

describe("EnvironmentService", () => {
  let service: EnvironmentService;
  let repoPath: string;

  const envsDir = () => path.join(repoPath, ".posthog-code", "environments");

  const readEnvFiles = () => fs.readdir(envsDir()).then((f) => f.sort());

  const writeRawToml = async (filename: string, content: string) => {
    const dir = envsDir();
    await fs.mkdir(dir, { recursive: true });
    await fs.writeFile(path.join(dir, filename), content, "utf-8");
  };

  const create = (
    input: Parameters<EnvironmentService["createEnvironment"]>[0],
  ) => service.createEnvironment(input, repoPath);

  const update = (
    input: Parameters<EnvironmentService["updateEnvironment"]>[0],
  ) => service.updateEnvironment(input, repoPath);

  beforeEach(async () => {
    service = new EnvironmentService();
    repoPath = await fs.mkdtemp(path.join(os.tmpdir(), "env-test-"));
  });

  describe("listEnvironments", () => {
    it("returns empty array when directory does not exist", async () => {
      expect(await service.listEnvironments(repoPath)).toEqual([]);
    });

    it("returns parsed environments", async () => {
      const env = await create({ name: "Dev" });

      const result = await service.listEnvironments(repoPath);
      expect(result).toHaveLength(1);
      expect(result[0]).toEqual(env);
    });

    it("skips invalid toml files", async () => {
      await writeRawToml("bad.toml", "not valid {{{");
      await create({ name: "Good" });

      const result = await service.listEnvironments(repoPath);
      expect(result).toHaveLength(1);
      expect(result[0].name).toBe("Good");
    });

    it("skips valid toml that does not match schema", async () => {
      await writeRawToml("wrong-schema.toml", 'title = "not an environment"');
      await create({ name: "Valid" });

      expect(await service.listEnvironments(repoPath)).toHaveLength(1);
    });

    it("ignores non-toml files", async () => {
      await writeRawToml("readme.md", "# notes");
      await create({ name: "Only" });

      expect(await service.listEnvironments(repoPath)).toHaveLength(1);
    });
  });

  describe("createEnvironment", () => {
    it("creates a toml file with slugified name", async () => {
      const env = await create({ name: "My Dev Environment" });

      expect(env).toMatchObject({ version: 1, name: "My Dev Environment" });
      expect(env.id).toBeTruthy();
      expect(await readEnvFiles()).toContain("my-dev-environment.toml");
    });

    it("handles filename collisions", async () => {
      await create({ name: "test" });
      await create({ name: "test" });

      expect(await readEnvFiles()).toEqual(["test-2.toml", "test.toml"]);
    });

    it("falls back to 'environment' slug for names with no alphanumeric chars", async () => {
      await create({ name: "---" });
      expect(await readEnvFiles()).toEqual(["environment.toml"]);
    });

    it("creates environment with actions", async () => {
      const env = await create({
        name: "Actions",
        actions: [
          { name: "Build", command: "npm run build" },
          { name: "Test", command: "npm test" },
        ],
      });

      expect(env.actions).toHaveLength(2);
      expect(env.actions?.[0].name).toBe("Build");
      expect(env.actions?.[1].name).toBe("Test");
    });

    it("round-trips setup script through toml", async () => {
      const env = await create({
        name: "Setup",
        setup: { script: "npm install\nnpm run build" },
      });

      const found = await service.getEnvironment(repoPath, env.id);
      expect(found?.setup?.script).toBe("npm install\nnpm run build");
    });

    it("round-trips action icon through toml", async () => {
      const env = await create({
        name: "Icons",
        actions: [{ name: "Run", command: "go run .", icon: "play" }],
      });

      const found = await service.getEnvironment(repoPath, env.id);
      expect(found?.actions?.[0].icon).toBe("play");
    });
  });

  describe("getEnvironment", () => {
    it("returns null for nonexistent id", async () => {
      expect(await service.getEnvironment(repoPath, "nonexistent")).toBeNull();
    });

    it("finds environment by id", async () => {
      const created = await create({ name: "Find Me" });
      expect(await service.getEnvironment(repoPath, created.id)).toEqual(
        created,
      );
    });
  });

  describe("updateEnvironment", () => {
    let env: Environment;

    beforeEach(async () => {
      env = await create({
        name: "Original",
        actions: [{ name: "Build", command: "make" }],
      });
    });

    it("updates name while preserving id and version", async () => {
      const updated = await update({ id: env.id, name: "Renamed" });

      expect(updated.id).toBe(env.id);
      expect(updated.version).toBe(1);
      expect(updated.name).toBe("Renamed");
    });

    it("keeps filename stable on rename", async () => {
      await update({ id: env.id, name: "Renamed" });
      expect(await readEnvFiles()).toEqual(["original.toml"]);
    });

    it("preserves fields not included in the update", async () => {
      const updated = await update({ id: env.id, name: "New Name" });
      expect(updated.actions).toEqual(env.actions);
    });

    it("persists update to disk", async () => {
      await update({ id: env.id, name: "Persisted" });

      const found = await service.getEnvironment(repoPath, env.id);
      expect(found?.name).toBe("Persisted");
    });

    it("throws for nonexistent id", async () => {
      await expect(update({ id: "nope", name: "X" })).rejects.toThrow(
        "Environment not found: nope",
      );
    });
  });

  describe("deleteEnvironment", () => {
    it("removes the toml file", async () => {
      const created = await create({ name: "Doomed" });
      await service.deleteEnvironment(repoPath, created.id);

      expect(await readEnvFiles()).toEqual([]);
    });

    it("does not affect other environments", async () => {
      const keep = await create({ name: "keep" });
      const remove = await create({ name: "remove" });

      await service.deleteEnvironment(repoPath, remove.id);

      const remaining = await service.listEnvironments(repoPath);
      expect(remaining).toHaveLength(1);
      expect(remaining[0].id).toBe(keep.id);
    });

    it("throws for nonexistent id", async () => {
      await expect(service.deleteEnvironment(repoPath, "nope")).rejects.toThrow(
        "Environment not found: nope",
      );
    });
  });
});
