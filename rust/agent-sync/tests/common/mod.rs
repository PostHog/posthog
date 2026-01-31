use async_trait::async_trait;
use axum::body::Body;
use axum::http::{header, Request, Response};
use axum::Router;
use chrono::Utc;
use parking_lot::Mutex;
use serde_json::json;
use sqlx::postgres::PgPoolOptions;
use std::sync::Arc;
use std::time::Duration;
use tower::ServiceExt;
use uuid::Uuid;

use agent_sync::app::{create_router, AppState};
use agent_sync::auth::AuthService;
use agent_sync::error::AppError;
use agent_sync::kafka::EventPublisher;
use agent_sync::store::LogStore;
use agent_sync::streaming::FanoutRouter;
use agent_sync::types::{AgentEvent, AuthContext};

#[derive(Clone)]
pub struct MockAuthService {
    pub context: AuthContext,
    pub should_authorize: bool,
}

impl MockAuthService {
    pub fn new(user_id: i32, team_id: Option<i32>) -> Arc<Self> {
        Arc::new(Self {
            context: AuthContext { user_id, team_id },
            should_authorize: true,
        })
    }

    pub fn unauthorized() -> Arc<Self> {
        Arc::new(Self {
            context: AuthContext {
                user_id: 1,
                team_id: Some(1),
            },
            should_authorize: false,
        })
    }
}

#[async_trait]
impl AuthService for MockAuthService {
    async fn authenticate(&self, token: &str) -> Result<AuthContext, AppError> {
        if token.starts_with("pha_") {
            Ok(self.context.clone())
        } else {
            Err(AppError::InvalidToken)
        }
    }

    async fn authorize_run(
        &self,
        _user_id: i32,
        _project_id: i64,
        _task_id: &Uuid,
        _run_id: &Uuid,
    ) -> Result<(), AppError> {
        if self.should_authorize {
            Ok(())
        } else {
            Err(AppError::Forbidden("Access denied".to_string()))
        }
    }
}

pub struct MockLogStore {
    events: Mutex<Vec<AgentEvent>>,
}

impl MockLogStore {
    pub fn new() -> Arc<Self> {
        Arc::new(Self {
            events: Mutex::new(Vec::new()),
        })
    }

    pub fn with_events(events: Vec<AgentEvent>) -> Arc<Self> {
        Arc::new(Self {
            events: Mutex::new(events),
        })
    }
}

#[async_trait]
impl LogStore for MockLogStore {
    async fn get_logs(
        &self,
        run_id: &Uuid,
        after: Option<u64>,
        limit: Option<u32>,
    ) -> Result<Vec<AgentEvent>, AppError> {
        let events = self.events.lock();
        let after_seq = after.unwrap_or(0);
        let limit = limit.unwrap_or(10000) as usize;

        let filtered: Vec<AgentEvent> = events
            .iter()
            .filter(|e| e.run_id == *run_id && e.sequence > after_seq)
            .take(limit)
            .cloned()
            .collect();

        Ok(filtered)
    }

    async fn health_check(&self) -> Result<(), AppError> {
        Ok(())
    }
}

pub struct MockEventPublisher {
    published: Mutex<Vec<AgentEvent>>,
}

impl MockEventPublisher {
    pub fn new() -> Arc<Self> {
        Arc::new(Self {
            published: Mutex::new(Vec::new()),
        })
    }

    pub fn get_published(&self) -> Vec<AgentEvent> {
        self.published.lock().clone()
    }
}

#[async_trait]
impl EventPublisher for MockEventPublisher {
    async fn publish(&self, event: &AgentEvent) -> Result<(), AppError> {
        self.published.lock().push(event.clone());
        Ok(())
    }
}

pub struct TestHarness {
    pub auth: Arc<MockAuthService>,
    pub log_store: Arc<MockLogStore>,
    pub publisher: Arc<MockEventPublisher>,
    pub router: Arc<FanoutRouter>,
    app: Router,
}

impl TestHarness {
    pub async fn new() -> Self {
        Self::builder().build().await
    }

    pub fn builder() -> TestHarnessBuilder {
        TestHarnessBuilder::default()
    }

    pub async fn get(&self, uri: &str) -> Response<Body> {
        self.app
            .clone()
            .oneshot(
                Request::builder()
                    .uri(uri)
                    .header(header::AUTHORIZATION, "Bearer pha_test_token")
                    .body(Body::empty())
                    .unwrap(),
            )
            .await
            .unwrap()
    }

    pub async fn get_without_auth(&self, uri: &str) -> Response<Body> {
        self.app
            .clone()
            .oneshot(Request::builder().uri(uri).body(Body::empty()).unwrap())
            .await
            .unwrap()
    }

    pub async fn post(&self, uri: &str, body: serde_json::Value) -> Response<Body> {
        self.app
            .clone()
            .oneshot(
                Request::builder()
                    .method("POST")
                    .uri(uri)
                    .header(header::AUTHORIZATION, "Bearer pha_test_token")
                    .header(header::CONTENT_TYPE, "application/json")
                    .body(Body::from(serde_json::to_string(&body).unwrap()))
                    .unwrap(),
            )
            .await
            .unwrap()
    }

    pub async fn body_json<T: serde::de::DeserializeOwned>(response: Response<Body>) -> T {
        let body = axum::body::to_bytes(response.into_body(), usize::MAX)
            .await
            .unwrap();
        serde_json::from_slice(&body).unwrap()
    }

    pub fn published_events(&self) -> Vec<AgentEvent> {
        self.publisher.get_published()
    }

    pub async fn get_with_header(
        &self,
        uri: &str,
        header_name: &str,
        header_value: &str,
    ) -> Response<Body> {
        self.app
            .clone()
            .oneshot(
                Request::builder()
                    .uri(uri)
                    .header(header::AUTHORIZATION, "Bearer pha_test_token")
                    .header(header_name, header_value)
                    .body(Body::empty())
                    .unwrap(),
            )
            .await
            .unwrap()
    }

}

#[derive(Default)]
pub struct TestHarnessBuilder {
    events: Vec<AgentEvent>,
    unauthorized: bool,
    user_id: Option<i32>,
    team_id: Option<Option<i32>>,
}

impl TestHarnessBuilder {
    pub fn with_events(mut self, events: Vec<AgentEvent>) -> Self {
        self.events = events;
        self
    }

    pub fn unauthorized(mut self) -> Self {
        self.unauthorized = true;
        self
    }

    pub fn with_user(mut self, user_id: i32) -> Self {
        self.user_id = Some(user_id);
        self
    }

    pub fn with_team(mut self, team_id: Option<i32>) -> Self {
        self.team_id = Some(team_id);
        self
    }

    pub async fn build(self) -> TestHarness {
        let auth = if self.unauthorized {
            MockAuthService::unauthorized()
        } else {
            let user_id = self.user_id.unwrap_or(1);
            let team_id = self.team_id.unwrap_or(Some(1));
            MockAuthService::new(user_id, team_id)
        };

        let log_store = if self.events.is_empty() {
            MockLogStore::new()
        } else {
            MockLogStore::with_events(self.events)
        };

        let publisher = MockEventPublisher::new();

        let database_url = std::env::var("DATABASE_URL")
            .unwrap_or_else(|_| "postgres://posthog:posthog@localhost:5432/posthog".to_string());

        let pg_pool = PgPoolOptions::new()
            .max_connections(1)
            .acquire_timeout(Duration::from_secs(2))
            .connect(&database_url)
            .await
            .expect("Failed to create test pool - is Postgres running?");

        let router = FanoutRouter::new();

        let state = AppState {
            auth: auth.clone(),
            log_store: log_store.clone(),
            publisher: publisher.clone(),
            router: router.clone(),
            pg_pool,
            max_logs_limit: 1000,
            sse_keepalive_secs: 30,
        };

        let app = create_router(state);

        TestHarness {
            auth,
            log_store,
            publisher,
            router,
            app,
        }
    }
}

pub struct AgentEventBuilder {
    team_id: i64,
    task_id: Uuid,
    run_id: Uuid,
    sequence: u64,
    entry_type: String,
    entry: serde_json::Value,
}

impl Default for AgentEventBuilder {
    fn default() -> Self {
        Self {
            team_id: 1,
            task_id: Uuid::new_v4(),
            run_id: Uuid::new_v4(),
            sequence: 1,
            entry_type: "test".to_string(),
            entry: json!({"test": true}),
        }
    }
}

impl AgentEventBuilder {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn team_id(mut self, team_id: i64) -> Self {
        self.team_id = team_id;
        self
    }

    pub fn task_id(mut self, task_id: Uuid) -> Self {
        self.task_id = task_id;
        self
    }

    pub fn run_id(mut self, run_id: Uuid) -> Self {
        self.run_id = run_id;
        self
    }

    pub fn sequence(mut self, sequence: u64) -> Self {
        self.sequence = sequence;
        self
    }

    pub fn entry_type(mut self, entry_type: &str) -> Self {
        self.entry_type = entry_type.to_string();
        self
    }

    pub fn entry(mut self, entry: serde_json::Value) -> Self {
        self.entry = entry;
        self
    }

    pub fn build(self) -> AgentEvent {
        AgentEvent {
            team_id: self.team_id,
            task_id: self.task_id,
            run_id: self.run_id,
            sequence: self.sequence,
            timestamp: Utc::now(),
            entry_type: self.entry_type,
            entry: self.entry,
        }
    }
}

pub fn test_event() -> AgentEventBuilder {
    AgentEventBuilder::new()
}
