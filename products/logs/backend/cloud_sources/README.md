# Cloud provider log sources

`aws_firehose_template.yaml` is the CloudFormation template a customer launches from Settings > Logs > Cloud provider sources.
It creates a Firehose stream pointed at PostHog's HTTP endpoint, the two IAM roles, an S3 bucket for failed deliveries, and one subscription filter.

The app links to it with a CloudFormation quick-create URL, which requires the template to be reachable as a public S3 object.
Publish a new revision after editing the file:

```bash
aws s3 cp products/logs/backend/cloud_sources/aws_firehose_template.yaml \
  s3://<public-templates-bucket>/logs/aws_firehose_template.yaml --acl public-read
```

Then set `LOGS_CLOUD_SOURCES_TEMPLATE_URL` to the object's HTTPS URL in each region's deployment.
When the setting is empty the `setup` action returns no `quick_create_url` and the app shows the values for a manual Firehose setup instead.

The backup bucket is retained when the customer deletes the stack, because CloudFormation cannot delete a bucket that still holds failed deliveries.
The quick-create link is only offered for commercial, GovCloud and China regions; isolated regions have no public console.
