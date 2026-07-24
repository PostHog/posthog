import { exec } from "node:child_process";
import fs from "node:fs/promises";
import path from "node:path";
import { promisify } from "node:util";
import {
  CLIPBOARD_SERVICE,
  type IClipboard,
} from "@posthog/platform/clipboard";
import { FILE_ICON_SERVICE, type IFileIcon } from "@posthog/platform/file-icon";
import { inject, injectable } from "inversify";
import { EXTERNAL_APPS_STORE } from "./identifiers";
import type { ExternalAppsStore } from "./ports";
import type { DetectedApplication } from "./schemas";
import type { AppDefinition } from "./types";

const execAsync = promisify(exec);

const LOCALAPPDATA = process.env.LOCALAPPDATA ?? "";
const PROGRAMFILES = process.env.PROGRAMFILES ?? "C:\\Program Files";

@injectable()
export class ExternalAppsService {
  private readonly APP_DEFINITIONS: Record<string, AppDefinition> = {
    // Cross-platform editors
    vscode: {
      type: "editor",
      darwin: { path: "/Applications/Visual Studio Code.app" },
      win32: {
        paths: [
          path.join(LOCALAPPDATA, "Programs", "Microsoft VS Code", "Code.exe"),
        ],
        exeName: "code",
      },
    },
    cursor: {
      type: "editor",
      darwin: { path: "/Applications/Cursor.app" },
      win32: {
        paths: [path.join(LOCALAPPDATA, "Programs", "cursor", "Cursor.exe")],
        exeName: "cursor",
      },
    },
    windsurf: {
      type: "editor",
      darwin: { path: "/Applications/Windsurf.app" },
      win32: {
        paths: [
          path.join(LOCALAPPDATA, "Programs", "Windsurf", "Windsurf.exe"),
        ],
        exeName: "windsurf",
      },
    },
    zed: {
      type: "editor",
      darwin: { path: "/Applications/Zed.app" },
      win32: {
        paths: [path.join(LOCALAPPDATA, "Programs", "Zed", "Zed.exe")],
        exeName: "zed",
      },
    },
    sublime: {
      type: "editor",
      darwin: { path: "/Applications/Sublime Text.app" },
      win32: {
        paths: [path.join(PROGRAMFILES, "Sublime Text", "sublime_text.exe")],
        exeName: "subl",
      },
    },
    lapce: {
      type: "editor",
      darwin: { path: "/Applications/Lapce.app" },
      win32: {
        paths: [path.join(PROGRAMFILES, "Lapce", "lapce.exe")],
        exeName: "lapce",
      },
    },
    emacs: {
      type: "editor",
      darwin: { path: "/Applications/Emacs.app" },
      win32: {
        paths: [path.join(PROGRAMFILES, "Emacs", "bin", "emacs.exe")],
        exeName: "emacs",
      },
    },
    androidstudio: {
      type: "editor",
      darwin: { path: "/Applications/Android Studio.app" },
      win32: {
        paths: [
          path.join(
            PROGRAMFILES,
            "Android",
            "Android Studio",
            "bin",
            "studio64.exe",
          ),
        ],
      },
    },
    fleet: {
      type: "editor",
      darwin: { path: "/Applications/Fleet.app" },
      win32: {
        paths: [path.join(LOCALAPPDATA, "JetBrains", "Fleet", "fleet.exe")],
      },
    },
    intellij: {
      type: "editor",
      darwin: { path: "/Applications/IntelliJ IDEA.app" },
      win32: {
        paths: [
          path.join(
            PROGRAMFILES,
            "JetBrains",
            "IntelliJ IDEA",
            "bin",
            "idea64.exe",
          ),
        ],
      },
    },
    intellijce: {
      type: "editor",
      darwin: { path: "/Applications/IntelliJ IDEA CE.app" },
      win32: {
        paths: [
          path.join(
            PROGRAMFILES,
            "JetBrains",
            "IntelliJ IDEA Community Edition",
            "bin",
            "idea64.exe",
          ),
        ],
      },
    },
    intellijultimate: {
      type: "editor",
      darwin: { path: "/Applications/IntelliJ IDEA Ultimate.app" },
      win32: {
        paths: [
          path.join(
            PROGRAMFILES,
            "JetBrains",
            "IntelliJ IDEA",
            "bin",
            "idea64.exe",
          ),
        ],
      },
    },
    webstorm: {
      type: "editor",
      darwin: { path: "/Applications/WebStorm.app" },
      win32: {
        paths: [
          path.join(
            PROGRAMFILES,
            "JetBrains",
            "WebStorm",
            "bin",
            "webstorm64.exe",
          ),
        ],
      },
    },
    pycharm: {
      type: "editor",
      darwin: { path: "/Applications/PyCharm.app" },
      win32: {
        paths: [
          path.join(
            PROGRAMFILES,
            "JetBrains",
            "PyCharm",
            "bin",
            "pycharm64.exe",
          ),
        ],
      },
    },
    pycharmce: {
      type: "editor",
      darwin: { path: "/Applications/PyCharm CE.app" },
      win32: {
        paths: [
          path.join(
            PROGRAMFILES,
            "JetBrains",
            "PyCharm Community Edition",
            "bin",
            "pycharm64.exe",
          ),
        ],
      },
    },
    pycharmpro: {
      type: "editor",
      darwin: { path: "/Applications/PyCharm Professional Edition.app" },
      win32: {
        paths: [
          path.join(
            PROGRAMFILES,
            "JetBrains",
            "PyCharm Professional",
            "bin",
            "pycharm64.exe",
          ),
        ],
      },
    },
    phpstorm: {
      type: "editor",
      darwin: { path: "/Applications/PhpStorm.app" },
      win32: {
        paths: [
          path.join(
            PROGRAMFILES,
            "JetBrains",
            "PhpStorm",
            "bin",
            "phpstorm64.exe",
          ),
        ],
      },
    },
    rubymine: {
      type: "editor",
      darwin: { path: "/Applications/RubyMine.app" },
      win32: {
        paths: [
          path.join(
            PROGRAMFILES,
            "JetBrains",
            "RubyMine",
            "bin",
            "rubymine64.exe",
          ),
        ],
      },
    },
    goland: {
      type: "editor",
      darwin: { path: "/Applications/GoLand.app" },
      win32: {
        paths: [
          path.join(PROGRAMFILES, "JetBrains", "GoLand", "bin", "goland64.exe"),
        ],
      },
    },
    clion: {
      type: "editor",
      darwin: { path: "/Applications/CLion.app" },
      win32: {
        paths: [
          path.join(PROGRAMFILES, "JetBrains", "CLion", "bin", "clion64.exe"),
        ],
      },
    },
    rider: {
      type: "editor",
      darwin: { path: "/Applications/Rider.app" },
      win32: {
        paths: [
          path.join(PROGRAMFILES, "JetBrains", "Rider", "bin", "rider64.exe"),
        ],
      },
    },
    datagrip: {
      type: "editor",
      darwin: { path: "/Applications/DataGrip.app" },
      win32: {
        paths: [
          path.join(
            PROGRAMFILES,
            "JetBrains",
            "DataGrip",
            "bin",
            "datagrip64.exe",
          ),
        ],
      },
    },
    dataspell: {
      type: "editor",
      darwin: { path: "/Applications/DataSpell.app" },
      win32: {
        paths: [
          path.join(
            PROGRAMFILES,
            "JetBrains",
            "DataSpell",
            "bin",
            "dataspell64.exe",
          ),
        ],
      },
    },
    rustrover: {
      type: "editor",
      darwin: { path: "/Applications/RustRover.app" },
      win32: {
        paths: [
          path.join(
            PROGRAMFILES,
            "JetBrains",
            "RustRover",
            "bin",
            "rustrover64.exe",
          ),
        ],
      },
    },
    aqua: {
      type: "editor",
      darwin: { path: "/Applications/Aqua.app" },
      win32: {
        paths: [
          path.join(PROGRAMFILES, "JetBrains", "Aqua", "bin", "aqua64.exe"),
        ],
      },
    },
    writerside: {
      type: "editor",
      darwin: { path: "/Applications/Writerside.app" },
      win32: {
        paths: [
          path.join(
            PROGRAMFILES,
            "JetBrains",
            "Writerside",
            "bin",
            "writerside64.exe",
          ),
        ],
      },
    },
    eclipse: {
      type: "editor",
      darwin: { path: "/Applications/Eclipse.app" },
      win32: {
        paths: [path.join(PROGRAMFILES, "Eclipse", "eclipse.exe")],
        exeName: "eclipse",
      },
    },
    netbeans: {
      type: "editor",
      darwin: { path: "/Applications/NetBeans.app" },
      win32: {
        paths: [path.join(PROGRAMFILES, "NetBeans", "bin", "netbeans64.exe")],
      },
    },
    netbeansapache: {
      type: "editor",
      darwin: { path: "/Applications/Apache NetBeans.app" },
      win32: {
        paths: [path.join(PROGRAMFILES, "NetBeans", "bin", "netbeans64.exe")],
      },
    },
    // macOS-only editors
    nova: { type: "editor", darwin: { path: "/Applications/Nova.app" } },
    bbedit: { type: "editor", darwin: { path: "/Applications/BBEdit.app" } },
    textmate: {
      type: "editor",
      darwin: { path: "/Applications/TextMate.app" },
    },
    xcode: { type: "editor", darwin: { path: "/Applications/Xcode.app" } },
    appcode: {
      type: "editor",
      darwin: { path: "/Applications/AppCode.app" },
    },
    // macOS-only terminals
    iterm: { type: "terminal", darwin: { path: "/Applications/iTerm.app" } },
    warp: { type: "terminal", darwin: { path: "/Applications/Warp.app" } },
    terminal: {
      type: "terminal",
      darwin: { path: "/System/Applications/Utilities/Terminal.app" },
    },
    ghostty: {
      type: "terminal",
      darwin: { path: "/Applications/Ghostty.app" },
    },
    cmux: {
      type: "terminal",
      darwin: { path: "/Applications/cmux.app" },
    },
    kitty: {
      type: "terminal",
      darwin: { path: "/Applications/kitty.app" },
    },
    rio: { type: "terminal", darwin: { path: "/Applications/Rio.app" } },
    // Cross-platform terminals
    alacritty: {
      type: "terminal",
      darwin: { path: "/Applications/Alacritty.app" },
      win32: {
        paths: [path.join(PROGRAMFILES, "Alacritty", "alacritty.exe")],
        exeName: "alacritty",
      },
    },
    hyper: {
      type: "terminal",
      darwin: { path: "/Applications/Hyper.app" },
      win32: {
        paths: [path.join(LOCALAPPDATA, "Programs", "Hyper", "Hyper.exe")],
      },
    },
    tabby: {
      type: "terminal",
      darwin: { path: "/Applications/Tabby.app" },
      win32: {
        paths: [path.join(LOCALAPPDATA, "Programs", "Tabby", "Tabby.exe")],
      },
    },
    // Windows-only terminals
    windowsterminal: {
      type: "terminal",
      win32: {
        paths: [path.join(LOCALAPPDATA, "Microsoft", "WindowsApps", "wt.exe")],
        exeName: "wt",
      },
    },
    // Git clients
    gitkraken: {
      type: "git-client",
      darwin: { path: "/Applications/GitKraken.app" },
    },
    // File managers
    finder: {
      type: "file-manager",
      darwin: { path: "/System/Library/CoreServices/Finder.app" },
    },
    explorer: {
      type: "file-manager",
      win32: {
        paths: [
          path.join(process.env.SYSTEMROOT ?? "C:\\Windows", "explorer.exe"),
        ],
      },
    },
  };

  private readonly DISPLAY_NAMES: Record<string, string> = {
    vscode: "VS Code",
    cursor: "Cursor",
    windsurf: "Windsurf",
    zed: "Zed",
    sublime: "Sublime Text",
    nova: "Nova",
    bbedit: "BBEdit",
    textmate: "TextMate",
    lapce: "Lapce",
    emacs: "Emacs",
    xcode: "Xcode",
    androidstudio: "Android Studio",
    fleet: "Fleet",
    intellij: "IntelliJ IDEA",
    intellijce: "IntelliJ IDEA CE",
    intellijultimate: "IntelliJ IDEA Ultimate",
    webstorm: "WebStorm",
    pycharm: "PyCharm",
    pycharmce: "PyCharm CE",
    pycharmpro: "PyCharm Professional",
    phpstorm: "PhpStorm",
    rubymine: "RubyMine",
    goland: "GoLand",
    clion: "CLion",
    rider: "Rider",
    datagrip: "DataGrip",
    dataspell: "DataSpell",
    rustrover: "RustRover",
    aqua: "Aqua",
    writerside: "Writerside",
    appcode: "AppCode",
    eclipse: "Eclipse",
    netbeans: "NetBeans",
    netbeansapache: "Apache NetBeans",
    iterm: "iTerm",
    warp: "Warp",
    terminal: "Terminal",
    alacritty: "Alacritty",
    kitty: "Kitty",
    ghostty: "Ghostty",
    cmux: "cmux",
    hyper: "Hyper",
    tabby: "Tabby",
    rio: "Rio",
    finder: "Finder",
    windowsterminal: "Windows Terminal",
    explorer: "Explorer",
    gitkraken: "GitKraken",
  };

  private cachedApps: DetectedApplication[] | null = null;
  private detectionPromise: Promise<DetectedApplication[]> | null = null;

  constructor(
    @inject(CLIPBOARD_SERVICE)
    private readonly clipboard: IClipboard,
    @inject(FILE_ICON_SERVICE)
    private readonly fileIcon: IFileIcon,
    @inject(EXTERNAL_APPS_STORE)
    private readonly store: ExternalAppsStore,
  ) {}

  private async extractIcon(appPath: string): Promise<string | undefined> {
    const dataUrl = await this.fileIcon.getAsDataUrl(appPath);
    return dataUrl ?? undefined;
  }

  private async findWin32Executable(
    definition: NonNullable<AppDefinition["win32"]>,
  ): Promise<string | null> {
    for (const p of definition.paths) {
      try {
        await fs.access(p);
        return p;
      } catch {
        // path not found, try next
      }
    }

    if (definition.exeName) {
      try {
        const { stdout } = await execAsync(`where.exe ${definition.exeName}`);
        const firstLine = stdout.trim().split("\n")[0]?.trim();
        if (firstLine) {
          return firstLine;
        }
      } catch {
        // not found in PATH
      }
    }

    return null;
  }

  private async checkApplication(
    id: string,
    definition: AppDefinition,
  ): Promise<DetectedApplication | null> {
    try {
      let appPath: string;
      let command: string;

      if (process.platform === "darwin") {
        const darwinDef = definition.darwin;
        if (!darwinDef) return null;

        await fs.access(darwinDef.path);
        appPath = darwinDef.path;
        command = `open -a "${appPath}"`;
      } else if (process.platform === "win32") {
        const win32Def = definition.win32;
        if (!win32Def) return null;

        const exePath = await this.findWin32Executable(win32Def);
        if (!exePath) return null;

        appPath = exePath;
        command = `"${appPath}"`;
      } else {
        return null;
      }

      const icon = await this.extractIcon(appPath);
      const name = this.DISPLAY_NAMES[id] || id;
      return { id, name, type: definition.type, path: appPath, command, icon };
    } catch {
      return null;
    }
  }

  private async detectExternalApps(): Promise<DetectedApplication[]> {
    const apps: DetectedApplication[] = [];
    for (const [id, definition] of Object.entries(this.APP_DEFINITIONS)) {
      const detected = await this.checkApplication(id, definition);
      if (detected) {
        apps.push(detected);
      }
    }
    return apps;
  }

  async getDetectedApps(): Promise<DetectedApplication[]> {
    if (this.cachedApps) {
      return this.cachedApps;
    }

    if (this.detectionPromise) {
      return this.detectionPromise;
    }

    this.detectionPromise = this.detectExternalApps().then((apps) => {
      this.cachedApps = apps;
      this.detectionPromise = null;
      return apps;
    });

    return this.detectionPromise;
  }

  async openInApp(
    appId: string,
    targetPath: string,
  ): Promise<{ success: boolean; error?: string }> {
    try {
      const apps = await this.getDetectedApps();
      const appToOpen = apps.find((a) => a.id === appId);

      if (!appToOpen) {
        return { success: false, error: "Application not found" };
      }

      let isFile = false;
      try {
        const stat = await fs.stat(targetPath);
        isFile = stat.isFile();
      } catch {
        isFile = false;
      }

      let command: string;

      if (process.platform === "darwin") {
        if (appToOpen.id === "finder" && isFile) {
          command = `open -R "${targetPath}"`;
        } else if (appToOpen.id === "gitkraken") {
          // GitKraken ignores positional args; it needs `--args -p <path>`.
          command = `open -na "${appToOpen.path}" --args -p "${targetPath}"`;
        } else {
          command = `open -a "${appToOpen.path}" "${targetPath}"`;
        }
      } else if (process.platform === "win32") {
        command =
          appToOpen.id === "explorer" && isFile
            ? `explorer.exe /select,"${targetPath}"`
            : `"${appToOpen.path}" "${targetPath}"`;
      } else {
        return { success: false, error: "Unsupported platform" };
      }

      await execAsync(command);
      return { success: true };
    } catch (error) {
      return {
        success: false,
        error: error instanceof Error ? error.message : "Unknown error",
      };
    }
  }

  async setLastUsed(appId: string): Promise<void> {
    const prefs = this.store.getPrefs();
    this.store.setPrefs({ ...prefs, lastUsedApp: appId });
  }

  async getLastUsed(): Promise<{ lastUsedApp?: string }> {
    const prefs = this.store.getPrefs();
    return { lastUsedApp: prefs.lastUsedApp };
  }

  async copyPath(targetPath: string): Promise<void> {
    await this.clipboard.writeText(targetPath);
  }
}
