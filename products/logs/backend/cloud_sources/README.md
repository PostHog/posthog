# Cloud provider log sources

`aws_firehose_template.yaml` is the CloudFormation template a customer launches from
Settings > Logs > Cloud provider sources.

The app links to it with a CloudFormation quick-create URL, which requires the template to be
readable over HTTPS without credentials. Publish a new revision after editing the file:

```bash
aws s3 cp products/logs/backend/cloud_sources/aws_firehose_template.yaml \
  s3://<public-templates-bucket>/logs/aws_firehose_template.yaml
```

Grant the read through a bucket policy or CloudFront, not `--acl public-read`: object ACLs fail
outright on a bucket with Object Ownership set to `BucketOwnerEnforced`, which is the default for
buckets created since April 2023.

Write access to that bucket means running arbitrary CloudFormation, IAM roles included, in every
customer account that launches a stack afterwards. Keep the bucket versioned, and prefer a
content-addressed key over overwriting in place, so the template a given stack came from stays
knowable.

Then set `LOGS_CLOUD_SOURCES_TEMPLATE_URL` to the object's HTTPS URL in each region's deployment.
When the setting is empty the `setup` action returns no `quick_create_url` and the app shows the
values for a manual Firehose setup instead.
