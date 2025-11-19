use std::sync::Arc;

use common_types::error_tracking::FrameId;
use proguard::StackFrame;
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha512};
use tracing::warn;

use crate::{
    error::{FrameError, ProguardError, ResolveError, UnhandledError},
    frames::Frame,
    langs::{utils::add_raw_to_junk, CommonFrameMetadata},
    symbol_store::{
        chunk_id::OrChunkId,
        proguard::{FetchedMapping, ProguardRef},
        SymbolCatalog,
    },
};

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct RawJavaFrame {
    pub filename: Option<String>, // The relative path of the file the context line is in
    pub function: String,         // The name of the function the exception came from
    pub lineno: Option<usize>,    // The line number of the context line
    pub module: String,           // The java-import style module name the function is in
    pub map_id: Option<String>, // ID of the proguard mapping symbol set this frame can be demangled with
    #[serde(default)]
    // Java compilers sometimes generate synthetic methods, for stuff like implied accessors from the source
    // More info at https://docs.oracle.com/javase/specs/jvms/se7/html/jvms-4.html#jvms-4.7.8
    //
    // TODO - we've used "synthetic" to mean "constructed by our SDK". This is a language-specific
    // meaning, and I'm not sure how to use it in our app. I'm also not /sure/ it matters, though.
    pub method_synthetic: bool,
    #[serde(flatten)]
    pub meta: CommonFrameMetadata,
    #[serde(skip)]
    pub exception_type: Option<String>,
}

impl RawJavaFrame {
    pub fn frame_id(&self) -> String {
        // We don't have version info for java frames, so we rely on
        // the module, function and line number to
        // uniquely identify a frame, with the intuition being that even
        // if two frames are from two different library versions, if the
        // files they're in are sufficiently similar we can consider
        // them to be the same frame
        let mut hasher = Sha512::new();
        if let Some(filename) = &self.filename {
            hasher.update(filename.as_bytes());
        }
        hasher.update(self.function.as_bytes());
        hasher.update(self.lineno.unwrap_or_default().to_be_bytes());
        hasher.update(self.module.as_bytes());
        format!("{:x}", hasher.finalize())
    }

    pub async fn resolve<C>(&self, team_id: i32, catalog: &C) -> Result<Vec<Frame>, UnhandledError>
    where
        C: SymbolCatalog<OrChunkId<ProguardRef>, FetchedMapping>,
    {
        match self.resolve_impl(team_id, catalog).await {
            Ok(frames) => Ok(frames),
            Err(ResolveError::ResolutionError(FrameError::Proguard(e))) => {
                Ok(vec![self.handle_resolution_error(e)])
            }
            Err(ResolveError::ResolutionError(FrameError::MissingChunkIdData(chunk_id))) => Ok(
                vec![self.handle_resolution_error(ProguardError::MissingMap(chunk_id))],
            ),
            Err(ResolveError::ResolutionError(e)) => {
                // TODO - other kinds of errors here should be unreachable, we need to specialize ResolveError to encode that
                unreachable!("Should not have received error {:?}", e)
            }
            Err(ResolveError::UnhandledError(e)) => Err(e),
        }
    }

    async fn resolve_impl<C>(&self, team_id: i32, catalog: &C) -> Result<Vec<Frame>, ResolveError>
    where
        C: SymbolCatalog<OrChunkId<ProguardRef>, FetchedMapping>,
    {
        let r = self.get_ref()?;
        let map: Arc<FetchedMapping> = catalog.lookup(team_id, r.clone()).await?;
        let mapper = map.get_mapper();

        let frame = match self.filename.as_ref() {
            Some(file) => StackFrame::with_file(
                &self.module,
                &self.function,
                self.lineno.unwrap_or_default(),
                file,
            ),
            None => StackFrame::new(
                &self.module,
                &self.function,
                self.lineno.unwrap_or_default(),
            ),
        };

        let mut res: Vec<Frame> = mapper
            .remap_frame(&frame)
            .map(|re| (self, re).into())
            .collect();

        for res in res.iter_mut() {
            res.exception_type = self
                .exception_type
                .as_ref()
                .and_then(|t| mapper.remap_class(t))
                .map(|s| s.to_string());
        }

        if res.is_empty() {
            warn!(
                "Failed to construct any remapped frames from the raw frame {} and chunk id {}",
                self.frame_id(),
                self.get_ref()?
            );
            Ok(vec![(self, ProguardError::NoOriginalFrames).into()])
        } else {
            Ok(res)
        }
    }

    pub fn handle_resolution_error(&self, error: ProguardError) -> Frame {
        (self, error).into()
    }

    pub fn symbol_set_ref(&self) -> Option<String> {
        self.get_ref().ok().map(|r| r.to_string())
    }

    fn get_ref(&self) -> Result<OrChunkId<ProguardRef>, ProguardError> {
        self.map_id
            .as_ref()
            .map(|id| OrChunkId::chunk_id(id.clone()))
            .ok_or(ProguardError::NoMapId)
    }
}

impl<'a> From<(&'a RawJavaFrame, StackFrame<'a>)> for Frame {
    fn from((raw, remapped): (&'a RawJavaFrame, StackFrame<'a>)) -> Self {
        let mut f = Frame {
            frame_id: FrameId::placeholder(),
            mangled_name: raw.function.clone(),
            line: Some(remapped.line() as u32),
            column: None,
            source: remapped.file().map(ToString::to_string),
            in_app: raw.meta.in_app,
            resolved_name: Some(remapped.method().to_string()),
            lang: "java".to_string(),
            resolved: true,
            resolve_failure: None,
            junk_drawer: None,
            code_variables: None,
            release: None,
            synthetic: raw.meta.synthetic,
            context: None,
            suspicious: false,
            module: Some(remapped.class().to_string()),
            exception_type: None,
        };

        add_raw_to_junk(&mut f, raw);

        f
    }
}

impl From<(&RawJavaFrame, ProguardError)> for Frame {
    fn from((raw, error): (&RawJavaFrame, ProguardError)) -> Self {
        let mut f = Frame {
            frame_id: FrameId::placeholder(),
            mangled_name: raw.function.clone(),
            line: raw.lineno.map(|ln| ln as u32),
            column: None,
            source: raw.filename.clone(),
            in_app: raw.meta.in_app,
            resolved_name: None,
            lang: "java".to_string(),
            resolved: false,
            resolve_failure: Some(error.to_string()),
            junk_drawer: None,
            code_variables: None,
            release: None,
            synthetic: raw.meta.synthetic,
            context: None,
            suspicious: false,
            module: Some(raw.module.clone()),
            exception_type: raw.exception_type.clone(),
        };

        add_raw_to_junk(&mut f, raw);

        f
    }
}

#[cfg(test)]
mod test {
    use std::sync::Arc;

    use chrono::Utc;
    use mockall::predicate;
    use posthog_symbol_data::write_symbol_data;
    use sqlx::PgPool;
    use uuid::Uuid;

    use crate::{
        config::Config,
        langs::{java::RawJavaFrame, CommonFrameMetadata},
        symbol_store::{
            chunk_id::ChunkIdFetcher, hermesmap::HermesMapProvider, proguard::ProguardProvider,
            saving::SymbolSetRecord, sourcemap::SourcemapProvider, Catalog, S3Client,
        },
    };

    const PROGUARD_MAP: &str = include_str!("../../tests/static/proguard/composed_example.map");

    async fn test_java_resolution(db: PgPool) {
        let team_id = 1;
        let mut config = Config::init_with_defaults().unwrap();
        config.object_storage_bucket = "test-bucket".to_string();

        let chunk_id = Uuid::now_v7().to_string();

        let mut record = SymbolSetRecord {
            id: Uuid::now_v7(),
            team_id,
            set_ref: chunk_id.clone(),
            storage_ptr: Some(chunk_id.clone()),
            failure_reason: None,
            created_at: Utc::now(),
            content_hash: Some("fake-hash".to_string()),
            last_used: Some(Utc::now()),
        };

        record.save(&db).await.unwrap();

        let mut client = S3Client::default();

        client
            .expect_get()
            .with(
                predicate::eq(config.object_storage_bucket.clone()),
                predicate::eq(chunk_id.clone()), // We set the chunk id as the storage ptr above, in production it will be a different value with a prefix
            )
            .returning(|_, _| Ok(Some(get_symbol_data_bytes())));

        let client = Arc::new(client);

        let hmp = HermesMapProvider {};
        let hmp = ChunkIdFetcher::new(
            hmp,
            client.clone(),
            db.clone(),
            config.object_storage_bucket.clone(),
        );

        let smp = SourcemapProvider::new(&config);
        let smp = ChunkIdFetcher::new(
            smp,
            client.clone(),
            db.clone(),
            config.object_storage_bucket.clone(),
        );

        let pgp = ChunkIdFetcher::new(
            ProguardProvider {},
            client.clone(),
            db.clone(),
            config.object_storage_bucket.clone(),
        );

        let c = Catalog::new(smp, hmp, pgp);

        let frame = RawJavaFrame {
            exception_type: Some("c".to_string()),
            module: "a1.d".to_string(),
            filename: Some("SourceFile".to_string()),
            function: "onClick".to_string(),
            lineno: Some(14),
            map_id: Some("com.posthog.android.sample@3.0+3".to_string()),
            method_synthetic: false,
            meta: CommonFrameMetadata::default(),
        };

        let res = frame.resolve(team_id, &c).await.unwrap().pop().unwrap();
        println!("GOT FRAME: {}", serde_json::to_string_pretty(&res).unwrap());
        assert!(res.resolved);
    }

    fn get_symbol_data_bytes() -> Vec<u8> {
        write_symbol_data(posthog_symbol_data::ProguardMapping {
            content: PROGUARD_MAP.to_string(),
        })
        .unwrap()
    }
}
