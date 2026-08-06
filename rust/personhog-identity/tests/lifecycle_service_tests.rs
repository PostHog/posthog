use tonic::{Code, Request};

use personhog_identity::lifecycle::validation::MAX_DELETE_BATCH_SIZE;
use personhog_identity::lifecycle::PersonHogLifecycleService;
use personhog_proto::personhog::lifecycle::v1::person_hog_lifecycle_server::PersonHogLifecycle;
use personhog_proto::personhog::lifecycle::v1::DeletePersonsRequest;

fn valid_request() -> DeletePersonsRequest {
    DeletePersonsRequest {
        team_id: 1,
        person_ids: vec![42],
        op_id: "018f6f60-8c5a-7000-8000-000000000000".to_string(),
    }
}

async fn delete_status(request: DeletePersonsRequest) -> Code {
    let service = PersonHogLifecycleService::new();
    service
        .delete_persons(Request::new(request))
        .await
        .expect_err("skeleton service never returns Ok")
        .code()
}

#[tokio::test]
async fn invalid_requests_are_rejected_before_the_saga() {
    let cases: Vec<(&str, DeletePersonsRequest)> = vec![
        (
            "zero team_id",
            DeletePersonsRequest {
                team_id: 0,
                ..valid_request()
            },
        ),
        (
            "team_id above i32 wraps in int4 storage",
            DeletePersonsRequest {
                team_id: i64::from(i32::MAX) + 1,
                ..valid_request()
            },
        ),
        (
            "empty person_ids",
            DeletePersonsRequest {
                person_ids: vec![],
                ..valid_request()
            },
        ),
        (
            "batch above cap",
            DeletePersonsRequest {
                person_ids: (1..=(MAX_DELETE_BATCH_SIZE as i64 + 1)).collect(),
                ..valid_request()
            },
        ),
        (
            "non-positive person id",
            DeletePersonsRequest {
                person_ids: vec![42, 0],
                ..valid_request()
            },
        ),
        (
            "op_id not a uuid",
            DeletePersonsRequest {
                op_id: "not-a-uuid".to_string(),
                ..valid_request()
            },
        ),
    ];

    for (name, request) in cases {
        assert_eq!(
            delete_status(request).await,
            Code::InvalidArgument,
            "case: {name}"
        );
    }
}

#[tokio::test]
async fn valid_request_reports_unimplemented_until_the_engine_lands() {
    assert_eq!(delete_status(valid_request()).await, Code::Unimplemented);
}
