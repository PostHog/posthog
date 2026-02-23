use crate::{
    error::UnhandledError,
    frames::RawFrame,
    metric_consts::EXCEPTION_RESOLVER_OPERATOR,
    stages::{pipeline::ExceptionEventHandledError, resolution::ResolutionStage},
    types::{
        batch::Batch,
        exception_properties::ExceptionProperties,
        operator::{OperatorResult, ValueOperator},
        Exception, ExceptionList,
    },
};

#[derive(Clone)]
pub struct ExceptionResolver;

impl ExceptionResolver {
    pub fn is_java_exception(exc: &Exception) -> bool {
        let first_frame = exc.stack.as_ref().and_then(|s| s.get_raw_frames().first());
        // Implementation for checking if the exception is a Java exception
        if let Some(RawFrame::Java(_)) = first_frame {
            if exc.module.is_some() {
                return true;
            }
        }
        false
    }

    pub fn is_dart_exception(exc: &Exception) -> bool {
        // Checking if the exception is a Dart exception
        exc.exception_type.starts_with("minified:")
    }
}

impl ValueOperator for ExceptionResolver {
    type Context = ResolutionStage;
    type Item = ExceptionProperties;
    type HandledError = ExceptionEventHandledError;
    type UnhandledError = UnhandledError;

    fn name(&self) -> &'static str {
        EXCEPTION_RESOLVER_OPERATOR
    }

    async fn execute_value(
        &self,
        mut evt: ExceptionProperties,
        ctx: ResolutionStage,
    ) -> OperatorResult<Self> {
        evt.exception_list = Batch::from(evt.exception_list.0)
            .apply_func(
                move |exc, ctx| async move {
                    let ctx = ctx.clone();
                    if ExceptionResolver::is_java_exception(&exc) {
                        ctx.symbol_resolver
                            .resolve_java_exception(evt.team_id, exc)
                            .await
                    } else if ExceptionResolver::is_dart_exception(&exc) {
                        ctx.symbol_resolver
                            .resolve_dart_exception(evt.team_id, exc)
                            .await
                    } else {
                        Ok(exc)
                    }
                },
                ctx,
            )
            .await
            .map(|v| ExceptionList::from(Vec::from(v)))?;

        Ok(Ok(evt))
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
        frames::RawFrame,
        langs::{java::RawJavaFrame, CommonFrameMetadata},
        stages::resolution::symbol::{local::LocalSymbolResolver, SymbolResolver},
        symbol_store::{
            chunk_id::ChunkIdFetcher, hermesmap::HermesMapProvider, proguard::ProguardProvider,
            saving::SymbolSetRecord, sourcemap::SourcemapProvider, Catalog, MockS3Client,
        },
        types::{Exception, Stacktrace},
    };

    const PROGUARD_MAP: &str = include_str!("../../../tests/static/proguard/mapping_example.txt");

    #[sqlx::test(migrations = "./tests/test_migrations")]
    async fn test_proguard_resolution(db: PgPool) {
        let team_id = 1;
        let mut config = Config::init_with_defaults().unwrap();
        config.object_storage_bucket = "test-bucket".to_string();

        let map_id = "com.posthog.android.sample@3.0+3".to_string();

        let mut record = SymbolSetRecord {
            id: Uuid::now_v7(),
            team_id,
            set_ref: map_id.clone(),
            storage_ptr: Some(map_id.clone()),
            failure_reason: None,
            created_at: Utc::now(),
            content_hash: Some("fake-hash".to_string()),
            last_used: Some(Utc::now()),
        };

        record.save(&db).await.unwrap();

        let mut client = MockS3Client::default();

        client
            .expect_get()
            .with(
                predicate::eq(config.object_storage_bucket.clone()),
                predicate::eq(map_id.clone()), // We set the map id as the storage ptr above, in production it will be a different value with a prefix
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
            module: "a1.d".to_string(),
            filename: Some("SourceFile".to_string()),
            function: "onClick".to_string(),
            lineno: Some(14),
            map_id: Some(map_id),
            method_synthetic: false,
            meta: CommonFrameMetadata::default(),
        };

        let resolver = LocalSymbolResolver::new(&config, Arc::new(c), db);
        let exception = Exception {
            exception_type: "c".to_string(),
            module: Some("a1".to_string()),
            exception_message: "Exception message".to_string(),
            exception_id: None,
            mechanism: None,
            thread_id: None,
            stack: Some(Stacktrace::Raw {
                frames: vec![RawFrame::Java(frame)],
            }),
        };

        let result = resolver
            .resolve_java_exception(team_id, exception)
            .await
            .unwrap();

        assert_eq!(
            result.module,
            Some("com.posthog.android.sample".to_string()),
        );

        assert_eq!(result.exception_type, "MyCustomException3".to_string(),);
    }

    fn get_symbol_data_bytes() -> Vec<u8> {
        write_symbol_data(posthog_symbol_data::ProguardMapping {
            content: PROGUARD_MAP.to_string(),
        })
        .unwrap()
    }
}
