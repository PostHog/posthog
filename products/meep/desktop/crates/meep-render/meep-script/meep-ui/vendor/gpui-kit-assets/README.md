# GPUI Kit Assets

> [!NOTE]
> **The complete catalog does not make existing applications embed every icon.**
> `Assets` keeps the original 101 component icons. Applications provide additional
> icons through their own `AssetSource`, as before; they do not need to redeclare
> the component icons. Only explicitly registering `AllAssets` embeds all 1,830
> SVGs on native platforms. Depending on the crate or using the shared `IconName`
> alone does not reference every SVG payload.
>
> | Native asset configuration | Embedded SVG data | Binary increase vs. default `Assets` |
> | --- | ---: | ---: |
> | Default component icons (101) | 44.28 KiB | 0 B (baseline) |
> | Default + 2 application icons (103) | 45.04 KiB | +15.19 KiB |
> | Default + 10 application icons (111) | 48.09 KiB | +19.19 KiB |
> | Explicit `AllAssets` (1,830) | 731.45 KiB | +1.02 MiB |
>
> **In this example, adding 10 application icons costs about 19 KiB, not the full
> catalog.** Their SVGs total 3,903 bytes; the measured binary increase is 19,648
> bytes, including the extra source's lookup/list-composition code, metadata and
> alignment. These are not fixed per-icon costs or whole-application sizes.
>
> Measured with Lucide 1.43.0 on Linux x86_64, Rust 1.98.0, `--release`, and stripped
> symbols. Each program uses the same `IconName` lookup and runtime asset path.
> The extra source falls back to `Assets`, and merges, sorts and deduplicates both
> sources' lists. The 10 extras are `Accessibility`, `AlarmClock`, `Archive`,
> `Award`, `Backpack`, `Bike`, `Bird`, `Camera`, `Coffee` and `Compass`; the two-icon
> case uses the first two. SVG complexity, toolchain and source implementation
> change the result.
>
> Binary size is not RAM usage. Selected sources borrow static bytes without a
> copy/cache; actual rendering still allocates for parsing, rasterization and
> render caches. Runtime shared-name lookup can retain a name/path table, and
> Cargo's downloaded package/build artifacts still contain the complete catalog.
> On WASM, `Assets::new(endpoint)` and `AllAssets::new(endpoint)` use the existing
> on-demand CDN loader instead of embedding the complete bundle.

The shared icon names and assets for [GPUI Kit](https://gpui-kit.com), exposed as
`gpui_kit::assets`. The crate depends on GPUI, not GPUI Component, so Base and
alternative presentation layers can use its complete `IconName` catalog.

`gpui_kit::assets::IconName` provides the complete shared catalog without a
Component dependency. `gpui_kit::component::IconName` remains the original
compatibility enum: existing imports, exhaustive matches and `.view(cx)` calls
continue to work without a new trait import. `Icon::new(...)` accepts either
type. A legacy name converts into the shared name with `.into()`.

For the new shared enum, use `Icon::new(name).view(cx)` when a component entity
is needed, or import `gpui_kit::component::IconNameExt` to call `name.view(cx)`.

The catalog contains all 1,818 Lucide 1.43.0 icons plus 12 retained GPUI Kit
icons. `IconName::ALL` enumerates it; names are generated from bundled SVGs
at build time without network access or another crate's source directory.

## Default component icons and application extras

Keep the existing registration:

```rust
use gpui_kit::assets::Assets;
let app = gpui_kit::application().with_assets(Assets);
```

On native platforms, this embeds only the original component icons listed in
`default-icons.txt`. Existing `Assets::get`, `Assets::iter`, `Assets::new` and
`AssetSource` behavior remain available. Applications can embed additional SVGs
with their own asset source and fall back to `Assets` for component paths, as
before. See [Icons & Assets](https://gpui-kit.com/docs/assets) and
[the extra-assets example](examples/extra_assets.rs) for source composition.

For selecting bundled extras without copying SVG files, the optional macro
creates a separate source:

```rust
use gpui_kit::assets::icon_assets;
icon_assets!(ExtraIcons, [Accessibility, AlarmClock]);
```

Compose `ExtraIcons` with `Assets` in your application's `AssetSource`; it does
not replace the default component bundle automatically. Only the selected SVGs
are referenced on native and WASM, unlisted paths return `Ok(None)`, and loads
borrow static bytes. Selection is explicit at compile time. Optional visibility
is supported (`icon_assets!(pub ExtraIcons, [...])`). Applications without
Component can register a selected source alone.

## Explicit complete bundle

Register `AllAssets` if you intentionally want every bundled icon available on
native platforms. On WASM, `Assets::new(endpoint)` and `AllAssets::new(endpoint)`
use the same existing on-demand CDN loader. Deploy `assets/icons` under
`{endpoint}/assets/icons/`. The selected macro source needs no CDN.

## Updating Lucide

`lucide.json` pins the upstream version, archive SHA-256, and canonical icon
count. Update those fields for a new release, then run from the repository root:

```sh
bun script/sync-lucide.ts
bun script/sync-lucide.ts --check
```

Requires Bun with `Bun.Archive` support. Use
`--archive /path/to/archive.tar.gz` for offline operation. The script checks
the archive hash, copies every canonical SVG and the upstream license, and
preserves custom/retired filenames. It does not expand the default component
bundle: changes to `default-icons.txt` are deliberate compatibility decisions.
`--check` verifies every upstream file byte for byte.

## License

Crate code: Apache-2.0. Lucide SVGs: ISC, with the upstream Feather-derived icons
under MIT; see [LICENSE-LUCIDE](LICENSE-LUCIDE) for complete attribution.
