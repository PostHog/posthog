#!/usr/bin/env python3
# ruff: noqa: T201
"""
Standalone script to test Firebase Cloud Messaging push notifications.
Use this to validate your Firebase setup before testing through PostHog.

Usage:
    python test_fcm_push.py <service-account.json> <fcm-token>

Example:
    python test_fcm_push.py ~/Downloads/firebase-service-account.json "dGVzdC10b2tlbi1oZXJl..."
"""

import sys
import json
import time
from pathlib import Path

import jwt
import requests


def get_access_token(service_account: dict) -> str:
    """Generate a short-lived access token from service account credentials."""
    now = int(time.time())

    payload = {
        "iss": service_account["client_email"],
        "sub": service_account["client_email"],
        "aud": "https://oauth2.googleapis.com/token",
        "iat": now,
        "exp": now + 3600,
        "scope": "https://www.googleapis.com/auth/firebase.messaging",
    }

    signed_jwt = jwt.encode(
        payload,
        service_account["private_key"],
        algorithm="RS256",
    )

    response = requests.post(
        "https://oauth2.googleapis.com/token",
        data={
            "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
            "assertion": signed_jwt,
        },
    )

    if response.status_code != 200:
        print(f"❌ Failed to get access token: {response.status_code}")
        print(response.text)
        sys.exit(1)

    return response.json()["access_token"]


def send_push(project_id: str, access_token: str, fcm_token: str, title: str, body: str) -> dict:
    """Send a push notification via FCM v1 API."""
    url = f"https://fcm.googleapis.com/v1/projects/{project_id}/messages:send"

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }

    payload = {
        "message": {
            "token": fcm_token,
            "notification": {
                "title": title,
                "body": body,
            },
            "data": {
                "source": "posthog_test_script",
                "timestamp": str(int(time.time())),
            },
        }
    }

    response = requests.post(url, headers=headers, json=payload)
    return {
        "status_code": response.status_code,
        "response": response.json() if response.text else {},
    }


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)

    service_account_path = Path(sys.argv[1])
    fcm_token = sys.argv[2]

    if not service_account_path.exists():
        print(f"❌ Service account file not found: {service_account_path}")
        sys.exit(1)

    print(f"📄 Loading service account from: {service_account_path}")
    with open(service_account_path) as f:
        service_account = json.load(f)

    project_id = service_account.get("project_id")
    if not project_id:
        print("❌ No project_id found in service account JSON")
        sys.exit(1)

    print(f"🔑 Project ID: {project_id}")
    print(f"📧 Service account: {service_account.get('client_email')}")

    print("\n🔐 Getting access token...")
    access_token = get_access_token(service_account)
    print(f"✅ Got access token (first 20 chars): {access_token[:20]}...")

    print(f"\n📱 Sending push to token: {fcm_token[:20]}...")
    result = send_push(
        project_id=project_id,
        access_token=access_token,
        fcm_token=fcm_token,
        title="PostHog Test",
        body="If you see this, FCM is working! 🎉",
    )

    if result["status_code"] == 200:
        print(f"✅ Push sent successfully!")
        print(f"   Message ID: {result['response'].get('name', 'N/A')}")
    else:
        print(f"❌ Push failed with status {result['status_code']}")
        print(f"   Response: {json.dumps(result['response'], indent=2)}")

        error_code = result["response"].get("error", {}).get("details", [{}])[0].get("errorCode", "")
        if error_code == "UNREGISTERED":
            print("\n💡 Hint: The FCM token is invalid or expired. Get a fresh token from your app.")
        elif result["status_code"] == 401:
            print("\n💡 Hint: Check that Cloud Messaging API is enabled in your Firebase project.")
        elif result["status_code"] == 404:
            print("\n💡 Hint: The project ID may be incorrect or Firebase isn't set up.")


if __name__ == "__main__":
    main()
