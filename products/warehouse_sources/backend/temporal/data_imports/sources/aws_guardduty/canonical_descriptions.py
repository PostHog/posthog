from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "findings": {
        "description": "Security findings detected by GuardDuty in the selected region.",
        "docs_url": "https://docs.aws.amazon.com/guardduty/latest/APIReference/API_Finding.html",
        "columns": {
            "arn": "Amazon Resource Name that uniquely identifies the finding.",
            "id": "Identifier assigned to the finding by GuardDuty.",
            "account_id": "AWS account where GuardDuty detected the finding.",
            "region": "AWS region where GuardDuty detected the finding.",
            "source_detector_id": "Detector used to retrieve this finding.",
            "created_at": "Time when GuardDuty created the finding.",
            "updated_at": "Time when GuardDuty last updated the finding.",
            "severity": "Severity assigned to the finding.",
            "type": "Type of threat reported by the finding.",
            "title": "Short summary of the finding.",
            "description": "Description of the finding.",
            "resource": "AWS resource associated with the finding.",
            "service": "Detection details, including the action and archive status.",
        },
    },
    "detectors": {
        "description": "GuardDuty detector configuration in the selected region.",
        "docs_url": "https://docs.aws.amazon.com/guardduty/latest/APIReference/API_GetDetector.html",
        "columns": {
            "source_detector_id": "Identifier of the detector whose configuration was retrieved.",
            "region": "AWS region that contains the detector.",
            "status": "Status of the GuardDuty detector.",
            "created_at": "Time when the detector was created.",
            "updated_at": "Time when the detector configuration was last updated.",
            "features": "Protection features and their status for this detector.",
            "data_sources": "Data sources configured for this detector.",
            "finding_publishing_frequency": "Frequency at which GuardDuty publishes updated findings.",
            "service_role": "IAM role that gives GuardDuty access to AWS resources.",
            "tags": "Tags attached to the detector.",
        },
    },
    "members": {
        "description": "Accounts managed by the GuardDuty administrator, including accounts that are no longer associated.",
        "docs_url": "https://docs.aws.amazon.com/guardduty/latest/APIReference/API_ListMembers.html",
        "columns": {
            "source_detector_id": "Administrator detector used to list this member.",
            "region": "AWS region where the member relationship is configured.",
            "account_id": "AWS account ID of the member.",
            "administrator_id": "AWS account ID of the GuardDuty administrator.",
            "detector_id": "Identifier of the member account's detector.",
            "email": "Email address associated with an invited member account.",
            "invited_at": "Time when the administrator invited the member account.",
            "updated_at": "Time when the member relationship was last updated.",
            "relationship_status": "Status of the relationship between the member and administrator accounts.",
        },
    },
}
