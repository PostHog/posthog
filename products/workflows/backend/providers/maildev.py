MAILDEV_MOCK_DNS_RECORDS = [
    # Mock DNS records for email domain setup when using local maildev
    {
        "type": "verification",
        "recordType": "TXT",
        "recordHostname": "_amazonses.example.com",
        "recordValue": "mock-verification-token",
        "status": "success",
    },
    {
        "type": "dkim",
        "recordType": "CNAME",
        "recordHostname": "mock1._domainkey.example.com",
        "recordValue": "mock1.dkim.amazonses.com",
        "status": "success",
    },
    {
        "type": "dkim",
        "recordType": "CNAME",
        "recordHostname": "mock2._domainkey.example.com",
        "recordValue": "mock2.dkim.amazonses.com",
        "status": "success",
    },
    {
        "type": "dkim",
        "recordType": "CNAME",
        "recordHostname": "mock3._domainkey.example.com",
        "recordValue": "mock3.dkim.amazonses.com",
        "status": "success",
    },
    {
        "type": "verification",
        "recordType": "TXT",
        "recordHostname": "@",
        "recordValue": "v=spf1 include:amazonses.com ~all",
        "status": "success",
    },
    {
        "type": "mail_from",
        "recordType": "MX",
        "recordHostname": "mail.example.com",
        "recordValue": "feedback-smtp.us-east-1.amazonses.com",
        "priority": 10,
        "status": "success",
    },
    {
        "type": "mail_from",
        "recordType": "TXT",
        "recordHostname": "mail.example.com",
        "recordValue": "v=spf1 include:amazonses.com ~all",
        "status": "success",
    },
]
