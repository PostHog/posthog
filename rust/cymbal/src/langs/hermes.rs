use std::{fmt::Display, sync::Arc};

use common_types::error_tracking::FrameId;
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha512};
use sourcemap::Token;

use crate::{
    error::{FrameError, HermesError, ResolveError, UnhandledError},
    frames::Frame,
    langs::{
        utils::{add_raw_to_junk, get_token_context},
        CommonFrameMetadata,
    },
    sanitize_string,
    symbol_store::{chunk_id::OrChunkId, hermesmap::ParsedHermesMap, SymbolCatalog},
};

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct RawHermesFrame {
    #[serde(rename = "colno")]
    pub column: u32, // Hermes frames don't have a line number
    #[serde(rename = "filename")]
    pub source: String, // This will /usually/ be meaningless
    #[serde(rename = "function")]
    pub fn_name: String, // Mangled function name - sometimes, but not always, the same as the demangled function name
    #[serde(rename = "chunkId", skip_serializing_if = "Option::is_none")]
    pub chunk_id: Option<String>, // Hermes frames are required to provide a chunk ID, or they cannot be resolved
    #[serde(flatten)]
    pub meta: CommonFrameMetadata,
}

// This is an enum it's impossible to construct an instance of. We use it here, along with OrChunkId, to represent that the hermes frames
// will always have a chunk ID - this lets us assert the OrChunkId variant will always be OrChunkId::ChunkId, because the R in this case
// is impossible to construct. Change to a never type once that's stable - https://doc.rust-lang.org/std/primitive.never.html
#[derive(Debug, Clone)]
pub enum HermesRef {}

impl RawHermesFrame {
    pub async fn resolve<C>(&self, team_id: i32, catalog: &C) -> Result<Frame, UnhandledError>
    where
        C: SymbolCatalog<OrChunkId<HermesRef>, ParsedHermesMap>,
    {
        match self.resolve_impl(team_id, catalog).await {
            Ok(frame) => Ok(frame),
            Err(ResolveError::ResolutionError(FrameError::Hermes(e))) => {
                Ok(self.handle_resolution_error(e))
            }
            Err(ResolveError::ResolutionError(FrameError::MissingChunkIdData(chunk_id))) => {
                Ok(self.handle_resolution_error(HermesError::NoSourcemapUploaded(chunk_id)))
            }
            Err(ResolveError::ResolutionError(e)) => {
                // TODO - other kinds of errors here should be unreachable, we need to specialize ResolveError to encode that
                unreachable!("Should not have received error {:?}", e)
            }
            Err(ResolveError::UnhandledError(e)) => Err(e),
        }
    }

    async fn resolve_impl<C>(&self, team_id: i32, catalog: &C) -> Result<Frame, ResolveError>
    where
        C: SymbolCatalog<OrChunkId<HermesRef>, ParsedHermesMap>,
    {
        let r = self.get_ref()?;
        // This type annotation is due to a rust analyzer bug - `cargo check` passes without it, but RA emits an error
        let sourcemap: Arc<ParsedHermesMap> = catalog.lookup(team_id, r.clone()).await?;
        let sourcemap = &sourcemap.map;

        let Some(token) = sourcemap.lookup_token(0, self.column) else {
            return Err(HermesError::NoTokenForColumn(self.column, r.to_string()).into());
        };

        let resolved_name = sourcemap
            .get_original_function_name(self.column)
            .map(|s| s.to_string());

        Ok((self, token, resolved_name).into())
    }

    pub fn frame_id(&self) -> String {
        let mut hasher = Sha512::new();
        hasher.update(self.fn_name.as_bytes());
        hasher.update(self.source.as_bytes());
        hasher.update(self.column.to_string().as_bytes());
        if let Some(chunk_id) = &self.chunk_id {
            hasher.update(chunk_id.as_bytes());
        }
        format!("{:x}", hasher.finalize())
    }

    pub fn symbol_set_ref(&self) -> Option<String> {
        self.get_ref().ok().map(|r| r.to_string())
    }

    fn get_ref(&self) -> Result<OrChunkId<HermesRef>, HermesError> {
        self.chunk_id
            .as_ref()
            .map(|id| OrChunkId::chunk_id(id.clone()))
            .ok_or(HermesError::NoChunkId)
    }

    fn handle_resolution_error(&self, err: HermesError) -> Frame {
        (self, err).into()
    }
}

impl Display for HermesRef {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "HermesRef")
    }
}

impl From<(&RawHermesFrame, HermesError)> for Frame {
    fn from((frame, err): (&RawHermesFrame, HermesError)) -> Self {
        let mut res = Self {
            frame_id: FrameId::placeholder(),
            mangled_name: frame.fn_name.clone(),
            line: Some(1), // Hermes frames are 1-indexed and always 1
            column: Some(frame.column),
            source: Some(frame.source.clone()),
            in_app: frame.meta.in_app,
            resolved_name: None,
            lang: "hermes-js".to_string(),
            resolved: false,
            resolve_failure: Some(err.to_string()),
            synthetic: frame.meta.synthetic,
            junk_drawer: None,
            code_variables: None,
            context: None,
            release: None,
            suspicious: false,
            module: None,
        };

        add_raw_to_junk(&mut res, frame);

        res
    }
}

impl From<(&RawHermesFrame, Token<'_>, Option<String>)> for Frame {
    fn from((frame, token, resolved_name): (&RawHermesFrame, Token<'_>, Option<String>)) -> Self {
        let source = token.get_source().map(|s| sanitize_string(s.to_string()));
        let in_app = source
            .as_ref()
            .map(|s| !s.contains("node_modules"))
            .unwrap_or(frame.meta.in_app);

        let mut res = Self {
            frame_id: FrameId::placeholder(),
            mangled_name: frame.fn_name.clone(),
            line: Some(token.get_src_line()),
            column: Some(token.get_src_col()),
            source,
            in_app,
            resolved_name,
            lang: "hermes-js".to_string(),
            resolved: true,
            resolve_failure: None,
            synthetic: frame.meta.synthetic,
            junk_drawer: None,
            code_variables: None,
            context: get_token_context(&token, token.get_src_line() as usize),
            release: None,
            suspicious: false,
            module: None,
        };

        add_raw_to_junk(&mut res, frame);

        res
    }
}

#[cfg(test)]
mod test {
    use std::sync::Arc;

    use chrono::Utc;
    use mockall::predicate;
    use posthog_symbol_data::write_symbol_data;
    use regex::Regex;
    use sqlx::PgPool;
    use uuid::Uuid;

    use crate::{
        config::Config,
        frames::RawFrame,
        langs::{hermes::RawHermesFrame, CommonFrameMetadata},
        symbol_store::{
            chunk_id::ChunkIdFetcher, hermesmap::HermesMapProvider, proguard::ProguardProvider,
            saving::SymbolSetRecord, sourcemap::SourcemapProvider, Catalog, S3Client,
        },
    };

    const HERMES_MAP: &str = include_str!("../../tests/static/hermes/composed_example.map");
    const RAW_STACK: &str = include_str!("../../tests/static/hermes/raw_stack.txt");

    #[sqlx::test(migrations = "./tests/test_migrations")]
    async fn test_hermes_resolution(db: PgPool) {
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

        for (raw_frame, expected_name) in get_frames(chunk_id) {
            let res = raw_frame.resolve(team_id, &c).await.unwrap().pop().unwrap();
            println!("GOT FRAME: {}", serde_json::to_string_pretty(&res).unwrap());
            assert!(res.resolved);
            assert_eq!(res.resolved_name, expected_name)
        }
    }

    fn get_frames(chunk_id: String) -> Vec<(RawFrame, Option<String>)> {
        let frame_regex = Regex::new(r"at\s+(\S+)\s+\(address at\s+[^:]+:(\d+):(\d+)\)").unwrap();
        let mut frames = Vec::new();

        let expected_names = [
            Some("c"),
            Some("b"),
            Some("a"),
            Some("loadModuleImplementation"),
            Some("guardedLoadModule"),
            Some("metroRequire"),
            None,
        ];

        for (captures, expected) in frame_regex
            .captures_iter(RAW_STACK)
            .zip(expected_names.iter())
        {
            let name = &captures[1];
            let _line: u32 = captures[2].parse().unwrap();
            let col: u32 = captures[3].parse().unwrap();

            let frame = RawHermesFrame {
                column: col,
                source: String::new(),
                fn_name: name.to_string(),
                chunk_id: Some(chunk_id.clone()),
                meta: CommonFrameMetadata::default(),
            };

            frames.push((RawFrame::Hermes(frame), expected.map(String::from)));
        }

        frames
    }

    fn get_symbol_data_bytes() -> Vec<u8> {
        write_symbol_data(posthog_symbol_data::HermesMap {
            sourcemap: HERMES_MAP.to_string(),
        })
        .unwrap()
    }
}
