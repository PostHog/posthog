use std::sync::Arc;

use crate::{
    error::UnhandledError,
    frames::{Frame, RawFrame},
    langs::native::DebugImage,
    metric_consts::{FRAME_RESOLVER_OPERATOR, NATIVE_INLINE_GROUPS},
    stages::{pipeline::HandledError, resolution::ResolutionStage},
    types::{
        batch::Batch,
        exception_properties::ExceptionProperties,
        operator::{OperatorResult, ValueOperator},
        Exception, ExceptionList, Stacktrace,
    },
};

#[derive(Clone, Default)]
pub struct FrameResolver;

impl FrameResolver {
    pub async fn resolve_exception_list_frames(
        team_id: i32,
        list: ExceptionList,
        debug_images: Arc<Vec<DebugImage>>,
        ctx: ResolutionStage,
    ) -> Result<ExceptionList, UnhandledError> {
        let res = Batch::from(list.0)
            .apply_func(
                move |exc, ctx| {
                    let debug_images = debug_images.clone();
                    async move {
                        FrameResolver::resolve_exception_frames(team_id, exc, debug_images, ctx)
                            .await
                    }
                },
                ctx,
            )
            .await?;
        Ok(Vec::from(res).into())
    }

    pub async fn resolve_exception_frames(
        team_id: i32,
        mut exc: Exception,
        debug_images: Arc<Vec<DebugImage>>,
        ctx: ResolutionStage,
    ) -> Result<Exception, UnhandledError> {
        exc.stack = match exc.stack {
            Some(Stacktrace::Raw { frames }) => {
                let units = partition_into_units(frames);
                let frame_batches: Batch<Vec<Frame>> = Batch::from(units)
                    .apply_func(
                        move |unit, ctx| {
                            let debug_images = debug_images.clone();
                            async move {
                                FrameResolver::resolve_frame_unit(
                                    team_id,
                                    &unit,
                                    &debug_images,
                                    ctx,
                                )
                                .await
                            }
                        },
                        ctx,
                    )
                    .await?;

                let frames: Vec<Frame> = frame_batches.into_iter().flatten().collect();
                Some(Stacktrace::Resolved { frames })
            }
            stack => stack,
        };
        Ok(exc)
    }

    /// Resolve one partition unit: a lone frame, or a client-expanded native
    /// inline group (physical lead frame + the inline frames the client
    /// expanded from the same address).
    ///
    /// The lead resolves through the normal per-frame path. When its address
    /// symbolicates to an inline expansion, the server-side expansion
    /// supersedes the whole group, so the chain isn't duplicated. When it
    /// symbolicates to a single frame against a multi-layer client group, the
    /// uploaded symbols carry no inline info for it (e.g. a stripped binary
    /// that kept its build id): the server's canonical physical frame is kept
    /// and the client's inline members are salvaged behind it, which stays
    /// duplicate-free because the member layers are disjoint from the
    /// physical layer. When it doesn't resolve at all, the client expansion
    /// passes through verbatim. Members always go through the per-frame path
    /// (their `inline` marker makes them resolution-free), so every emitted
    /// frame is backed by the per-frame cache and stored records.
    async fn resolve_frame_unit(
        team_id: i32,
        unit: &[RawFrame],
        debug_images: &[DebugImage],
        ctx: ResolutionStage,
    ) -> Result<Vec<Frame>, UnhandledError> {
        let (lead, members) = unit.split_first().expect("partition units are non-empty");

        let mut frames =
            FrameResolver::resolve_frame(team_id, lead, debug_images, ctx.clone()).await?;

        if members.is_empty() {
            return Ok(frames);
        }

        let server_resolved = frames.first().is_some_and(|f| f.resolved);
        if server_resolved {
            if frames.len() > 1 {
                // Replaces even a slightly shallower multi-frame expansion:
                // same-build symbols normally match the client's depth, and
                // deferring to the server keeps debug-built and stripped
                // clients of the same binary converging on identical stacks
                // and fingerprints once symbols exist. Splicing the client's
                // extra layers in would need chain alignment between two
                // symbolications, which is exactly the duplication hazard the
                // group contract avoids.
                metrics::counter!(NATIVE_INLINE_GROUPS, "outcome" => "replaced").increment(1);
                return Ok(frames);
            }
            // Single-frame resolution against a multi-layer client group: no
            // inline info in the uploaded symbols. Keep the canonical physical
            // frame, salvage the client members behind it.
            metrics::counter!(NATIVE_INLINE_GROUPS, "outcome" => "merged_client_inlines")
                .increment(1);
        } else {
            metrics::counter!(NATIVE_INLINE_GROUPS, "outcome" => "kept").increment(1);
        }

        for member in members {
            frames.extend(
                FrameResolver::resolve_frame(team_id, member, debug_images, ctx.clone()).await?,
            );
        }
        Ok(frames)
    }

    pub async fn resolve_frame(
        team_id: i32,
        frame: &RawFrame,
        debug_images: &[DebugImage],
        ctx: ResolutionStage,
    ) -> Result<Vec<Frame>, UnhandledError> {
        let _permit = ctx.acquire_symbol_resolution_permit().await?;

        let mut resolved_frames = ctx
            .symbol_resolver
            .resolve_raw_frame(team_id, frame, debug_images)
            .await?;

        // The frame id is part of the caller/frontend lookup contract. Keep it
        // tied to the submitted raw frame here instead of trusting resolver
        // implementations to preserve the raw_id/part shape.
        resolved_frames
            .iter_mut()
            .enumerate()
            .for_each(|(index, resolved_frame)| {
                resolved_frame.frame_id = frame.frame_id(team_id, index, debug_images);
            });

        Ok(resolved_frames)
    }
}

/// Split a raw stack into resolution units, preserving order. Consecutive
/// native frames form one unit when they are a client-expanded inline group:
/// a physical (non-inline) frame carrying an instruction address, followed by
/// inline-marked frames carrying that same address. Everything else — other
/// platforms, address-less frames, orphaned inline frames — is its own unit.
///
/// Grouping keys off the `inline` markers rather than address adjacency:
/// direct recursion repeats the same return address across *distinct*
/// physical frames, and those must stay separate groups.
fn partition_into_units(frames: Vec<RawFrame>) -> Vec<Vec<RawFrame>> {
    let mut units: Vec<Vec<RawFrame>> = Vec::new();

    for frame in frames {
        if let (Some(unit), RawFrame::Native(candidate)) = (units.last_mut(), &frame) {
            if let Some(RawFrame::Native(lead)) = unit.first() {
                if !lead.inline
                    && lead.instruction_addr.is_some()
                    && candidate.continues_group_of(lead)
                {
                    unit.push(frame);
                    continue;
                }
            }
        }
        units.push(vec![frame]);
    }

    units
}

impl ValueOperator for FrameResolver {
    type Context = ResolutionStage;
    type Item = ExceptionProperties;
    type HandledError = HandledError;
    type UnhandledError = UnhandledError;

    fn name(&self) -> &'static str {
        FRAME_RESOLVER_OPERATOR
    }

    async fn execute_value(
        &self,
        mut evt: ExceptionProperties,
        ctx: ResolutionStage,
    ) -> OperatorResult<Self> {
        // Clone rather than take: `$debug_images` is serialized back onto the
        // event after resolution (rules eval and the /process response), so the
        // field must survive this stage.
        let debug_images = Arc::new(evt.debug_images.clone());
        evt.exception_list = FrameResolver::resolve_exception_list_frames(
            evt.team_id,
            evt.exception_list,
            debug_images,
            ctx,
        )
        .await?;
        Ok(Ok(evt))
    }
}

#[cfg(test)]
mod test {
    use std::sync::Arc;

    use tokio::sync::Semaphore;

    use super::*;
    use crate::{
        langs::native::test_support::{
            catalog_for_chunk, catalog_without_symbols, debug_image_at, native_frame_at,
            zip_fixture,
        },
        modes::processing::config::ProcessingConfig,
        symbolication::symbol::local::LocalSymbolResolver,
        symbolication::symbol_store::Catalog,
    };

    fn client_frame(addr: u64, image_addr: u64, inline: bool, function: &str) -> RawFrame {
        let mut frame = native_frame_at(addr, image_addr);
        frame.inline = inline;
        frame.client_resolved = true;
        frame.function = Some(function.to_string());
        frame.filename = Some("src/lib.rs".to_string());
        frame.lineno = Some(10);
        RawFrame::Native(frame)
    }

    fn unit_sizes(units: &[Vec<RawFrame>]) -> Vec<usize> {
        units.iter().map(|u| u.len()).collect()
    }

    #[test]
    fn partition_keeps_independent_frames_single() {
        let frames = vec![
            client_frame(0x10, 0x1, false, "a"),
            client_frame(0x20, 0x1, false, "b"),
        ];
        assert_eq!(unit_sizes(&partition_into_units(frames)), vec![1, 1]);
    }

    #[test]
    fn partition_groups_physical_frame_with_its_inline_members() {
        let frames = vec![
            client_frame(0x10, 0x1, false, "outer"),
            client_frame(0x10, 0x1, true, "mid"),
            client_frame(0x10, 0x1, true, "leaf"),
            client_frame(0x20, 0x1, false, "next"),
        ];
        assert_eq!(unit_sizes(&partition_into_units(frames)), vec![3, 1]);
    }

    #[test]
    fn partition_keeps_recursive_same_address_frames_separate() {
        // Direct recursion repeats the same return address across distinct
        // physical frames — bare address adjacency must not group them.
        let frames = vec![
            client_frame(0x10, 0x1, false, "recurse"),
            client_frame(0x10, 0x1, false, "recurse"),
        ];
        assert_eq!(unit_sizes(&partition_into_units(frames)), vec![1, 1]);
    }

    #[test]
    fn partition_keeps_recursive_inline_groups_separate() {
        // Inlined recursion: each recursion level is its own group, delimited
        // by its non-inline physical frame.
        let frames = vec![
            client_frame(0x10, 0x1, false, "recurse"),
            client_frame(0x10, 0x1, true, "recurse_inner"),
            client_frame(0x10, 0x1, false, "recurse"),
            client_frame(0x10, 0x1, true, "recurse_inner"),
        ];
        assert_eq!(unit_sizes(&partition_into_units(frames)), vec![2, 2]);
    }

    #[test]
    fn partition_orphan_inline_and_mismatches_stay_single() {
        // An inline frame with no preceding physical frame (e.g. malformed
        // input) stays alone, and a member with a different address or a
        // different image does not join the preceding group.
        let frames = vec![
            client_frame(0x10, 0x1, true, "orphan"),
            client_frame(0x20, 0x1, false, "lead"),
            client_frame(0x21, 0x1, true, "stray_addr"),
            client_frame(0x30, 0x1, false, "lead_2"),
            client_frame(0x30, 0x2, true, "stray_image"),
        ];
        assert_eq!(
            unit_sizes(&partition_into_units(frames)),
            vec![1, 1, 1, 1, 1]
        );
    }

    #[test]
    fn partition_non_native_frames_break_groups() {
        let custom: RawFrame = serde_json::from_str(
            r#"{"platform": "custom", "function": "f", "in_app": true, "lang": "elixir"}"#,
        )
        .unwrap();
        let frames = vec![
            client_frame(0x10, 0x1, false, "lead"),
            custom,
            client_frame(0x10, 0x1, true, "member"),
        ];
        assert_eq!(unit_sizes(&partition_into_units(frames)), vec![1, 1, 1]);
    }

    const INLINE_ELF: &[u8] =
        include_bytes!("../../../../../tests/static/native/test_binary_inline");
    const INLINE_CHUNK_ID: &str = "140ab543-c098-09dc-22b6-11f72e46d6fe";
    const SLIDE_BASE: u64 = 0x7f0000000000;
    // 0x1475: after the -1 call-site adjustment the lookup lands inside
    // inlined_leaf as inlined (via inner_function) into outer_function.
    const INLINE_ADDR: u64 = SLIDE_BASE + 0x1475;

    fn resolution_stage(db: &sqlx::PgPool, catalog: Catalog) -> ResolutionStage {
        let mut config = ProcessingConfig::init_with_defaults().unwrap();
        config.resolver.object_storage_bucket = "test-bucket".to_string();
        ResolutionStage {
            symbol_resolver: Arc::new(LocalSymbolResolver::new(
                &config.resolver,
                Arc::new(catalog),
                db.clone(),
            )),
            symbol_resolution_limiter: Arc::new(Semaphore::new(4)),
            remote: None,
        }
    }

    fn client_expanded_group() -> Vec<RawFrame> {
        vec![
            client_frame(INLINE_ADDR, SLIDE_BASE, false, "client_outer"),
            client_frame(INLINE_ADDR, SLIDE_BASE, true, "client_inner"),
            client_frame(INLINE_ADDR, SLIDE_BASE, true, "client_leaf"),
        ]
    }

    fn exception_with(frames: Vec<RawFrame>) -> Exception {
        Exception {
            exception_type: "Panic".to_string(),
            exception_message: "boom".to_string(),
            module: None,
            exception_id: None,
            mechanism: None,
            thread_id: None,
            stack: Some(Stacktrace::Raw { frames }),
        }
    }

    fn resolved_frames(exc: Exception) -> Vec<Frame> {
        match exc.stack {
            Some(Stacktrace::Resolved { frames }) => frames,
            other => panic!("expected a resolved stacktrace, got {other:?}"),
        }
    }

    /// When the group's address symbolicates, the server expansion replaces
    /// the whole client expansion — same logical frames, no duplication.
    #[sqlx::test(migrations = "./tests/test_migrations")]
    async fn client_expanded_group_is_replaced_by_server_expansion(db: sqlx::PgPool) {
        let catalog = catalog_for_chunk(&db, INLINE_CHUNK_ID, zip_fixture(INLINE_ELF, None)).await;
        let stage = resolution_stage(&db, catalog);
        let debug_images = Arc::new(vec![debug_image_at(INLINE_CHUNK_ID, SLIDE_BASE)]);

        let group = client_expanded_group();
        let lead = group[0].clone();
        let exc = exception_with(group);

        let frames = resolved_frames(
            FrameResolver::resolve_exception_frames(1, exc, debug_images.clone(), stage.clone())
                .await
                .unwrap(),
        );

        let names: Vec<_> = frames
            .iter()
            .map(|f| f.resolved_name.as_deref().unwrap())
            .collect();
        assert_eq!(
            names,
            ["outer_function", "inner_function", "inlined_leaf"],
            "expected the server expansion to replace the client group"
        );
        assert!(frames.iter().all(|f| f.resolved));

        // The replacement frames all carry ids derived from the group's
        // physical frame, matching the single-address-frame contract.
        for (index, frame) in frames.iter().enumerate() {
            assert_eq!(frame.frame_id, lead.frame_id(1, index, &debug_images));
        }

        // A client group deeper than the server's multi-frame expansion is
        // still replaced: the server's inline chain is canonical.
        let mut deeper = client_expanded_group();
        deeper.push(client_frame(INLINE_ADDR, SLIDE_BASE, true, "client_extra"));
        let frames = resolved_frames(
            FrameResolver::resolve_exception_frames(
                1,
                exception_with(deeper),
                debug_images.clone(),
                stage,
            )
            .await
            .unwrap(),
        );
        assert_eq!(frames.len(), 3);
        assert!(frames.iter().all(|f| f.resolved));
    }

    /// When the address can't be symbolicated (no symbols uploaded), the
    /// client's expansion passes through verbatim: the physical frame keeps
    /// its client fields plus the failure reason, and the inline members
    /// survive untouched.
    #[sqlx::test(migrations = "./tests/test_migrations")]
    async fn client_expanded_group_is_kept_when_symbols_are_missing(db: sqlx::PgPool) {
        let catalog = catalog_without_symbols(&db);
        let stage = resolution_stage(&db, catalog);
        let debug_images = Arc::new(vec![debug_image_at(INLINE_CHUNK_ID, SLIDE_BASE)]);

        let exc = exception_with(client_expanded_group());

        let frames = resolved_frames(
            FrameResolver::resolve_exception_frames(1, exc, debug_images.clone(), stage)
                .await
                .unwrap(),
        );

        let names: Vec<_> = frames
            .iter()
            .map(|f| f.resolved_name.as_deref().unwrap())
            .collect();
        assert_eq!(names, ["client_outer", "client_inner", "client_leaf"]);

        // The physical frame records why server resolution didn't happen…
        assert!(!frames[0].resolved);
        assert!(frames[0]
            .resolve_failure
            .as_deref()
            .is_some_and(|f| f.contains(INLINE_CHUNK_ID)));
        // …while the client-expanded members pass through as resolved frames.
        assert!(frames[1..].iter().all(|f| f.resolved));
        assert!(frames[1..].iter().all(|f| f.resolve_failure.is_none()));
        assert!(frames.iter().all(|f| f.line == Some(10)));
    }

    /// A single-frame resolution against a multi-layer client group means
    /// the uploaded symbols carry no inline info (e.g. a stripped binary that
    /// kept its build id): the server's canonical physical frame is kept and
    /// the client's inline members are salvaged behind it.
    #[sqlx::test(migrations = "./tests/test_migrations")]
    async fn inline_less_symbols_keep_client_inline_members(db: sqlx::PgPool) {
        const NOPIE_ELF: &[u8] =
            include_bytes!("../../../../../tests/static/native/test_binary_nopie");
        const NOPIE_CHUNK_ID: &str = "7561847b-1054-7eb3-7763-4415adfaa134";
        // Non-PIE: loads at its link base; 0x14a8 is inside inner_function,
        // which has no inlined callees, so the lookup yields a single frame.
        const NOPIE_BASE: u64 = 0x1000000;
        const NOPIE_ADDR: u64 = NOPIE_BASE + 0x14a8;

        let catalog = catalog_for_chunk(&db, NOPIE_CHUNK_ID, zip_fixture(NOPIE_ELF, None)).await;
        let stage = resolution_stage(&db, catalog);
        let debug_images = Arc::new(vec![debug_image_at(NOPIE_CHUNK_ID, NOPIE_BASE)]);

        let group = vec![
            client_frame(NOPIE_ADDR, NOPIE_BASE, false, "client_physical"),
            client_frame(NOPIE_ADDR, NOPIE_BASE, true, "client_inline_a"),
            client_frame(NOPIE_ADDR, NOPIE_BASE, true, "client_inline_b"),
        ];
        let exc = exception_with(group);

        let frames = resolved_frames(
            FrameResolver::resolve_exception_frames(1, exc, debug_images.clone(), stage)
                .await
                .unwrap(),
        );

        let names: Vec<_> = frames
            .iter()
            .map(|f| f.resolved_name.as_deref().unwrap())
            .collect();
        assert_eq!(
            names,
            ["inner_function", "client_inline_a", "client_inline_b"],
            "expected the server physical frame plus the client inline members"
        );
        assert!(frames[0].resolved);
        assert!(frames[1..].iter().all(|f| f.resolve_failure.is_none()));
    }

    /// The same crash must fingerprint identically under the v2 normalizing
    /// algorithm whether its inline group was kept (no symbols uploaded) or
    /// replaced by the server expansion: v2 hashes every frame and only the
    /// file-name component of sources, so the client's absolute paths and the
    /// server's short names agree. (v1 stays frozen and splits on the path
    /// spelling, which is why new issues key on v2.)
    #[sqlx::test(migrations = "./tests/test_migrations")]
    async fn kept_and_replaced_groups_fingerprint_identically_under_v2(db: sqlx::PgPool) {
        use crate::fingerprinting::FingerprintVersion;

        // Server-parity names (what posthog-rs actually sends) plus an
        // absolute capture-host path for the fixture's source file.
        let client_group = || -> Vec<RawFrame> {
            [
                ("outer_function", false),
                ("inner_function", true),
                ("inlined_leaf", true),
            ]
            .into_iter()
            .map(|(function, inline)| {
                let RawFrame::Native(mut frame) =
                    client_frame(INLINE_ADDR, SLIDE_BASE, inline, function)
                else {
                    unreachable!("client_frame builds native frames");
                };
                frame.filename =
                    Some("/build/host/cymbal_tests/native/test_binary_inline.c".to_string());
                frame.meta.in_app = true;
                RawFrame::Native(frame)
            })
            .collect()
        };
        let debug_images = Arc::new(vec![debug_image_at(INLINE_CHUNK_ID, SLIDE_BASE)]);

        // Distinct team ids so the two runs don't share cached frame records.
        let kept_stage = resolution_stage(&db, catalog_without_symbols(&db));
        let kept = FrameResolver::resolve_exception_frames(
            2,
            exception_with(client_group()),
            debug_images.clone(),
            kept_stage,
        )
        .await
        .unwrap();

        let replaced_catalog =
            catalog_for_chunk(&db, INLINE_CHUNK_ID, zip_fixture(INLINE_ELF, None)).await;
        let replaced_stage = resolution_stage(&db, replaced_catalog);
        let replaced = FrameResolver::resolve_exception_frames(
            1,
            exception_with(client_group()),
            debug_images.clone(),
            replaced_stage,
        )
        .await
        .unwrap();

        // Sanity: the two paths really did produce different representations.
        let kept_frames = resolved_frames(kept.clone());
        let replaced_frames = resolved_frames(replaced.clone());
        assert!(kept_frames[0].resolve_failure.is_some());
        assert!(replaced_frames.iter().all(|f| f.resolved));

        let kept_fp = FingerprintVersion::V2.compute(&vec![kept].into());
        let replaced_fp = FingerprintVersion::V2.compute(&vec![replaced].into());
        assert_eq!(
            kept_fp.value, replaced_fp.value,
            "kept: {:#?}\nreplaced: {:#?}",
            kept_fp.record, replaced_fp.record
        );
    }
}
