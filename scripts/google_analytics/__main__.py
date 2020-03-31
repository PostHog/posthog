from datetime import date, datetime
import json
import pickle
import os
import requests

from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
import posthog

from scripts.google_analytics.constants import (
  CREDENTIALS_FILE_PATH,
  END_DATE,
  START_DATE,
  GA_ID,
  METRICS,
  DIMENSIONS,
)

creds = None
SCOPES = ['https://www.googleapis.com/auth/analytics.readonly']

if os.path.exists('./token.pickle'):
    with open('./token.pickle', 'rb') as token:
        creds = pickle.load(token)

# If there are no (valid) credentials available, let the user log in.
if not creds or not creds.valid:
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    else:
        flow = InstalledAppFlow.from_client_secrets_file(
            CREDENTIALS_FILE_PATH,
            SCOPES,
        )
        creds = flow.run_console()

    with open('./token.pickle', 'wb') as token:
        pickle.dump(creds, token)

service = build('analytics', 'v3', credentials=creds)

service.management().accounts().list().execute()

result = service.data().ga().get(
    end_date=END_DATE,
    start_date=START_DATE,
    ids=GA_ID,
    metrics=METRICS,
    dimensions=DIMENSIONS,
).execute()


column_names = [col['name'] for col in result['columnHeaders']]
batch_data   = []

for row in result['rows']:
    row_dictionary = {}

    for index, column in enumerate(column_names):
        row_dictionary[column] = row[index]

    batch_data.append(row_dictionary)

data = {
    "api_key": "PYbSt25buQK4Ksfpd4IBABOZ9vDO5LnKcgdHMyEJq7Y",
    "batch":   batch_data,
}

request = requests.post(
    "http://localhost:8000/capture/",
    data=json.dumps(data),
    headers={'Content-Type': 'application/json'},
)