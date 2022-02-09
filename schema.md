---
title: PostHog API vnull
language_tabs:
  - shell: Shell
  - http: HTTP
  - javascript: JavaScript
  - ruby: Ruby
  - python: Python
  - php: PHP
  - java: Java
  - go: Go
toc_footers: []
includes: []
search: true
highlight_theme: darkula
headingLevel: 2

---

<!-- Generator: Widdershins v4.0.1 -->

<h1 id="">PostHog API vnull</h1>

> Scroll down for code samples, example requests and responses. Select a language for code samples from the tabs above or the mobile navigation menu.

This section of our Docs explains how to pull or push data from/to our API. PostHog has an API available on all tiers of PostHog cloud pricing, including the free tier, and for every self-hosted version.

Please note that PostHog makes use of two different APIs, serving different purposes and using different mechanisms for authentication.

One API is used for pushing data into PostHog. This uses the 'Team API Key' that is included in the [frontend snippet](/docs/integrate/client/js). This API Key is **public**, and is what we use in our frontend integration to push events into PostHog, as well as to check for feature flags, for instance.

The other API is more powerful and allows you to perform any action as if you were an authenticated user utilizing the PostHog UI. It is mostly used for getting data out of PostHog, as well as other private actions such as creating a feature flag. This uses a 'Personal API Key' which you need to create manually (instructions [below](#authentication)). This API Key is **private** and you should not make it public nor share it with anyone. It gives you access to all the data held by your PostHog instance, which includes sensitive information.

These API Docs refer mostly to the **private API**, performing authentication as outlined below. The only exception is the [POST-only public endpoints](/docs/api/post-only-endpoints) section. This section explicitly informs you on how to perform authentication. For endpoints in all other sections, authentication is done as described below.

## Authentication

Personal API keys allow full access to your account, just like e-mail address and password, but you can create any number of them and each one can invalidated individually at any moment. This makes for greater control for you and improved security of stored data.

### How to obtain a personal API key

1. Click on your name/avatar on the top right.
1. Click on 'My account'
1. Navigate to the 'Personal API Keys' section.
1. Click "+ Create a Personal API Key".
1. Give your new key a label – it's just for you, usually to describe the key's purpose.
1. Click 'Create Key'.
1. There you go! At the top of the list you should now be seeing your brand new key. **Immediately** copy its value, as you'll **never** see it again after refreshing the page. But don't worry if you forget to copy it – you can delete and create keys as much as you want.

### How to use a personal API key

There are three options:

1. Use the `Authorization` header and `Bearer` authentication, like so:
    ```JavaScript
    const headers = {
        Authorization: `Bearer ${POSTHOG_PERSONAL_API_KEY}`
    }
    ```
2. Put the key in request body, like so:
    ```JavaScript
    const body = {
        personal_api_key: POSTHOG_PERSONAL_API_KEY
    }
    ```
3. Put the key in query string, like so:
    ```JavaScript
    const url = `https://posthog.example.com/api/event/?personal_api_key=${POSTHOG_PERSONAL_API_KEY}`
    ```

Any one of these methods works, but only the value encountered first (in the order above) will be used for authenticaition!

For PostHog Cloud, use `app.posthog.com` as the host address.

#### Specifying a project when using the API

By default, if you're accessing the API, PostHog will return results from the last project you visited in the UI. To override this behavior, you can pass in your Project API Key (public token) as a query parameter in the request. This ensures you will get data from the project associated with that token.

**Example**

```
api/event/?token=my_project_api_key
```

### cURL example for self-hosted PostHog

```bash
POSTHOG_PERSONAL_API_KEY=qTjsppKJqYLr2YskbsLXmu46eW1oH0r3jZkmKaERlf0

curl --header "Authorization: Bearer $POSTHOG_PERSONAL_API_KEY" https://posthog.example.com/api/person/
```

### cURL example for PostHog Cloud

```bash
POSTHOG_PERSONAL_API_KEY=qTjsppKJqYLr2YskbsLXmu46eW1oH0r3jZkmKaERlf0
curl --header "Authorization: Bearer $POSTHOG_PERSONAL_API_KEY" https://app.posthog.com/api/person/
```

## Tips

- The [`/users/@me/` endpoint](/docs/api/user) gives you useful information about the current user.
- The `/api/event_definition/` and `/api/property_definition` endpoints provide the possible event names and properties you can use throughout the rest of the API.
- The maximum size of a POST request body is governed by `settings.DATA_UPLOAD_MAX_MEMORY_SIZE`, and is 20MB by default.

## Pagination

Sometimes requests are paginated. If that's the case, it'll be in the following format:

```json
{
    "next": "https://posthog.example.com/api/person/?cursor=cD0yMjgxOTA2",
    "previous": null,
    "results": [
        ...
    ]
}
```

You can then just call the `"next"` URL to get the next set of results.

            

<h1 id="-organizations">organizations</h1>

## invites_list

<a id="opIdinvites_list"></a>

> Code samples

```shell
# You can also use wget
curl -X GET /api/organizations/{parent_lookup_organization_id}/invites/ \
  -H 'Accept: application/json'

```

```http
GET /api/organizations/{parent_lookup_organization_id}/invites/ HTTP/1.1

Accept: application/json

```

```javascript

const headers = {
  'Accept':'application/json'
};

fetch('/api/organizations/{parent_lookup_organization_id}/invites/',
{
  method: 'GET',

  headers: headers
})
.then(function(res) {
    return res.json();
}).then(function(body) {
    console.log(body);
});

```

```ruby
require 'rest-client'
require 'json'

headers = {
  'Accept' => 'application/json'
}

result = RestClient.get '/api/organizations/{parent_lookup_organization_id}/invites/',
  params: {
  }, headers: headers

p JSON.parse(result)

```

```python
import requests
headers = {
  'Accept': 'application/json'
}

r = requests.get('/api/organizations/{parent_lookup_organization_id}/invites/', headers = headers)

print(r.json())

```

```php
<?php

require 'vendor/autoload.php';

$headers = array(
    'Accept' => 'application/json',
);

$client = new \GuzzleHttp\Client();

// Define array of request body.
$request_body = array();

try {
    $response = $client->request('GET','/api/organizations/{parent_lookup_organization_id}/invites/', array(
        'headers' => $headers,
        'json' => $request_body,
       )
    );
    print_r($response->getBody()->getContents());
 }
 catch (\GuzzleHttp\Exception\BadResponseException $e) {
    // handle exception or api errors.
    print_r($e->getMessage());
 }

 // ...

```

```java
URL obj = new URL("/api/organizations/{parent_lookup_organization_id}/invites/");
HttpURLConnection con = (HttpURLConnection) obj.openConnection();
con.setRequestMethod("GET");
int responseCode = con.getResponseCode();
BufferedReader in = new BufferedReader(
    new InputStreamReader(con.getInputStream()));
String inputLine;
StringBuffer response = new StringBuffer();
while ((inputLine = in.readLine()) != null) {
    response.append(inputLine);
}
in.close();
System.out.println(response.toString());

```

```go
package main

import (
       "bytes"
       "net/http"
)

func main() {

    headers := map[string][]string{
        "Accept": []string{"application/json"},
    }

    data := bytes.NewBuffer([]byte{jsonReq})
    req, err := http.NewRequest("GET", "/api/organizations/{parent_lookup_organization_id}/invites/", data)
    req.Header = headers

    client := &http.Client{}
    resp, err := client.Do(req)
    // ...
}

```

`GET /api/organizations/{parent_lookup_organization_id}/invites/`

<h3 id="invites_list-parameters">Parameters</h3>

|Name|In|Type|Required|Description|
|---|---|---|---|---|
|limit|query|integer|false|Number of results to return per page.|
|offset|query|integer|false|The initial index from which to return the results.|
|parent_lookup_organization_id|path|string|true|none|

> Example responses

> 200 Response

```json
{
  "count": 123,
  "next": "http://api.example.org/accounts/?offset=400&limit=100",
  "previous": "http://api.example.org/accounts/?offset=200&limit=100",
  "results": [
    {
      "id": "497f6eca-6276-4993-bfeb-53cbbbba6f08",
      "target_email": "user@example.com",
      "first_name": "string",
      "emailing_attempt_made": true,
      "is_expired": true,
      "created_by": {
        "id": 0,
        "uuid": "095be615-a8ad-4c33-8e9c-c7612fbf6c9f",
        "distinct_id": "string",
        "first_name": "string",
        "email": "user@example.com"
      },
      "created_at": "2019-08-24T14:15:22Z",
      "updated_at": "2019-08-24T14:15:22Z"
    }
  ]
}
```

<h3 id="invites_list-responses">Responses</h3>

|Status|Meaning|Description|Schema|
|---|---|---|---|
|200|[OK](https://tools.ietf.org/html/rfc7231#section-6.3.1)|none|[PaginatedOrganizationInviteList](#schemapaginatedorganizationinvitelist)|

<aside class="success">
This operation does not require authentication
</aside>

## invites_create

<a id="opIdinvites_create"></a>

> Code samples

```shell
# You can also use wget
curl -X POST /api/organizations/{parent_lookup_organization_id}/invites/ \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json'

```

```http
POST /api/organizations/{parent_lookup_organization_id}/invites/ HTTP/1.1

Content-Type: application/json
Accept: application/json

```

```javascript
const inputBody = '{
  "target_email": "user@example.com",
  "first_name": "string"
}';
const headers = {
  'Content-Type':'application/json',
  'Accept':'application/json'
};

fetch('/api/organizations/{parent_lookup_organization_id}/invites/',
{
  method: 'POST',
  body: inputBody,
  headers: headers
})
.then(function(res) {
    return res.json();
}).then(function(body) {
    console.log(body);
});

```

```ruby
require 'rest-client'
require 'json'

headers = {
  'Content-Type' => 'application/json',
  'Accept' => 'application/json'
}

result = RestClient.post '/api/organizations/{parent_lookup_organization_id}/invites/',
  params: {
  }, headers: headers

p JSON.parse(result)

```

```python
import requests
headers = {
  'Content-Type': 'application/json',
  'Accept': 'application/json'
}

r = requests.post('/api/organizations/{parent_lookup_organization_id}/invites/', headers = headers)

print(r.json())

```

```php
<?php

require 'vendor/autoload.php';

$headers = array(
    'Content-Type' => 'application/json',
    'Accept' => 'application/json',
);

$client = new \GuzzleHttp\Client();

// Define array of request body.
$request_body = array();

try {
    $response = $client->request('POST','/api/organizations/{parent_lookup_organization_id}/invites/', array(
        'headers' => $headers,
        'json' => $request_body,
       )
    );
    print_r($response->getBody()->getContents());
 }
 catch (\GuzzleHttp\Exception\BadResponseException $e) {
    // handle exception or api errors.
    print_r($e->getMessage());
 }

 // ...

```

```java
URL obj = new URL("/api/organizations/{parent_lookup_organization_id}/invites/");
HttpURLConnection con = (HttpURLConnection) obj.openConnection();
con.setRequestMethod("POST");
int responseCode = con.getResponseCode();
BufferedReader in = new BufferedReader(
    new InputStreamReader(con.getInputStream()));
String inputLine;
StringBuffer response = new StringBuffer();
while ((inputLine = in.readLine()) != null) {
    response.append(inputLine);
}
in.close();
System.out.println(response.toString());

```

```go
package main

import (
       "bytes"
       "net/http"
)

func main() {

    headers := map[string][]string{
        "Content-Type": []string{"application/json"},
        "Accept": []string{"application/json"},
    }

    data := bytes.NewBuffer([]byte{jsonReq})
    req, err := http.NewRequest("POST", "/api/organizations/{parent_lookup_organization_id}/invites/", data)
    req.Header = headers

    client := &http.Client{}
    resp, err := client.Do(req)
    // ...
}

```

`POST /api/organizations/{parent_lookup_organization_id}/invites/`

> Body parameter

```json
{
  "target_email": "user@example.com",
  "first_name": "string"
}
```

```yaml
target_email: user@example.com
first_name: string

```

<h3 id="invites_create-parameters">Parameters</h3>

|Name|In|Type|Required|Description|
|---|---|---|---|---|
|parent_lookup_organization_id|path|string|true|none|
|body|body|[OrganizationInvite](#schemaorganizationinvite)|true|none|

> Example responses

> 201 Response

```json
{
  "id": "497f6eca-6276-4993-bfeb-53cbbbba6f08",
  "target_email": "user@example.com",
  "first_name": "string",
  "emailing_attempt_made": true,
  "is_expired": true,
  "created_by": {
    "id": 0,
    "uuid": "095be615-a8ad-4c33-8e9c-c7612fbf6c9f",
    "distinct_id": "string",
    "first_name": "string",
    "email": "user@example.com"
  },
  "created_at": "2019-08-24T14:15:22Z",
  "updated_at": "2019-08-24T14:15:22Z"
}
```

<h3 id="invites_create-responses">Responses</h3>

|Status|Meaning|Description|Schema|
|---|---|---|---|
|201|[Created](https://tools.ietf.org/html/rfc7231#section-6.3.2)|none|[OrganizationInvite](#schemaorganizationinvite)|

<aside class="success">
This operation does not require authentication
</aside>

## invites_destroy

<a id="opIdinvites_destroy"></a>

> Code samples

```shell
# You can also use wget
curl -X DELETE /api/organizations/{parent_lookup_organization_id}/invites/{id}/

```

```http
DELETE /api/organizations/{parent_lookup_organization_id}/invites/{id}/ HTTP/1.1

```

```javascript

fetch('/api/organizations/{parent_lookup_organization_id}/invites/{id}/',
{
  method: 'DELETE'

})
.then(function(res) {
    return res.json();
}).then(function(body) {
    console.log(body);
});

```

```ruby
require 'rest-client'
require 'json'

result = RestClient.delete '/api/organizations/{parent_lookup_organization_id}/invites/{id}/',
  params: {
  }

p JSON.parse(result)

```

```python
import requests

r = requests.delete('/api/organizations/{parent_lookup_organization_id}/invites/{id}/')

print(r.json())

```

```php
<?php

require 'vendor/autoload.php';

$client = new \GuzzleHttp\Client();

// Define array of request body.
$request_body = array();

try {
    $response = $client->request('DELETE','/api/organizations/{parent_lookup_organization_id}/invites/{id}/', array(
        'headers' => $headers,
        'json' => $request_body,
       )
    );
    print_r($response->getBody()->getContents());
 }
 catch (\GuzzleHttp\Exception\BadResponseException $e) {
    // handle exception or api errors.
    print_r($e->getMessage());
 }

 // ...

```

```java
URL obj = new URL("/api/organizations/{parent_lookup_organization_id}/invites/{id}/");
HttpURLConnection con = (HttpURLConnection) obj.openConnection();
con.setRequestMethod("DELETE");
int responseCode = con.getResponseCode();
BufferedReader in = new BufferedReader(
    new InputStreamReader(con.getInputStream()));
String inputLine;
StringBuffer response = new StringBuffer();
while ((inputLine = in.readLine()) != null) {
    response.append(inputLine);
}
in.close();
System.out.println(response.toString());

```

```go
package main

import (
       "bytes"
       "net/http"
)

func main() {

    data := bytes.NewBuffer([]byte{jsonReq})
    req, err := http.NewRequest("DELETE", "/api/organizations/{parent_lookup_organization_id}/invites/{id}/", data)
    req.Header = headers

    client := &http.Client{}
    resp, err := client.Do(req)
    // ...
}

```

`DELETE /api/organizations/{parent_lookup_organization_id}/invites/{id}/`

<h3 id="invites_destroy-parameters">Parameters</h3>

|Name|In|Type|Required|Description|
|---|---|---|---|---|
|id|path|string(uuid)|true|A UUID string identifying this organization invite.|
|parent_lookup_organization_id|path|string|true|none|

<h3 id="invites_destroy-responses">Responses</h3>

|Status|Meaning|Description|Schema|
|---|---|---|---|
|204|[No Content](https://tools.ietf.org/html/rfc7231#section-6.3.5)|No response body|None|

<aside class="success">
This operation does not require authentication
</aside>

## invites_bulk_create

<a id="opIdinvites_bulk_create"></a>

> Code samples

```shell
# You can also use wget
curl -X POST /api/organizations/{parent_lookup_organization_id}/invites/bulk/ \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json'

```

```http
POST /api/organizations/{parent_lookup_organization_id}/invites/bulk/ HTTP/1.1

Content-Type: application/json
Accept: application/json

```

```javascript
const inputBody = '{
  "target_email": "user@example.com",
  "first_name": "string"
}';
const headers = {
  'Content-Type':'application/json',
  'Accept':'application/json'
};

fetch('/api/organizations/{parent_lookup_organization_id}/invites/bulk/',
{
  method: 'POST',
  body: inputBody,
  headers: headers
})
.then(function(res) {
    return res.json();
}).then(function(body) {
    console.log(body);
});

```

```ruby
require 'rest-client'
require 'json'

headers = {
  'Content-Type' => 'application/json',
  'Accept' => 'application/json'
}

result = RestClient.post '/api/organizations/{parent_lookup_organization_id}/invites/bulk/',
  params: {
  }, headers: headers

p JSON.parse(result)

```

```python
import requests
headers = {
  'Content-Type': 'application/json',
  'Accept': 'application/json'
}

r = requests.post('/api/organizations/{parent_lookup_organization_id}/invites/bulk/', headers = headers)

print(r.json())

```

```php
<?php

require 'vendor/autoload.php';

$headers = array(
    'Content-Type' => 'application/json',
    'Accept' => 'application/json',
);

$client = new \GuzzleHttp\Client();

// Define array of request body.
$request_body = array();

try {
    $response = $client->request('POST','/api/organizations/{parent_lookup_organization_id}/invites/bulk/', array(
        'headers' => $headers,
        'json' => $request_body,
       )
    );
    print_r($response->getBody()->getContents());
 }
 catch (\GuzzleHttp\Exception\BadResponseException $e) {
    // handle exception or api errors.
    print_r($e->getMessage());
 }

 // ...

```

```java
URL obj = new URL("/api/organizations/{parent_lookup_organization_id}/invites/bulk/");
HttpURLConnection con = (HttpURLConnection) obj.openConnection();
con.setRequestMethod("POST");
int responseCode = con.getResponseCode();
BufferedReader in = new BufferedReader(
    new InputStreamReader(con.getInputStream()));
String inputLine;
StringBuffer response = new StringBuffer();
while ((inputLine = in.readLine()) != null) {
    response.append(inputLine);
}
in.close();
System.out.println(response.toString());

```

```go
package main

import (
       "bytes"
       "net/http"
)

func main() {

    headers := map[string][]string{
        "Content-Type": []string{"application/json"},
        "Accept": []string{"application/json"},
    }

    data := bytes.NewBuffer([]byte{jsonReq})
    req, err := http.NewRequest("POST", "/api/organizations/{parent_lookup_organization_id}/invites/bulk/", data)
    req.Header = headers

    client := &http.Client{}
    resp, err := client.Do(req)
    // ...
}

```

`POST /api/organizations/{parent_lookup_organization_id}/invites/bulk/`

> Body parameter

```json
{
  "target_email": "user@example.com",
  "first_name": "string"
}
```

```yaml
target_email: user@example.com
first_name: string

```

<h3 id="invites_bulk_create-parameters">Parameters</h3>

|Name|In|Type|Required|Description|
|---|---|---|---|---|
|parent_lookup_organization_id|path|string|true|none|
|body|body|[OrganizationInvite](#schemaorganizationinvite)|true|none|

> Example responses

> 200 Response

```json
{
  "id": "497f6eca-6276-4993-bfeb-53cbbbba6f08",
  "target_email": "user@example.com",
  "first_name": "string",
  "emailing_attempt_made": true,
  "is_expired": true,
  "created_by": {
    "id": 0,
    "uuid": "095be615-a8ad-4c33-8e9c-c7612fbf6c9f",
    "distinct_id": "string",
    "first_name": "string",
    "email": "user@example.com"
  },
  "created_at": "2019-08-24T14:15:22Z",
  "updated_at": "2019-08-24T14:15:22Z"
}
```

<h3 id="invites_bulk_create-responses">Responses</h3>

|Status|Meaning|Description|Schema|
|---|---|---|---|
|200|[OK](https://tools.ietf.org/html/rfc7231#section-6.3.1)|none|[OrganizationInvite](#schemaorganizationinvite)|

<aside class="success">
This operation does not require authentication
</aside>

## members_list

<a id="opIdmembers_list"></a>

> Code samples

```shell
# You can also use wget
curl -X GET /api/organizations/{parent_lookup_organization_id}/members/ \
  -H 'Accept: application/json'

```

```http
GET /api/organizations/{parent_lookup_organization_id}/members/ HTTP/1.1

Accept: application/json

```

```javascript

const headers = {
  'Accept':'application/json'
};

fetch('/api/organizations/{parent_lookup_organization_id}/members/',
{
  method: 'GET',

  headers: headers
})
.then(function(res) {
    return res.json();
}).then(function(body) {
    console.log(body);
});

```

```ruby
require 'rest-client'
require 'json'

headers = {
  'Accept' => 'application/json'
}

result = RestClient.get '/api/organizations/{parent_lookup_organization_id}/members/',
  params: {
  }, headers: headers

p JSON.parse(result)

```

```python
import requests
headers = {
  'Accept': 'application/json'
}

r = requests.get('/api/organizations/{parent_lookup_organization_id}/members/', headers = headers)

print(r.json())

```

```php
<?php

require 'vendor/autoload.php';

$headers = array(
    'Accept' => 'application/json',
);

$client = new \GuzzleHttp\Client();

// Define array of request body.
$request_body = array();

try {
    $response = $client->request('GET','/api/organizations/{parent_lookup_organization_id}/members/', array(
        'headers' => $headers,
        'json' => $request_body,
       )
    );
    print_r($response->getBody()->getContents());
 }
 catch (\GuzzleHttp\Exception\BadResponseException $e) {
    // handle exception or api errors.
    print_r($e->getMessage());
 }

 // ...

```

```java
URL obj = new URL("/api/organizations/{parent_lookup_organization_id}/members/");
HttpURLConnection con = (HttpURLConnection) obj.openConnection();
con.setRequestMethod("GET");
int responseCode = con.getResponseCode();
BufferedReader in = new BufferedReader(
    new InputStreamReader(con.getInputStream()));
String inputLine;
StringBuffer response = new StringBuffer();
while ((inputLine = in.readLine()) != null) {
    response.append(inputLine);
}
in.close();
System.out.println(response.toString());

```

```go
package main

import (
       "bytes"
       "net/http"
)

func main() {

    headers := map[string][]string{
        "Accept": []string{"application/json"},
    }

    data := bytes.NewBuffer([]byte{jsonReq})
    req, err := http.NewRequest("GET", "/api/organizations/{parent_lookup_organization_id}/members/", data)
    req.Header = headers

    client := &http.Client{}
    resp, err := client.Do(req)
    // ...
}

```

`GET /api/organizations/{parent_lookup_organization_id}/members/`

<h3 id="members_list-parameters">Parameters</h3>

|Name|In|Type|Required|Description|
|---|---|---|---|---|
|limit|query|integer|false|Number of results to return per page.|
|offset|query|integer|false|The initial index from which to return the results.|
|parent_lookup_organization_id|path|string|true|none|

> Example responses

> 200 Response

```json
{
  "count": 123,
  "next": "http://api.example.org/accounts/?offset=400&limit=100",
  "previous": "http://api.example.org/accounts/?offset=200&limit=100",
  "results": [
    {
      "id": "497f6eca-6276-4993-bfeb-53cbbbba6f08",
      "user": {
        "id": 0,
        "uuid": "095be615-a8ad-4c33-8e9c-c7612fbf6c9f",
        "distinct_id": "string",
        "first_name": "string",
        "email": "user@example.com"
      },
      "level": 1,
      "joined_at": "2019-08-24T14:15:22Z",
      "updated_at": "2019-08-24T14:15:22Z"
    }
  ]
}
```

<h3 id="members_list-responses">Responses</h3>

|Status|Meaning|Description|Schema|
|---|---|---|---|
|200|[OK](https://tools.ietf.org/html/rfc7231#section-6.3.1)|none|[PaginatedOrganizationMemberList](#schemapaginatedorganizationmemberlist)|

<aside class="success">
This operation does not require authentication
</aside>

## members_update

<a id="opIdmembers_update"></a>

> Code samples

```shell
# You can also use wget
curl -X PUT /api/organizations/{parent_lookup_organization_id}/members/{user__uuid}/ \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json'

```

```http
PUT /api/organizations/{parent_lookup_organization_id}/members/{user__uuid}/ HTTP/1.1

Content-Type: application/json
Accept: application/json

```

```javascript
const inputBody = '{
  "level": 1
}';
const headers = {
  'Content-Type':'application/json',
  'Accept':'application/json'
};

fetch('/api/organizations/{parent_lookup_organization_id}/members/{user__uuid}/',
{
  method: 'PUT',
  body: inputBody,
  headers: headers
})
.then(function(res) {
    return res.json();
}).then(function(body) {
    console.log(body);
});

```

```ruby
require 'rest-client'
require 'json'

headers = {
  'Content-Type' => 'application/json',
  'Accept' => 'application/json'
}

result = RestClient.put '/api/organizations/{parent_lookup_organization_id}/members/{user__uuid}/',
  params: {
  }, headers: headers

p JSON.parse(result)

```

```python
import requests
headers = {
  'Content-Type': 'application/json',
  'Accept': 'application/json'
}

r = requests.put('/api/organizations/{parent_lookup_organization_id}/members/{user__uuid}/', headers = headers)

print(r.json())

```

```php
<?php

require 'vendor/autoload.php';

$headers = array(
    'Content-Type' => 'application/json',
    'Accept' => 'application/json',
);

$client = new \GuzzleHttp\Client();

// Define array of request body.
$request_body = array();

try {
    $response = $client->request('PUT','/api/organizations/{parent_lookup_organization_id}/members/{user__uuid}/', array(
        'headers' => $headers,
        'json' => $request_body,
       )
    );
    print_r($response->getBody()->getContents());
 }
 catch (\GuzzleHttp\Exception\BadResponseException $e) {
    // handle exception or api errors.
    print_r($e->getMessage());
 }

 // ...

```

```java
URL obj = new URL("/api/organizations/{parent_lookup_organization_id}/members/{user__uuid}/");
HttpURLConnection con = (HttpURLConnection) obj.openConnection();
con.setRequestMethod("PUT");
int responseCode = con.getResponseCode();
BufferedReader in = new BufferedReader(
    new InputStreamReader(con.getInputStream()));
String inputLine;
StringBuffer response = new StringBuffer();
while ((inputLine = in.readLine()) != null) {
    response.append(inputLine);
}
in.close();
System.out.println(response.toString());

```

```go
package main

import (
       "bytes"
       "net/http"
)

func main() {

    headers := map[string][]string{
        "Content-Type": []string{"application/json"},
        "Accept": []string{"application/json"},
    }

    data := bytes.NewBuffer([]byte{jsonReq})
    req, err := http.NewRequest("PUT", "/api/organizations/{parent_lookup_organization_id}/members/{user__uuid}/", data)
    req.Header = headers

    client := &http.Client{}
    resp, err := client.Do(req)
    // ...
}

```

`PUT /api/organizations/{parent_lookup_organization_id}/members/{user__uuid}/`

> Body parameter

```json
{
  "level": 1
}
```

```yaml
level: 1

```

<h3 id="members_update-parameters">Parameters</h3>

|Name|In|Type|Required|Description|
|---|---|---|---|---|
|parent_lookup_organization_id|path|string|true|none|
|user__uuid|path|string(uuid)|true|none|
|body|body|[OrganizationMember](#schemaorganizationmember)|false|none|

> Example responses

> 200 Response

```json
{
  "id": "497f6eca-6276-4993-bfeb-53cbbbba6f08",
  "user": {
    "id": 0,
    "uuid": "095be615-a8ad-4c33-8e9c-c7612fbf6c9f",
    "distinct_id": "string",
    "first_name": "string",
    "email": "user@example.com"
  },
  "level": 1,
  "joined_at": "2019-08-24T14:15:22Z",
  "updated_at": "2019-08-24T14:15:22Z"
}
```

<h3 id="members_update-responses">Responses</h3>

|Status|Meaning|Description|Schema|
|---|---|---|---|
|200|[OK](https://tools.ietf.org/html/rfc7231#section-6.3.1)|none|[OrganizationMember](#schemaorganizationmember)|

<aside class="success">
This operation does not require authentication
</aside>

## members_partial_update

<a id="opIdmembers_partial_update"></a>

> Code samples

```shell
# You can also use wget
curl -X PATCH /api/organizations/{parent_lookup_organization_id}/members/{user__uuid}/ \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json'

```

```http
PATCH /api/organizations/{parent_lookup_organization_id}/members/{user__uuid}/ HTTP/1.1

Content-Type: application/json
Accept: application/json

```

```javascript
const inputBody = '{
  "level": 1
}';
const headers = {
  'Content-Type':'application/json',
  'Accept':'application/json'
};

fetch('/api/organizations/{parent_lookup_organization_id}/members/{user__uuid}/',
{
  method: 'PATCH',
  body: inputBody,
  headers: headers
})
.then(function(res) {
    return res.json();
}).then(function(body) {
    console.log(body);
});

```

```ruby
require 'rest-client'
require 'json'

headers = {
  'Content-Type' => 'application/json',
  'Accept' => 'application/json'
}

result = RestClient.patch '/api/organizations/{parent_lookup_organization_id}/members/{user__uuid}/',
  params: {
  }, headers: headers

p JSON.parse(result)

```

```python
import requests
headers = {
  'Content-Type': 'application/json',
  'Accept': 'application/json'
}

r = requests.patch('/api/organizations/{parent_lookup_organization_id}/members/{user__uuid}/', headers = headers)

print(r.json())

```

```php
<?php

require 'vendor/autoload.php';

$headers = array(
    'Content-Type' => 'application/json',
    'Accept' => 'application/json',
);

$client = new \GuzzleHttp\Client();

// Define array of request body.
$request_body = array();

try {
    $response = $client->request('PATCH','/api/organizations/{parent_lookup_organization_id}/members/{user__uuid}/', array(
        'headers' => $headers,
        'json' => $request_body,
       )
    );
    print_r($response->getBody()->getContents());
 }
 catch (\GuzzleHttp\Exception\BadResponseException $e) {
    // handle exception or api errors.
    print_r($e->getMessage());
 }

 // ...

```

```java
URL obj = new URL("/api/organizations/{parent_lookup_organization_id}/members/{user__uuid}/");
HttpURLConnection con = (HttpURLConnection) obj.openConnection();
con.setRequestMethod("PATCH");
int responseCode = con.getResponseCode();
BufferedReader in = new BufferedReader(
    new InputStreamReader(con.getInputStream()));
String inputLine;
StringBuffer response = new StringBuffer();
while ((inputLine = in.readLine()) != null) {
    response.append(inputLine);
}
in.close();
System.out.println(response.toString());

```

```go
package main

import (
       "bytes"
       "net/http"
)

func main() {

    headers := map[string][]string{
        "Content-Type": []string{"application/json"},
        "Accept": []string{"application/json"},
    }

    data := bytes.NewBuffer([]byte{jsonReq})
    req, err := http.NewRequest("PATCH", "/api/organizations/{parent_lookup_organization_id}/members/{user__uuid}/", data)
    req.Header = headers

    client := &http.Client{}
    resp, err := client.Do(req)
    // ...
}

```

`PATCH /api/organizations/{parent_lookup_organization_id}/members/{user__uuid}/`

> Body parameter

```json
{
  "level": 1
}
```

```yaml
level: 1

```

<h3 id="members_partial_update-parameters">Parameters</h3>

|Name|In|Type|Required|Description|
|---|---|---|---|---|
|parent_lookup_organization_id|path|string|true|none|
|user__uuid|path|string(uuid)|true|none|
|body|body|[PatchedOrganizationMember](#schemapatchedorganizationmember)|false|none|

> Example responses

> 200 Response

```json
{
  "id": "497f6eca-6276-4993-bfeb-53cbbbba6f08",
  "user": {
    "id": 0,
    "uuid": "095be615-a8ad-4c33-8e9c-c7612fbf6c9f",
    "distinct_id": "string",
    "first_name": "string",
    "email": "user@example.com"
  },
  "level": 1,
  "joined_at": "2019-08-24T14:15:22Z",
  "updated_at": "2019-08-24T14:15:22Z"
}
```

<h3 id="members_partial_update-responses">Responses</h3>

|Status|Meaning|Description|Schema|
|---|---|---|---|
|200|[OK](https://tools.ietf.org/html/rfc7231#section-6.3.1)|none|[OrganizationMember](#schemaorganizationmember)|

<aside class="success">
This operation does not require authentication
</aside>

## members_destroy

<a id="opIdmembers_destroy"></a>

> Code samples

```shell
# You can also use wget
curl -X DELETE /api/organizations/{parent_lookup_organization_id}/members/{user__uuid}/

```

```http
DELETE /api/organizations/{parent_lookup_organization_id}/members/{user__uuid}/ HTTP/1.1

```

```javascript

fetch('/api/organizations/{parent_lookup_organization_id}/members/{user__uuid}/',
{
  method: 'DELETE'

})
.then(function(res) {
    return res.json();
}).then(function(body) {
    console.log(body);
});

```

```ruby
require 'rest-client'
require 'json'

result = RestClient.delete '/api/organizations/{parent_lookup_organization_id}/members/{user__uuid}/',
  params: {
  }

p JSON.parse(result)

```

```python
import requests

r = requests.delete('/api/organizations/{parent_lookup_organization_id}/members/{user__uuid}/')

print(r.json())

```

```php
<?php

require 'vendor/autoload.php';

$client = new \GuzzleHttp\Client();

// Define array of request body.
$request_body = array();

try {
    $response = $client->request('DELETE','/api/organizations/{parent_lookup_organization_id}/members/{user__uuid}/', array(
        'headers' => $headers,
        'json' => $request_body,
       )
    );
    print_r($response->getBody()->getContents());
 }
 catch (\GuzzleHttp\Exception\BadResponseException $e) {
    // handle exception or api errors.
    print_r($e->getMessage());
 }

 // ...

```

```java
URL obj = new URL("/api/organizations/{parent_lookup_organization_id}/members/{user__uuid}/");
HttpURLConnection con = (HttpURLConnection) obj.openConnection();
con.setRequestMethod("DELETE");
int responseCode = con.getResponseCode();
BufferedReader in = new BufferedReader(
    new InputStreamReader(con.getInputStream()));
String inputLine;
StringBuffer response = new StringBuffer();
while ((inputLine = in.readLine()) != null) {
    response.append(inputLine);
}
in.close();
System.out.println(response.toString());

```

```go
package main

import (
       "bytes"
       "net/http"
)

func main() {

    data := bytes.NewBuffer([]byte{jsonReq})
    req, err := http.NewRequest("DELETE", "/api/organizations/{parent_lookup_organization_id}/members/{user__uuid}/", data)
    req.Header = headers

    client := &http.Client{}
    resp, err := client.Do(req)
    // ...
}

```

`DELETE /api/organizations/{parent_lookup_organization_id}/members/{user__uuid}/`

<h3 id="members_destroy-parameters">Parameters</h3>

|Name|In|Type|Required|Description|
|---|---|---|---|---|
|parent_lookup_organization_id|path|string|true|none|
|user__uuid|path|string(uuid)|true|none|

<h3 id="members_destroy-responses">Responses</h3>

|Status|Meaning|Description|Schema|
|---|---|---|---|
|204|[No Content](https://tools.ietf.org/html/rfc7231#section-6.3.5)|No response body|None|

<aside class="success">
This operation does not require authentication
</aside>

## plugins_list

<a id="opIdplugins_list"></a>

> Code samples

```shell
# You can also use wget
curl -X GET /api/organizations/{parent_lookup_organization_id}/plugins/ \
  -H 'Accept: application/json'

```

```http
GET /api/organizations/{parent_lookup_organization_id}/plugins/ HTTP/1.1

Accept: application/json

```

```javascript

const headers = {
  'Accept':'application/json'
};

fetch('/api/organizations/{parent_lookup_organization_id}/plugins/',
{
  method: 'GET',

  headers: headers
})
.then(function(res) {
    return res.json();
}).then(function(body) {
    console.log(body);
});

```

```ruby
require 'rest-client'
require 'json'

headers = {
  'Accept' => 'application/json'
}

result = RestClient.get '/api/organizations/{parent_lookup_organization_id}/plugins/',
  params: {
  }, headers: headers

p JSON.parse(result)

```

```python
import requests
headers = {
  'Accept': 'application/json'
}

r = requests.get('/api/organizations/{parent_lookup_organization_id}/plugins/', headers = headers)

print(r.json())

```

```php
<?php

require 'vendor/autoload.php';

$headers = array(
    'Accept' => 'application/json',
);

$client = new \GuzzleHttp\Client();

// Define array of request body.
$request_body = array();

try {
    $response = $client->request('GET','/api/organizations/{parent_lookup_organization_id}/plugins/', array(
        'headers' => $headers,
        'json' => $request_body,
       )
    );
    print_r($response->getBody()->getContents());
 }
 catch (\GuzzleHttp\Exception\BadResponseException $e) {
    // handle exception or api errors.
    print_r($e->getMessage());
 }

 // ...

```

```java
URL obj = new URL("/api/organizations/{parent_lookup_organization_id}/plugins/");
HttpURLConnection con = (HttpURLConnection) obj.openConnection();
con.setRequestMethod("GET");
int responseCode = con.getResponseCode();
BufferedReader in = new BufferedReader(
    new InputStreamReader(con.getInputStream()));
String inputLine;
StringBuffer response = new StringBuffer();
while ((inputLine = in.readLine()) != null) {
    response.append(inputLine);
}
in.close();
System.out.println(response.toString());

```

```go
package main

import (
       "bytes"
       "net/http"
)

func main() {

    headers := map[string][]string{
        "Accept": []string{"application/json"},
    }

    data := bytes.NewBuffer([]byte{jsonReq})
    req, err := http.NewRequest("GET", "/api/organizations/{parent_lookup_organization_id}/plugins/", data)
    req.Header = headers

    client := &http.Client{}
    resp, err := client.Do(req)
    // ...
}

```

`GET /api/organizations/{parent_lookup_organization_id}/plugins/`

<h3 id="plugins_list-parameters">Parameters</h3>

|Name|In|Type|Required|Description|
|---|---|---|---|---|
|limit|query|integer|false|Number of results to return per page.|
|offset|query|integer|false|The initial index from which to return the results.|
|parent_lookup_organization_id|path|string|true|none|

> Example responses

> 200 Response

```json
{
  "count": 123,
  "next": "http://api.example.org/accounts/?offset=400&limit=100",
  "previous": "http://api.example.org/accounts/?offset=200&limit=100",
  "results": [
    {
      "id": 0,
      "plugin_type": "local",
      "name": "string",
      "description": "string",
      "url": "string",
      "config_schema": {
        "property1": null,
        "property2": null
      },
      "tag": "string",
      "source": "string",
      "latest_tag": "string",
      "is_global": true,
      "organization_id": "7c60d51f-b44e-4682-87d6-449835ea4de6",
      "organization_name": "string",
      "capabilities": {
        "property1": null,
        "property2": null
      },
      "metrics": {
        "property1": null,
        "property2": null
      },
      "public_jobs": {
        "property1": null,
        "property2": null
      }
    }
  ]
}
```

<h3 id="plugins_list-responses">Responses</h3>

|Status|Meaning|Description|Schema|
|---|---|---|---|
|200|[OK](https://tools.ietf.org/html/rfc7231#section-6.3.1)|none|[PaginatedPluginList](#schemapaginatedpluginlist)|

<aside class="success">
This operation does not require authentication
</aside>

## plugins_create

<a id="opIdplugins_create"></a>

> Code samples

```shell
# You can also use wget
curl -X POST /api/organizations/{parent_lookup_organization_id}/plugins/ \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json'

```

```http
POST /api/organizations/{parent_lookup_organization_id}/plugins/ HTTP/1.1

Content-Type: application/json
Accept: application/json

```

```javascript
const inputBody = '{
  "plugin_type": "local",
  "name": "string",
  "description": "string",
  "config_schema": {
    "property1": null,
    "property2": null
  },
  "tag": "string",
  "source": "string",
  "is_global": true,
  "capabilities": {
    "property1": null,
    "property2": null
  },
  "metrics": {
    "property1": null,
    "property2": null
  },
  "public_jobs": {
    "property1": null,
    "property2": null
  }
}';
const headers = {
  'Content-Type':'application/json',
  'Accept':'application/json'
};

fetch('/api/organizations/{parent_lookup_organization_id}/plugins/',
{
  method: 'POST',
  body: inputBody,
  headers: headers
})
.then(function(res) {
    return res.json();
}).then(function(body) {
    console.log(body);
});

```

```ruby
require 'rest-client'
require 'json'

headers = {
  'Content-Type' => 'application/json',
  'Accept' => 'application/json'
}

result = RestClient.post '/api/organizations/{parent_lookup_organization_id}/plugins/',
  params: {
  }, headers: headers

p JSON.parse(result)

```

```python
import requests
headers = {
  'Content-Type': 'application/json',
  'Accept': 'application/json'
}

r = requests.post('/api/organizations/{parent_lookup_organization_id}/plugins/', headers = headers)

print(r.json())

```

```php
<?php

require 'vendor/autoload.php';

$headers = array(
    'Content-Type' => 'application/json',
    'Accept' => 'application/json',
);

$client = new \GuzzleHttp\Client();

// Define array of request body.
$request_body = array();

try {
    $response = $client->request('POST','/api/organizations/{parent_lookup_organization_id}/plugins/', array(
        'headers' => $headers,
        'json' => $request_body,
       )
    );
    print_r($response->getBody()->getContents());
 }
 catch (\GuzzleHttp\Exception\BadResponseException $e) {
    // handle exception or api errors.
    print_r($e->getMessage());
 }

 // ...

```

```java
URL obj = new URL("/api/organizations/{parent_lookup_organization_id}/plugins/");
HttpURLConnection con = (HttpURLConnection) obj.openConnection();
con.setRequestMethod("POST");
int responseCode = con.getResponseCode();
BufferedReader in = new BufferedReader(
    new InputStreamReader(con.getInputStream()));
String inputLine;
StringBuffer response = new StringBuffer();
while ((inputLine = in.readLine()) != null) {
    response.append(inputLine);
}
in.close();
System.out.println(response.toString());

```

```go
package main

import (
       "bytes"
       "net/http"
)

func main() {

    headers := map[string][]string{
        "Content-Type": []string{"application/json"},
        "Accept": []string{"application/json"},
    }

    data := bytes.NewBuffer([]byte{jsonReq})
    req, err := http.NewRequest("POST", "/api/organizations/{parent_lookup_organization_id}/plugins/", data)
    req.Header = headers

    client := &http.Client{}
    resp, err := client.Do(req)
    // ...
}

```

`POST /api/organizations/{parent_lookup_organization_id}/plugins/`

> Body parameter

```json
{
  "plugin_type": "local",
  "name": "string",
  "description": "string",
  "config_schema": {
    "property1": null,
    "property2": null
  },
  "tag": "string",
  "source": "string",
  "is_global": true,
  "capabilities": {
    "property1": null,
    "property2": null
  },
  "metrics": {
    "property1": null,
    "property2": null
  },
  "public_jobs": {
    "property1": null,
    "property2": null
  }
}
```

```yaml
plugin_type: local
name: string
description: string
config_schema:
  ? property1
  ? property2
tag: string
source: string
is_global: true
capabilities:
  ? property1
  ? property2
metrics:
  ? property1
  ? property2
public_jobs:
  ? property1
  ? property2

```

<h3 id="plugins_create-parameters">Parameters</h3>

|Name|In|Type|Required|Description|
|---|---|---|---|---|
|parent_lookup_organization_id|path|string|true|none|
|body|body|[Plugin](#schemaplugin)|false|none|

> Example responses

> 201 Response

```json
{
  "id": 0,
  "plugin_type": "local",
  "name": "string",
  "description": "string",
  "url": "string",
  "config_schema": {
    "property1": null,
    "property2": null
  },
  "tag": "string",
  "source": "string",
  "latest_tag": "string",
  "is_global": true,
  "organization_id": "7c60d51f-b44e-4682-87d6-449835ea4de6",
  "organization_name": "string",
  "capabilities": {
    "property1": null,
    "property2": null
  },
  "metrics": {
    "property1": null,
    "property2": null
  },
  "public_jobs": {
    "property1": null,
    "property2": null
  }
}
```

<h3 id="plugins_create-responses">Responses</h3>

|Status|Meaning|Description|Schema|
|---|---|---|---|
|201|[Created](https://tools.ietf.org/html/rfc7231#section-6.3.2)|none|[Plugin](#schemaplugin)|

<aside class="success">
This operation does not require authentication
</aside>

## plugins_retrieve

<a id="opIdplugins_retrieve"></a>

> Code samples

```shell
# You can also use wget
curl -X GET /api/organizations/{parent_lookup_organization_id}/plugins/{id}/ \
  -H 'Accept: application/json'

```

```http
GET /api/organizations/{parent_lookup_organization_id}/plugins/{id}/ HTTP/1.1

Accept: application/json

```

```javascript

const headers = {
  'Accept':'application/json'
};

fetch('/api/organizations/{parent_lookup_organization_id}/plugins/{id}/',
{
  method: 'GET',

  headers: headers
})
.then(function(res) {
    return res.json();
}).then(function(body) {
    console.log(body);
});

```

```ruby
require 'rest-client'
require 'json'

headers = {
  'Accept' => 'application/json'
}

result = RestClient.get '/api/organizations/{parent_lookup_organization_id}/plugins/{id}/',
  params: {
  }, headers: headers

p JSON.parse(result)

```

```python
import requests
headers = {
  'Accept': 'application/json'
}

r = requests.get('/api/organizations/{parent_lookup_organization_id}/plugins/{id}/', headers = headers)

print(r.json())

```

```php
<?php

require 'vendor/autoload.php';

$headers = array(
    'Accept' => 'application/json',
);

$client = new \GuzzleHttp\Client();

// Define array of request body.
$request_body = array();

try {
    $response = $client->request('GET','/api/organizations/{parent_lookup_organization_id}/plugins/{id}/', array(
        'headers' => $headers,
        'json' => $request_body,
       )
    );
    print_r($response->getBody()->getContents());
 }
 catch (\GuzzleHttp\Exception\BadResponseException $e) {
    // handle exception or api errors.
    print_r($e->getMessage());
 }

 // ...

```

```java
URL obj = new URL("/api/organizations/{parent_lookup_organization_id}/plugins/{id}/");
HttpURLConnection con = (HttpURLConnection) obj.openConnection();
con.setRequestMethod("GET");
int responseCode = con.getResponseCode();
BufferedReader in = new BufferedReader(
    new InputStreamReader(con.getInputStream()));
String inputLine;
StringBuffer response = new StringBuffer();
while ((inputLine = in.readLine()) != null) {
    response.append(inputLine);
}
in.close();
System.out.println(response.toString());

```

```go
package main

import (
       "bytes"
       "net/http"
)

func main() {

    headers := map[string][]string{
        "Accept": []string{"application/json"},
    }

    data := bytes.NewBuffer([]byte{jsonReq})
    req, err := http.NewRequest("GET", "/api/organizations/{parent_lookup_organization_id}/plugins/{id}/", data)
    req.Header = headers

    client := &http.Client{}
    resp, err := client.Do(req)
    // ...
}

```

`GET /api/organizations/{parent_lookup_organization_id}/plugins/{id}/`

<h3 id="plugins_retrieve-parameters">Parameters</h3>

|Name|In|Type|Required|Description|
|---|---|---|---|---|
|id|path|integer|true|A unique integer value identifying this plugin.|
|parent_lookup_organization_id|path|string|true|none|

> Example responses

> 200 Response

```json
{
  "id": 0,
  "plugin_type": "local",
  "name": "string",
  "description": "string",
  "url": "string",
  "config_schema": {
    "property1": null,
    "property2": null
  },
  "tag": "string",
  "source": "string",
  "latest_tag": "string",
  "is_global": true,
  "organization_id": "7c60d51f-b44e-4682-87d6-449835ea4de6",
  "organization_name": "string",
  "capabilities": {
    "property1": null,
    "property2": null
  },
  "metrics": {
    "property1": null,
    "property2": null
  },
  "public_jobs": {
    "property1": null,
    "property2": null
  }
}
```

<h3 id="plugins_retrieve-responses">Responses</h3>

|Status|Meaning|Description|Schema|
|---|---|---|---|
|200|[OK](https://tools.ietf.org/html/rfc7231#section-6.3.1)|none|[Plugin](#schemaplugin)|

<aside class="success">
This operation does not require authentication
</aside>

## plugins_update

<a id="opIdplugins_update"></a>

> Code samples

```shell
# You can also use wget
curl -X PUT /api/organizations/{parent_lookup_organization_id}/plugins/{id}/ \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json'

```

```http
PUT /api/organizations/{parent_lookup_organization_id}/plugins/{id}/ HTTP/1.1

Content-Type: application/json
Accept: application/json

```

```javascript
const inputBody = '{
  "plugin_type": "local",
  "name": "string",
  "description": "string",
  "config_schema": {
    "property1": null,
    "property2": null
  },
  "tag": "string",
  "source": "string",
  "is_global": true,
  "capabilities": {
    "property1": null,
    "property2": null
  },
  "metrics": {
    "property1": null,
    "property2": null
  },
  "public_jobs": {
    "property1": null,
    "property2": null
  }
}';
const headers = {
  'Content-Type':'application/json',
  'Accept':'application/json'
};

fetch('/api/organizations/{parent_lookup_organization_id}/plugins/{id}/',
{
  method: 'PUT',
  body: inputBody,
  headers: headers
})
.then(function(res) {
    return res.json();
}).then(function(body) {
    console.log(body);
});

```

```ruby
require 'rest-client'
require 'json'

headers = {
  'Content-Type' => 'application/json',
  'Accept' => 'application/json'
}

result = RestClient.put '/api/organizations/{parent_lookup_organization_id}/plugins/{id}/',
  params: {
  }, headers: headers

p JSON.parse(result)

```

```python
import requests
headers = {
  'Content-Type': 'application/json',
  'Accept': 'application/json'
}

r = requests.put('/api/organizations/{parent_lookup_organization_id}/plugins/{id}/', headers = headers)

print(r.json())

```

```php
<?php

require 'vendor/autoload.php';

$headers = array(
    'Content-Type' => 'application/json',
    'Accept' => 'application/json',
);

$client = new \GuzzleHttp\Client();

// Define array of request body.
$request_body = array();

try {
    $response = $client->request('PUT','/api/organizations/{parent_lookup_organization_id}/plugins/{id}/', array(
        'headers' => $headers,
        'json' => $request_body,
       )
    );
    print_r($response->getBody()->getContents());
 }
 catch (\GuzzleHttp\Exception\BadResponseException $e) {
    // handle exception or api errors.
    print_r($e->getMessage());
 }

 // ...

```

```java
URL obj = new URL("/api/organizations/{parent_lookup_organization_id}/plugins/{id}/");
HttpURLConnection con = (HttpURLConnection) obj.openConnection();
con.setRequestMethod("PUT");
int responseCode = con.getResponseCode();
BufferedReader in = new BufferedReader(
    new InputStreamReader(con.getInputStream()));
String inputLine;
StringBuffer response = new StringBuffer();
while ((inputLine = in.readLine()) != null) {
    response.append(inputLine);
}
in.close();
System.out.println(response.toString());

```

```go
package main

import (
       "bytes"
       "net/http"
)

func main() {

    headers := map[string][]string{
        "Content-Type": []string{"application/json"},
        "Accept": []string{"application/json"},
    }

    data := bytes.NewBuffer([]byte{jsonReq})
    req, err := http.NewRequest("PUT", "/api/organizations/{parent_lookup_organization_id}/plugins/{id}/", data)
    req.Header = headers

    client := &http.Client{}
    resp, err := client.Do(req)
    // ...
}

```

`PUT /api/organizations/{parent_lookup_organization_id}/plugins/{id}/`

> Body parameter

```json
{
  "plugin_type": "local",
  "name": "string",
  "description": "string",
  "config_schema": {
    "property1": null,
    "property2": null
  },
  "tag": "string",
  "source": "string",
  "is_global": true,
  "capabilities": {
    "property1": null,
    "property2": null
  },
  "metrics": {
    "property1": null,
    "property2": null
  },
  "public_jobs": {
    "property1": null,
    "property2": null
  }
}
```

```yaml
plugin_type: local
name: string
description: string
config_schema:
  ? property1
  ? property2
tag: string
source: string
is_global: true
capabilities:
  ? property1
  ? property2
metrics:
  ? property1
  ? property2
public_jobs:
  ? property1
  ? property2

```

<h3 id="plugins_update-parameters">Parameters</h3>

|Name|In|Type|Required|Description|
|---|---|---|---|---|
|id|path|integer|true|A unique integer value identifying this plugin.|
|parent_lookup_organization_id|path|string|true|none|
|body|body|[Plugin](#schemaplugin)|false|none|

> Example responses

> 200 Response

```json
{
  "id": 0,
  "plugin_type": "local",
  "name": "string",
  "description": "string",
  "url": "string",
  "config_schema": {
    "property1": null,
    "property2": null
  },
  "tag": "string",
  "source": "string",
  "latest_tag": "string",
  "is_global": true,
  "organization_id": "7c60d51f-b44e-4682-87d6-449835ea4de6",
  "organization_name": "string",
  "capabilities": {
    "property1": null,
    "property2": null
  },
  "metrics": {
    "property1": null,
    "property2": null
  },
  "public_jobs": {
    "property1": null,
    "property2": null
  }
}
```

<h3 id="plugins_update-responses">Responses</h3>

|Status|Meaning|Description|Schema|
|---|---|---|---|
|200|[OK](https://tools.ietf.org/html/rfc7231#section-6.3.1)|none|[Plugin](#schemaplugin)|

<aside class="success">
This operation does not require authentication
</aside>

## plugins_partial_update

<a id="opIdplugins_partial_update"></a>

> Code samples

```shell
# You can also use wget
curl -X PATCH /api/organizations/{parent_lookup_organization_id}/plugins/{id}/ \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json'

```

```http
PATCH /api/organizations/{parent_lookup_organization_id}/plugins/{id}/ HTTP/1.1

Content-Type: application/json
Accept: application/json

```

```javascript
const inputBody = '{
  "plugin_type": "local",
  "name": "string",
  "description": "string",
  "config_schema": {
    "property1": null,
    "property2": null
  },
  "tag": "string",
  "source": "string",
  "is_global": true,
  "capabilities": {
    "property1": null,
    "property2": null
  },
  "metrics": {
    "property1": null,
    "property2": null
  },
  "public_jobs": {
    "property1": null,
    "property2": null
  }
}';
const headers = {
  'Content-Type':'application/json',
  'Accept':'application/json'
};

fetch('/api/organizations/{parent_lookup_organization_id}/plugins/{id}/',
{
  method: 'PATCH',
  body: inputBody,
  headers: headers
})
.then(function(res) {
    return res.json();
}).then(function(body) {
    console.log(body);
});

```

```ruby
require 'rest-client'
require 'json'

headers = {
  'Content-Type' => 'application/json',
  'Accept' => 'application/json'
}

result = RestClient.patch '/api/organizations/{parent_lookup_organization_id}/plugins/{id}/',
  params: {
  }, headers: headers

p JSON.parse(result)

```

```python
import requests
headers = {
  'Content-Type': 'application/json',
  'Accept': 'application/json'
}

r = requests.patch('/api/organizations/{parent_lookup_organization_id}/plugins/{id}/', headers = headers)

print(r.json())

```

```php
<?php

require 'vendor/autoload.php';

$headers = array(
    'Content-Type' => 'application/json',
    'Accept' => 'application/json',
);

$client = new \GuzzleHttp\Client();

// Define array of request body.
$request_body = array();

try {
    $response = $client->request('PATCH','/api/organizations/{parent_lookup_organization_id}/plugins/{id}/', array(
        'headers' => $headers,
        'json' => $request_body,
       )
    );
    print_r($response->getBody()->getContents());
 }
 catch (\GuzzleHttp\Exception\BadResponseException $e) {
    // handle exception or api errors.
    print_r($e->getMessage());
 }

 // ...

```

```java
URL obj = new URL("/api/organizations/{parent_lookup_organization_id}/plugins/{id}/");
HttpURLConnection con = (HttpURLConnection) obj.openConnection();
con.setRequestMethod("PATCH");
int responseCode = con.getResponseCode();
BufferedReader in = new BufferedReader(
    new InputStreamReader(con.getInputStream()));
String inputLine;
StringBuffer response = new StringBuffer();
while ((inputLine = in.readLine()) != null) {
    response.append(inputLine);
}
in.close();
System.out.println(response.toString());

```

```go
package main

import (
       "bytes"
       "net/http"
)

func main() {

    headers := map[string][]string{
        "Content-Type": []string{"application/json"},
        "Accept": []string{"application/json"},
    }

    data := bytes.NewBuffer([]byte{jsonReq})
    req, err := http.NewRequest("PATCH", "/api/organizations/{parent_lookup_organization_id}/plugins/{id}/", data)
    req.Header = headers

    client := &http.Client{}
    resp, err := client.Do(req)
    // ...
}

```

`PATCH /api/organizations/{parent_lookup_organization_id}/plugins/{id}/`

> Body parameter

```json
{
  "plugin_type": "local",
  "name": "string",
  "description": "string",
  "config_schema": {
    "property1": null,
    "property2": null
  },
  "tag": "string",
  "source": "string",
  "is_global": true,
  "capabilities": {
    "property1": null,
    "property2": null
  },
  "metrics": {
    "property1": null,
    "property2": null
  },
  "public_jobs": {
    "property1": null,
    "property2": null
  }
}
```

```yaml
plugin_type: local
name: string
description: string
config_schema:
  ? property1
  ? property2
tag: string
source: string
is_global: true
capabilities:
  ? property1
  ? property2
metrics:
  ? property1
  ? property2
public_jobs:
  ? property1
  ? property2

```

<h3 id="plugins_partial_update-parameters">Parameters</h3>

|Name|In|Type|Required|Description|
|---|---|---|---|---|
|id|path|integer|true|A unique integer value identifying this plugin.|
|parent_lookup_organization_id|path|string|true|none|
|body|body|[PatchedPlugin](#schemapatchedplugin)|false|none|

> Example responses

> 200 Response

```json
{
  "id": 0,
  "plugin_type": "local",
  "name": "string",
  "description": "string",
  "url": "string",
  "config_schema": {
    "property1": null,
    "property2": null
  },
  "tag": "string",
  "source": "string",
  "latest_tag": "string",
  "is_global": true,
  "organization_id": "7c60d51f-b44e-4682-87d6-449835ea4de6",
  "organization_name": "string",
  "capabilities": {
    "property1": null,
    "property2": null
  },
  "metrics": {
    "property1": null,
    "property2": null
  },
  "public_jobs": {
    "property1": null,
    "property2": null
  }
}
```

<h3 id="plugins_partial_update-responses">Responses</h3>

|Status|Meaning|Description|Schema|
|---|---|---|---|
|200|[OK](https://tools.ietf.org/html/rfc7231#section-6.3.1)|none|[Plugin](#schemaplugin)|

<aside class="success">
This operation does not require authentication
</aside>

## plugins_destroy

<a id="opIdplugins_destroy"></a>

> Code samples

```shell
# You can also use wget
curl -X DELETE /api/organizations/{parent_lookup_organization_id}/plugins/{id}/

```

```http
DELETE /api/organizations/{parent_lookup_organization_id}/plugins/{id}/ HTTP/1.1

```

```javascript

fetch('/api/organizations/{parent_lookup_organization_id}/plugins/{id}/',
{
  method: 'DELETE'

})
.then(function(res) {
    return res.json();
}).then(function(body) {
    console.log(body);
});

```

```ruby
require 'rest-client'
require 'json'

result = RestClient.delete '/api/organizations/{parent_lookup_organization_id}/plugins/{id}/',
  params: {
  }

p JSON.parse(result)

```

```python
import requests

r = requests.delete('/api/organizations/{parent_lookup_organization_id}/plugins/{id}/')

print(r.json())

```

```php
<?php

require 'vendor/autoload.php';

$client = new \GuzzleHttp\Client();

// Define array of request body.
$request_body = array();

try {
    $response = $client->request('DELETE','/api/organizations/{parent_lookup_organization_id}/plugins/{id}/', array(
        'headers' => $headers,
        'json' => $request_body,
       )
    );
    print_r($response->getBody()->getContents());
 }
 catch (\GuzzleHttp\Exception\BadResponseException $e) {
    // handle exception or api errors.
    print_r($e->getMessage());
 }

 // ...

```

```java
URL obj = new URL("/api/organizations/{parent_lookup_organization_id}/plugins/{id}/");
HttpURLConnection con = (HttpURLConnection) obj.openConnection();
con.setRequestMethod("DELETE");
int responseCode = con.getResponseCode();
BufferedReader in = new BufferedReader(
    new InputStreamReader(con.getInputStream()));
String inputLine;
StringBuffer response = new StringBuffer();
while ((inputLine = in.readLine()) != null) {
    response.append(inputLine);
}
in.close();
System.out.println(response.toString());

```

```go
package main

import (
       "bytes"
       "net/http"
)

func main() {

    data := bytes.NewBuffer([]byte{jsonReq})
    req, err := http.NewRequest("DELETE", "/api/organizations/{parent_lookup_organization_id}/plugins/{id}/", data)
    req.Header = headers

    client := &http.Client{}
    resp, err := client.Do(req)
    // ...
}

```

`DELETE /api/organizations/{parent_lookup_organization_id}/plugins/{id}/`

<h3 id="plugins_destroy-parameters">Parameters</h3>

|Name|In|Type|Required|Description|
|---|---|---|---|---|
|id|path|integer|true|A unique integer value identifying this plugin.|
|parent_lookup_organization_id|path|string|true|none|

<h3 id="plugins_destroy-responses">Responses</h3>

|Status|Meaning|Description|Schema|
|---|---|---|---|
|204|[No Content](https://tools.ietf.org/html/rfc7231#section-6.3.5)|No response body|None|

<aside class="success">
This operation does not require authentication
</aside>

## plugins_check_for_updates_retrieve

<a id="opIdplugins_check_for_updates_retrieve"></a>

> Code samples

```shell
# You can also use wget
curl -X GET /api/organizations/{parent_lookup_organization_id}/plugins/{id}/check_for_updates/ \
  -H 'Accept: application/json'

```

```http
GET /api/organizations/{parent_lookup_organization_id}/plugins/{id}/check_for_updates/ HTTP/1.1

Accept: application/json

```

```javascript

const headers = {
  'Accept':'application/json'
};

fetch('/api/organizations/{parent_lookup_organization_id}/plugins/{id}/check_for_updates/',
{
  method: 'GET',

  headers: headers
})
.then(function(res) {
    return res.json();
}).then(function(body) {
    console.log(body);
});

```

```ruby
require 'rest-client'
require 'json'

headers = {
  'Accept' => 'application/json'
}

result = RestClient.get '/api/organizations/{parent_lookup_organization_id}/plugins/{id}/check_for_updates/',
  params: {
  }, headers: headers

p JSON.parse(result)

```

```python
import requests
headers = {
  'Accept': 'application/json'
}

r = requests.get('/api/organizations/{parent_lookup_organization_id}/plugins/{id}/check_for_updates/', headers = headers)

print(r.json())

```

```php
<?php

require 'vendor/autoload.php';

$headers = array(
    'Accept' => 'application/json',
);

$client = new \GuzzleHttp\Client();

// Define array of request body.
$request_body = array();

try {
    $response = $client->request('GET','/api/organizations/{parent_lookup_organization_id}/plugins/{id}/check_for_updates/', array(
        'headers' => $headers,
        'json' => $request_body,
       )
    );
    print_r($response->getBody()->getContents());
 }
 catch (\GuzzleHttp\Exception\BadResponseException $e) {
    // handle exception or api errors.
    print_r($e->getMessage());
 }

 // ...

```

```java
URL obj = new URL("/api/organizations/{parent_lookup_organization_id}/plugins/{id}/check_for_updates/");
HttpURLConnection con = (HttpURLConnection) obj.openConnection();
con.setRequestMethod("GET");
int responseCode = con.getResponseCode();
BufferedReader in = new BufferedReader(
    new InputStreamReader(con.getInputStream()));
String inputLine;
StringBuffer response = new StringBuffer();
while ((inputLine = in.readLine()) != null) {
    response.append(inputLine);
}
in.close();
System.out.println(response.toString());

```

```go
package main

import (
       "bytes"
       "net/http"
)

func main() {

    headers := map[string][]string{
        "Accept": []string{"application/json"},
    }

    data := bytes.NewBuffer([]byte{jsonReq})
    req, err := http.NewRequest("GET", "/api/organizations/{parent_lookup_organization_id}/plugins/{id}/check_for_updates/", data)
    req.Header = headers

    client := &http.Client{}
    resp, err := client.Do(req)
    // ...
}

```

`GET /api/organizations/{parent_lookup_organization_id}/plugins/{id}/check_for_updates/`

<h3 id="plugins_check_for_updates_retrieve-parameters">Parameters</h3>

|Name|In|Type|Required|Description|
|---|---|---|---|---|
|id|path|integer|true|A unique integer value identifying this plugin.|
|parent_lookup_organization_id|path|string|true|none|

> Example responses

> 200 Response

```json
{
  "id": 0,
  "plugin_type": "local",
  "name": "string",
  "description": "string",
  "url": "string",
  "config_schema": {
    "property1": null,
    "property2": null
  },
  "tag": "string",
  "source": "string",
  "latest_tag": "string",
  "is_global": true,
  "organization_id": "7c60d51f-b44e-4682-87d6-449835ea4de6",
  "organization_name": "string",
  "capabilities": {
    "property1": null,
    "property2": null
  },
  "metrics": {
    "property1": null,
    "property2": null
  },
  "public_jobs": {
    "property1": null,
    "property2": null
  }
}
```

<h3 id="plugins_check_for_updates_retrieve-responses">Responses</h3>

|Status|Meaning|Description|Schema|
|---|---|---|---|
|200|[OK](https://tools.ietf.org/html/rfc7231#section-6.3.1)|none|[Plugin](#schemaplugin)|

<aside class="success">
This operation does not require authentication
</aside>

## plugins_upgrade_create

<a id="opIdplugins_upgrade_create"></a>

> Code samples

```shell
# You can also use wget
curl -X POST /api/organizations/{parent_lookup_organization_id}/plugins/{id}/upgrade/ \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json'

```

```http
POST /api/organizations/{parent_lookup_organization_id}/plugins/{id}/upgrade/ HTTP/1.1

Content-Type: application/json
Accept: application/json

```

```javascript
const inputBody = '{
  "plugin_type": "local",
  "name": "string",
  "description": "string",
  "config_schema": {
    "property1": null,
    "property2": null
  },
  "tag": "string",
  "source": "string",
  "is_global": true,
  "capabilities": {
    "property1": null,
    "property2": null
  },
  "metrics": {
    "property1": null,
    "property2": null
  },
  "public_jobs": {
    "property1": null,
    "property2": null
  }
}';
const headers = {
  'Content-Type':'application/json',
  'Accept':'application/json'
};

fetch('/api/organizations/{parent_lookup_organization_id}/plugins/{id}/upgrade/',
{
  method: 'POST',
  body: inputBody,
  headers: headers
})
.then(function(res) {
    return res.json();
}).then(function(body) {
    console.log(body);
});

```

```ruby
require 'rest-client'
require 'json'

headers = {
  'Content-Type' => 'application/json',
  'Accept' => 'application/json'
}

result = RestClient.post '/api/organizations/{parent_lookup_organization_id}/plugins/{id}/upgrade/',
  params: {
  }, headers: headers

p JSON.parse(result)

```

```python
import requests
headers = {
  'Content-Type': 'application/json',
  'Accept': 'application/json'
}

r = requests.post('/api/organizations/{parent_lookup_organization_id}/plugins/{id}/upgrade/', headers = headers)

print(r.json())

```

```php
<?php

require 'vendor/autoload.php';

$headers = array(
    'Content-Type' => 'application/json',
    'Accept' => 'application/json',
);

$client = new \GuzzleHttp\Client();

// Define array of request body.
$request_body = array();

try {
    $response = $client->request('POST','/api/organizations/{parent_lookup_organization_id}/plugins/{id}/upgrade/', array(
        'headers' => $headers,
        'json' => $request_body,
       )
    );
    print_r($response->getBody()->getContents());
 }
 catch (\GuzzleHttp\Exception\BadResponseException $e) {
    // handle exception or api errors.
    print_r($e->getMessage());
 }

 // ...

```

```java
URL obj = new URL("/api/organizations/{parent_lookup_organization_id}/plugins/{id}/upgrade/");
HttpURLConnection con = (HttpURLConnection) obj.openConnection();
con.setRequestMethod("POST");
int responseCode = con.getResponseCode();
BufferedReader in = new BufferedReader(
    new InputStreamReader(con.getInputStream()));
String inputLine;
StringBuffer response = new StringBuffer();
while ((inputLine = in.readLine()) != null) {
    response.append(inputLine);
}
in.close();
System.out.println(response.toString());

```

```go
package main

import (
       "bytes"
       "net/http"
)

func main() {

    headers := map[string][]string{
        "Content-Type": []string{"application/json"},
        "Accept": []string{"application/json"},
    }

    data := bytes.NewBuffer([]byte{jsonReq})
    req, err := http.NewRequest("POST", "/api/organizations/{parent_lookup_organization_id}/plugins/{id}/upgrade/", data)
    req.Header = headers

    client := &http.Client{}
    resp, err := client.Do(req)
    // ...
}

```

`POST /api/organizations/{parent_lookup_organization_id}/plugins/{id}/upgrade/`

> Body parameter

```json
{
  "plugin_type": "local",
  "name": "string",
  "description": "string",
  "config_schema": {
    "property1": null,
    "property2": null
  },
  "tag": "string",
  "source": "string",
  "is_global": true,
  "capabilities": {
    "property1": null,
    "property2": null
  },
  "metrics": {
    "property1": null,
    "property2": null
  },
  "public_jobs": {
    "property1": null,
    "property2": null
  }
}
```

```yaml
plugin_type: local
name: string
description: string
config_schema:
  ? property1
  ? property2
tag: string
source: string
is_global: true
capabilities:
  ? property1
  ? property2
metrics:
  ? property1
  ? property2
public_jobs:
  ? property1
  ? property2

```

<h3 id="plugins_upgrade_create-parameters">Parameters</h3>

|Name|In|Type|Required|Description|
|---|---|---|---|---|
|id|path|integer|true|A unique integer value identifying this plugin.|
|parent_lookup_organization_id|path|string|true|none|
|body|body|[Plugin](#schemaplugin)|false|none|

> Example responses

> 200 Response

```json
{
  "id": 0,
  "plugin_type": "local",
  "name": "string",
  "description": "string",
  "url": "string",
  "config_schema": {
    "property1": null,
    "property2": null
  },
  "tag": "string",
  "source": "string",
  "latest_tag": "string",
  "is_global": true,
  "organization_id": "7c60d51f-b44e-4682-87d6-449835ea4de6",
  "organization_name": "string",
  "capabilities": {
    "property1": null,
    "property2": null
  },
  "metrics": {
    "property1": null,
    "property2": null
  },
  "public_jobs": {
    "property1": null,
    "property2": null
  }
}
```

<h3 id="plugins_upgrade_create-responses">Responses</h3>

|Status|Meaning|Description|Schema|
|---|---|---|---|
|200|[OK](https://tools.ietf.org/html/rfc7231#section-6.3.1)|none|[Plugin](#schemaplugin)|

<aside class="success">
This operation does not require authentication
</aside>

## plugins_repository_retrieve

<a id="opIdplugins_repository_retrieve"></a>

> Code samples

```shell
# You can also use wget
curl -X GET /api/organizations/{parent_lookup_organization_id}/plugins/repository/ \
  -H 'Accept: application/json'

```

```http
GET /api/organizations/{parent_lookup_organization_id}/plugins/repository/ HTTP/1.1

Accept: application/json

```

```javascript

const headers = {
  'Accept':'application/json'
};

fetch('/api/organizations/{parent_lookup_organization_id}/plugins/repository/',
{
  method: 'GET',

  headers: headers
})
.then(function(res) {
    return res.json();
}).then(function(body) {
    console.log(body);
});

```

```ruby
require 'rest-client'
require 'json'

headers = {
  'Accept' => 'application/json'
}

result = RestClient.get '/api/organizations/{parent_lookup_organization_id}/plugins/repository/',
  params: {
  }, headers: headers

p JSON.parse(result)

```

```python
import requests
headers = {
  'Accept': 'application/json'
}

r = requests.get('/api/organizations/{parent_lookup_organization_id}/plugins/repository/', headers = headers)

print(r.json())

```

```php
<?php

require 'vendor/autoload.php';

$headers = array(
    'Accept' => 'application/json',
);

$client = new \GuzzleHttp\Client();

// Define array of request body.
$request_body = array();

try {
    $response = $client->request('GET','/api/organizations/{parent_lookup_organization_id}/plugins/repository/', array(
        'headers' => $headers,
        'json' => $request_body,
       )
    );
    print_r($response->getBody()->getContents());
 }
 catch (\GuzzleHttp\Exception\BadResponseException $e) {
    // handle exception or api errors.
    print_r($e->getMessage());
 }

 // ...

```

```java
URL obj = new URL("/api/organizations/{parent_lookup_organization_id}/plugins/repository/");
HttpURLConnection con = (HttpURLConnection) obj.openConnection();
con.setRequestMethod("GET");
int responseCode = con.getResponseCode();
BufferedReader in = new BufferedReader(
    new InputStreamReader(con.getInputStream()));
String inputLine;
StringBuffer response = new StringBuffer();
while ((inputLine = in.readLine()) != null) {
    response.append(inputLine);
}
in.close();
System.out.println(response.toString());

```

```go
package main

import (
       "bytes"
       "net/http"
)

func main() {

    headers := map[string][]string{
        "Accept": []string{"application/json"},
    }

    data := bytes.NewBuffer([]byte{jsonReq})
    req, err := http.NewRequest("GET", "/api/organizations/{parent_lookup_organization_id}/plugins/repository/", data)
    req.Header = headers

    client := &http.Client{}
    resp, err := client.Do(req)
    // ...
}

```

`GET /api/organizations/{parent_lookup_organization_id}/plugins/repository/`

<h3 id="plugins_repository_retrieve-parameters">Parameters</h3>

|Name|In|Type|Required|Description|
|---|---|---|---|---|
|parent_lookup_organization_id|path|string|true|none|

> Example responses

> 200 Response

```json
{
  "id": 0,
  "plugin_type": "local",
  "name": "string",
  "description": "string",
  "url": "string",
  "config_schema": {
    "property1": null,
    "property2": null
  },
  "tag": "string",
  "source": "string",
  "latest_tag": "string",
  "is_global": true,
  "organization_id": "7c60d51f-b44e-4682-87d6-449835ea4de6",
  "organization_name": "string",
  "capabilities": {
    "property1": null,
    "property2": null
  },
  "metrics": {
    "property1": null,
    "property2": null
  },
  "public_jobs": {
    "property1": null,
    "property2": null
  }
}
```

<h3 id="plugins_repository_retrieve-responses">Responses</h3>

|Status|Meaning|Description|Schema|
|---|---|---|---|
|200|[OK](https://tools.ietf.org/html/rfc7231#section-6.3.1)|none|[Plugin](#schemaplugin)|

<aside class="success">
This operation does not require authentication
</aside>

<h1 id="-projects">projects</h1>

## list

<a id="opIdlist"></a>

> Code samples

```shell
# You can also use wget
curl -X GET /api/projects/ \
  -H 'Accept: application/json'

```

```http
GET /api/projects/ HTTP/1.1

Accept: application/json

```

```javascript

const headers = {
  'Accept':'application/json'
};

fetch('/api/projects/',
{
  method: 'GET',

  headers: headers
})
.then(function(res) {
    return res.json();
}).then(function(body) {
    console.log(body);
});

```

```ruby
require 'rest-client'
require 'json'

headers = {
  'Accept' => 'application/json'
}

result = RestClient.get '/api/projects/',
  params: {
  }, headers: headers

p JSON.parse(result)

```

```python
import requests
headers = {
  'Accept': 'application/json'
}

r = requests.get('/api/projects/', headers = headers)

print(r.json())

```

```php
<?php

require 'vendor/autoload.php';

$headers = array(
    'Accept' => 'application/json',
);

$client = new \GuzzleHttp\Client();

// Define array of request body.
$request_body = array();

try {
    $response = $client->request('GET','/api/projects/', array(
        'headers' => $headers,
        'json' => $request_body,
       )
    );
    print_r($response->getBody()->getContents());
 }
 catch (\GuzzleHttp\Exception\BadResponseException $e) {
    // handle exception or api errors.
    print_r($e->getMessage());
 }

 // ...

```

```java
URL obj = new URL("/api/projects/");
HttpURLConnection con = (HttpURLConnection) obj.openConnection();
con.setRequestMethod("GET");
int responseCode = con.getResponseCode();
BufferedReader in = new BufferedReader(
    new InputStreamReader(con.getInputStream()));
String inputLine;
StringBuffer response = new StringBuffer();
while ((inputLine = in.readLine()) != null) {
    response.append(inputLine);
}
in.close();
System.out.println(response.toString());

```

```go
package main

import (
       "bytes"
       "net/http"
)

func main() {

    headers := map[string][]string{
        "Accept": []string{"application/json"},
    }

    data := bytes.NewBuffer([]byte{jsonReq})
    req, err := http.NewRequest("GET", "/api/projects/", data)
    req.Header = headers

    client := &http.Client{}
    resp, err := client.Do(req)
    // ...
}

```

`GET /api/projects/`

Projects for the current organization.

<h3 id="list-parameters">Parameters</h3>

|Name|In|Type|Required|Description|
|---|---|---|---|---|
|limit|query|integer|false|Number of results to return per page.|
|offset|query|integer|false|The initial index from which to return the results.|

> Example responses

> 200 Response

```json
{
  "count": 123,
  "next": "http://api.example.org/accounts/?offset=400&limit=100",
  "previous": "http://api.example.org/accounts/?offset=200&limit=100",
  "results": [
    {
      "id": 0,
      "uuid": "095be615-a8ad-4c33-8e9c-c7612fbf6c9f",
      "organization": "452c1a86-a0af-475b-b03f-724878b0f387",
      "api_token": "stringstri",
      "name": "string",
      "completed_snippet_onboarding": true,
      "ingested_event": true,
      "is_demo": true,
      "timezone": "Africa/Abidjan",
      "access_control": true,
      "effective_membership_level": 1
    }
  ]
}
```

<h3 id="list-responses">Responses</h3>

|Status|Meaning|Description|Schema|
|---|---|---|---|
|200|[OK](https://tools.ietf.org/html/rfc7231#section-6.3.1)|none|[PaginatedTeamBasicList](#schemapaginatedteambasiclist)|

<aside class="success">
This operation does not require authentication
</aside>

## create

<a id="opIdcreate"></a>

> Code samples

```shell
# You can also use wget
curl -X POST /api/projects/ \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json'

```

```http
POST /api/projects/ HTTP/1.1

Content-Type: application/json
Accept: application/json

```

```javascript
const inputBody = '{
  "app_urls": [
    "string"
  ],
  "name": "string",
  "slack_incoming_webhook": "string",
  "anonymize_ips": true,
  "completed_snippet_onboarding": true,
  "test_account_filters": {
    "property1": null,
    "property2": null
  },
  "path_cleaning_filters": {
    "property1": null,
    "property2": null
  },
  "timezone": "Africa/Abidjan",
  "data_attributes": {
    "property1": null,
    "property2": null
  },
  "correlation_config": {
    "property1": null,
    "property2": null
  },
  "session_recording_opt_in": true,
  "access_control": true
}';
const headers = {
  'Content-Type':'application/json',
  'Accept':'application/json'
};

fetch('/api/projects/',
{
  method: 'POST',
  body: inputBody,
  headers: headers
})
.then(function(res) {
    return res.json();
}).then(function(body) {
    console.log(body);
});

```

```ruby
require 'rest-client'
require 'json'

headers = {
  'Content-Type' => 'application/json',
  'Accept' => 'application/json'
}

result = RestClient.post '/api/projects/',
  params: {
  }, headers: headers

p JSON.parse(result)

```

```python
import requests
headers = {
  'Content-Type': 'application/json',
  'Accept': 'application/json'
}

r = requests.post('/api/projects/', headers = headers)

print(r.json())

```

```php
<?php

require 'vendor/autoload.php';

$headers = array(
    'Content-Type' => 'application/json',
    'Accept' => 'application/json',
);

$client = new \GuzzleHttp\Client();

// Define array of request body.
$request_body = array();

try {
    $response = $client->request('POST','/api/projects/', array(
        'headers' => $headers,
        'json' => $request_body,
       )
    );
    print_r($response->getBody()->getContents());
 }
 catch (\GuzzleHttp\Exception\BadResponseException $e) {
    // handle exception or api errors.
    print_r($e->getMessage());
 }

 // ...

```

```java
URL obj = new URL("/api/projects/");
HttpURLConnection con = (HttpURLConnection) obj.openConnection();
con.setRequestMethod("POST");
int responseCode = con.getResponseCode();
BufferedReader in = new BufferedReader(
    new InputStreamReader(con.getInputStream()));
String inputLine;
StringBuffer response = new StringBuffer();
while ((inputLine = in.readLine()) != null) {
    response.append(inputLine);
}
in.close();
System.out.println(response.toString());

```

```go
package main

import (
       "bytes"
       "net/http"
)

func main() {

    headers := map[string][]string{
        "Content-Type": []string{"application/json"},
        "Accept": []string{"application/json"},
    }

    data := bytes.NewBuffer([]byte{jsonReq})
    req, err := http.NewRequest("POST", "/api/projects/", data)
    req.Header = headers

    client := &http.Client{}
    resp, err := client.Do(req)
    // ...
}

```

`POST /api/projects/`

Projects for the current organization.

> Body parameter

```json
{
  "app_urls": [
    "string"
  ],
  "name": "string",
  "slack_incoming_webhook": "string",
  "anonymize_ips": true,
  "completed_snippet_onboarding": true,
  "test_account_filters": {
    "property1": null,
    "property2": null
  },
  "path_cleaning_filters": {
    "property1": null,
    "property2": null
  },
  "timezone": "Africa/Abidjan",
  "data_attributes": {
    "property1": null,
    "property2": null
  },
  "correlation_config": {
    "property1": null,
    "property2": null
  },
  "session_recording_opt_in": true,
  "access_control": true
}
```

```yaml
app_urls:
  - string
name: string
slack_incoming_webhook: string
anonymize_ips: true
completed_snippet_onboarding: true
test_account_filters:
  ? property1
  ? property2
path_cleaning_filters:
  ? property1
  ? property2
timezone: Africa/Abidjan
data_attributes:
  ? property1
  ? property2
correlation_config:
  ? property1
  ? property2
session_recording_opt_in: true
access_control: true

```

<h3 id="create-parameters">Parameters</h3>

|Name|In|Type|Required|Description|
|---|---|---|---|---|
|body|body|[Team](#schemateam)|false|none|

> Example responses

> 201 Response

```json
{
  "id": 0,
  "uuid": "095be615-a8ad-4c33-8e9c-c7612fbf6c9f",
  "organization": "452c1a86-a0af-475b-b03f-724878b0f387",
  "api_token": "string",
  "app_urls": [
    "string"
  ],
  "name": "string",
  "slack_incoming_webhook": "string",
  "created_at": "2019-08-24T14:15:22Z",
  "updated_at": "2019-08-24T14:15:22Z",
  "anonymize_ips": true,
  "completed_snippet_onboarding": true,
  "ingested_event": true,
  "test_account_filters": {
    "property1": null,
    "property2": null
  },
  "path_cleaning_filters": {
    "property1": null,
    "property2": null
  },
  "is_demo": true,
  "timezone": "Africa/Abidjan",
  "data_attributes": {
    "property1": null,
    "property2": null
  },
  "correlation_config": {
    "property1": null,
    "property2": null
  },
  "session_recording_opt_in": true,
  "effective_membership_level": 1,
  "access_control": true,
  "has_group_types": true
}
```

<h3 id="create-responses">Responses</h3>

|Status|Meaning|Description|Schema|
|---|---|---|---|
|201|[Created](https://tools.ietf.org/html/rfc7231#section-6.3.2)|none|[Team](#schemateam)|

<aside class="success">
This operation does not require authentication
</aside>

## retrieve

<a id="opIdretrieve"></a>

> Code samples

```shell
# You can also use wget
curl -X GET /api/projects/{id}/ \
  -H 'Accept: application/json'

```

```http
GET /api/projects/{id}/ HTTP/1.1

Accept: application/json

```

```javascript

const headers = {
  'Accept':'application/json'
};

fetch('/api/projects/{id}/',
{
  method: 'GET',

  headers: headers
})
.then(function(res) {
    return res.json();
}).then(function(body) {
    console.log(body);
});

```

```ruby
require 'rest-client'
require 'json'

headers = {
  'Accept' => 'application/json'
}

result = RestClient.get '/api/projects/{id}/',
  params: {
  }, headers: headers

p JSON.parse(result)

```

```python
import requests
headers = {
  'Accept': 'application/json'
}

r = requests.get('/api/projects/{id}/', headers = headers)

print(r.json())

```

```php
<?php

require 'vendor/autoload.php';

$headers = array(
    'Accept' => 'application/json',
);

$client = new \GuzzleHttp\Client();

// Define array of request body.
$request_body = array();

try {
    $response = $client->request('GET','/api/projects/{id}/', array(
        'headers' => $headers,
        'json' => $request_body,
       )
    );
    print_r($response->getBody()->getContents());
 }
 catch (\GuzzleHttp\Exception\BadResponseException $e) {
    // handle exception or api errors.
    print_r($e->getMessage());
 }

 // ...

```

```java
URL obj = new URL("/api/projects/{id}/");
HttpURLConnection con = (HttpURLConnection) obj.openConnection();
con.setRequestMethod("GET");
int responseCode = con.getResponseCode();
BufferedReader in = new BufferedReader(
    new InputStreamReader(con.getInputStream()));
String inputLine;
StringBuffer response = new StringBuffer();
while ((inputLine = in.readLine()) != null) {
    response.append(inputLine);
}
in.close();
System.out.println(response.toString());

```

```go
package main

import (
       "bytes"
       "net/http"
)

func main() {

    headers := map[string][]string{
        "Accept": []string{"application/json"},
    }

    data := bytes.NewBuffer([]byte{jsonReq})
    req, err := http.NewRequest("GET", "/api/projects/{id}/", data)
    req.Header = headers

    client := &http.Client{}
    resp, err := client.Do(req)
    // ...
}

```

`GET /api/projects/{id}/`

Projects for the current organization.

<h3 id="retrieve-parameters">Parameters</h3>

|Name|In|Type|Required|Description|
|---|---|---|---|---|
|id|path|integer|true|A unique integer value identifying this team.|

> Example responses

> 200 Response

```json
{
  "id": 0,
  "uuid": "095be615-a8ad-4c33-8e9c-c7612fbf6c9f",
  "organization": "452c1a86-a0af-475b-b03f-724878b0f387",
  "api_token": "string",
  "app_urls": [
    "string"
  ],
  "name": "string",
  "slack_incoming_webhook": "string",
  "created_at": "2019-08-24T14:15:22Z",
  "updated_at": "2019-08-24T14:15:22Z",
  "anonymize_ips": true,
  "completed_snippet_onboarding": true,
  "ingested_event": true,
  "test_account_filters": {
    "property1": null,
    "property2": null
  },
  "path_cleaning_filters": {
    "property1": null,
    "property2": null
  },
  "is_demo": true,
  "timezone": "Africa/Abidjan",
  "data_attributes": {
    "property1": null,
    "property2": null
  },
  "correlation_config": {
    "property1": null,
    "property2": null
  },
  "session_recording_opt_in": true,
  "effective_membership_level": 1,
  "access_control": true,
  "has_group_types": true
}
```

<h3 id="retrieve-responses">Responses</h3>

|Status|Meaning|Description|Schema|
|---|---|---|---|
|200|[OK](https://tools.ietf.org/html/rfc7231#section-6.3.1)|none|[Team](#schemateam)|

<aside class="success">
This operation does not require authentication
</aside>

## update

<a id="opIdupdate"></a>

> Code samples

```shell
# You can also use wget
curl -X PUT /api/projects/{id}/ \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json'

```

```http
PUT /api/projects/{id}/ HTTP/1.1

Content-Type: application/json
Accept: application/json

```

```javascript
const inputBody = '{
  "app_urls": [
    "string"
  ],
  "name": "string",
  "slack_incoming_webhook": "string",
  "anonymize_ips": true,
  "completed_snippet_onboarding": true,
  "test_account_filters": {
    "property1": null,
    "property2": null
  },
  "path_cleaning_filters": {
    "property1": null,
    "property2": null
  },
  "timezone": "Africa/Abidjan",
  "data_attributes": {
    "property1": null,
    "property2": null
  },
  "correlation_config": {
    "property1": null,
    "property2": null
  },
  "session_recording_opt_in": true,
  "access_control": true
}';
const headers = {
  'Content-Type':'application/json',
  'Accept':'application/json'
};

fetch('/api/projects/{id}/',
{
  method: 'PUT',
  body: inputBody,
  headers: headers
})
.then(function(res) {
    return res.json();
}).then(function(body) {
    console.log(body);
});

```

```ruby
require 'rest-client'
require 'json'

headers = {
  'Content-Type' => 'application/json',
  'Accept' => 'application/json'
}

result = RestClient.put '/api/projects/{id}/',
  params: {
  }, headers: headers

p JSON.parse(result)

```

```python
import requests
headers = {
  'Content-Type': 'application/json',
  'Accept': 'application/json'
}

r = requests.put('/api/projects/{id}/', headers = headers)

print(r.json())

```

```php
<?php

require 'vendor/autoload.php';

$headers = array(
    'Content-Type' => 'application/json',
    'Accept' => 'application/json',
);

$client = new \GuzzleHttp\Client();

// Define array of request body.
$request_body = array();

try {
    $response = $client->request('PUT','/api/projects/{id}/', array(
        'headers' => $headers,
        'json' => $request_body,
       )
    );
    print_r($response->getBody()->getContents());
 }
 catch (\GuzzleHttp\Exception\BadResponseException $e) {
    // handle exception or api errors.
    print_r($e->getMessage());
 }

 // ...

```

```java
URL obj = new URL("/api/projects/{id}/");
HttpURLConnection con = (HttpURLConnection) obj.openConnection();
con.setRequestMethod("PUT");
int responseCode = con.getResponseCode();
BufferedReader in = new BufferedReader(
    new InputStreamReader(con.getInputStream()));
String inputLine;
StringBuffer response = new StringBuffer();
while ((inputLine = in.readLine()) != null) {
    response.append(inputLine);
}
in.close();
System.out.println(response.toString());

```

```go
package main

import (
       "bytes"
       "net/http"
)

func main() {

    headers := map[string][]string{
        "Content-Type": []string{"application/json"},
        "Accept": []string{"application/json"},
    }

    data := bytes.NewBuffer([]byte{jsonReq})
    req, err := http.NewRequest("PUT", "/api/projects/{id}/", data)
    req.Header = headers

    client := &http.Client{}
    resp, err := client.Do(req)
    // ...
}

```

`PUT /api/projects/{id}/`

Projects for the current organization.

> Body parameter

```json
{
  "app_urls": [
    "string"
  ],
  "name": "string",
  "slack_incoming_webhook": "string",
  "anonymize_ips": true,
  "completed_snippet_onboarding": true,
  "test_account_filters": {
    "property1": null,
    "property2": null
  },
  "path_cleaning_filters": {
    "property1": null,
    "property2": null
  },
  "timezone": "Africa/Abidjan",
  "data_attributes": {
    "property1": null,
    "property2": null
  },
  "correlation_config": {
    "property1": null,
    "property2": null
  },
  "session_recording_opt_in": true,
  "access_control": true
}
```

```yaml
app_urls:
  - string
name: string
slack_incoming_webhook: string
anonymize_ips: true
completed_snippet_onboarding: true
test_account_filters:
  ? property1
  ? property2
path_cleaning_filters:
  ? property1
  ? property2
timezone: Africa/Abidjan
data_attributes:
  ? property1
  ? property2
correlation_config:
  ? property1
  ? property2
session_recording_opt_in: true
access_control: true

```

<h3 id="update-parameters">Parameters</h3>

|Name|In|Type|Required|Description|
|---|---|---|---|---|
|id|path|integer|true|A unique integer value identifying this team.|
|body|body|[Team](#schemateam)|false|none|

> Example responses

> 200 Response

```json
{
  "id": 0,
  "uuid": "095be615-a8ad-4c33-8e9c-c7612fbf6c9f",
  "organization": "452c1a86-a0af-475b-b03f-724878b0f387",
  "api_token": "string",
  "app_urls": [
    "string"
  ],
  "name": "string",
  "slack_incoming_webhook": "string",
  "created_at": "2019-08-24T14:15:22Z",
  "updated_at": "2019-08-24T14:15:22Z",
  "anonymize_ips": true,
  "completed_snippet_onboarding": true,
  "ingested_event": true,
  "test_account_filters": {
    "property1": null,
    "property2": null
  },
  "path_cleaning_filters": {
    "property1": null,
    "property2": null
  },
  "is_demo": true,
  "timezone": "Africa/Abidjan",
  "data_attributes": {
    "property1": null,
    "property2": null
  },
  "correlation_config": {
    "property1": null,
    "property2": null
  },
  "session_recording_opt_in": true,
  "effective_membership_level": 1,
  "access_control": true,
  "has_group_types": true
}
```

<h3 id="update-responses">Responses</h3>

|Status|Meaning|Description|Schema|
|---|---|---|---|
|200|[OK](https://tools.ietf.org/html/rfc7231#section-6.3.1)|none|[Team](#schemateam)|

<aside class="success">
This operation does not require authentication
</aside>

## partial_update

<a id="opIdpartial_update"></a>

> Code samples

```shell
# You can also use wget
curl -X PATCH /api/projects/{id}/ \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json'

```

```http
PATCH /api/projects/{id}/ HTTP/1.1

Content-Type: application/json
Accept: application/json

```

```javascript
const inputBody = '{
  "app_urls": [
    "string"
  ],
  "name": "string",
  "slack_incoming_webhook": "string",
  "anonymize_ips": true,
  "completed_snippet_onboarding": true,
  "test_account_filters": {
    "property1": null,
    "property2": null
  },
  "path_cleaning_filters": {
    "property1": null,
    "property2": null
  },
  "timezone": "Africa/Abidjan",
  "data_attributes": {
    "property1": null,
    "property2": null
  },
  "correlation_config": {
    "property1": null,
    "property2": null
  },
  "session_recording_opt_in": true,
  "access_control": true
}';
const headers = {
  'Content-Type':'application/json',
  'Accept':'application/json'
};

fetch('/api/projects/{id}/',
{
  method: 'PATCH',
  body: inputBody,
  headers: headers
})
.then(function(res) {
    return res.json();
}).then(function(body) {
    console.log(body);
});

```

```ruby
require 'rest-client'
require 'json'

headers = {
  'Content-Type' => 'application/json',
  'Accept' => 'application/json'
}

result = RestClient.patch '/api/projects/{id}/',
  params: {
  }, headers: headers

p JSON.parse(result)

```

```python
import requests
headers = {
  'Content-Type': 'application/json',
  'Accept': 'application/json'
}

r = requests.patch('/api/projects/{id}/', headers = headers)

print(r.json())

```

```php
<?php

require 'vendor/autoload.php';

$headers = array(
    'Content-Type' => 'application/json',
    'Accept' => 'application/json',
);

$client = new \GuzzleHttp\Client();

// Define array of request body.
$request_body = array();

try {
    $response = $client->request('PATCH','/api/projects/{id}/', array(
        'headers' => $headers,
        'json' => $request_body,
       )
    );
    print_r($response->getBody()->getContents());
 }
 catch (\GuzzleHttp\Exception\BadResponseException $e) {
    // handle exception or api errors.
    print_r($e->getMessage());
 }

 // ...

```

```java
URL obj = new URL("/api/projects/{id}/");
HttpURLConnection con = (HttpURLConnection) obj.openConnection();
con.setRequestMethod("PATCH");
int responseCode = con.getResponseCode();
BufferedReader in = new BufferedReader(
    new InputStreamReader(con.getInputStream()));
String inputLine;
StringBuffer response = new StringBuffer();
while ((inputLine = in.readLine()) != null) {
    response.append(inputLine);
}
in.close();
System.out.println(response.toString());

```

```go
package main

import (
       "bytes"
       "net/http"
)

func main() {

    headers := map[string][]string{
        "Content-Type": []string{"application/json"},
        "Accept": []string{"application/json"},
    }

    data := bytes.NewBuffer([]byte{jsonReq})
    req, err := http.NewRequest("PATCH", "/api/projects/{id}/", data)
    req.Header = headers

    client := &http.Client{}
    resp, err := client.Do(req)
    // ...
}

```

`PATCH /api/projects/{id}/`

Projects for the current organization.

> Body parameter

```json
{
  "app_urls": [
    "string"
  ],
  "name": "string",
  "slack_incoming_webhook": "string",
  "anonymize_ips": true,
  "completed_snippet_onboarding": true,
  "test_account_filters": {
    "property1": null,
    "property2": null
  },
  "path_cleaning_filters": {
    "property1": null,
    "property2": null
  },
  "timezone": "Africa/Abidjan",
  "data_attributes": {
    "property1": null,
    "property2": null
  },
  "correlation_config": {
    "property1": null,
    "property2": null
  },
  "session_recording_opt_in": true,
  "access_control": true
}
```

```yaml
app_urls:
  - string
name: string
slack_incoming_webhook: string
anonymize_ips: true
completed_snippet_onboarding: true
test_account_filters:
  ? property1
  ? property2
path_cleaning_filters:
  ? property1
  ? property2
timezone: Africa/Abidjan
data_attributes:
  ? property1
  ? property2
correlation_config:
  ? property1
  ? property2
session_recording_opt_in: true
access_control: true

```

<h3 id="partial_update-parameters">Parameters</h3>

|Name|In|Type|Required|Description|
|---|---|---|---|---|
|id|path|integer|true|A unique integer value identifying this team.|
|body|body|[PatchedTeam](#schemapatchedteam)|false|none|

> Example responses

> 200 Response

```json
{
  "id": 0,
  "uuid": "095be615-a8ad-4c33-8e9c-c7612fbf6c9f",
  "organization": "452c1a86-a0af-475b-b03f-724878b0f387",
  "api_token": "string",
  "app_urls": [
    "string"
  ],
  "name": "string",
  "slack_incoming_webhook": "string",
  "created_at": "2019-08-24T14:15:22Z",
  "updated_at": "2019-08-24T14:15:22Z",
  "anonymize_ips": true,
  "completed_snippet_onboarding": true,
  "ingested_event": true,
  "test_account_filters": {
    "property1": null,
    "property2": null
  },
  "path_cleaning_filters": {
    "property1": null,
    "property2": null
  },
  "is_demo": true,
  "timezone": "Africa/Abidjan",
  "data_attributes": {
    "property1": null,
    "property2": null
  },
  "correlation_config": {
    "property1": null,
    "property2": null
  },
  "session_recording_opt_in": true,
  "effective_membership_level": 1,
  "access_control": true,
  "has_group_types": true
}
```

<h3 id="partial_update-responses">Responses</h3>

|Status|Meaning|Description|Schema|
|---|---|---|---|
|200|[OK](https://tools.ietf.org/html/rfc7231#section-6.3.1)|none|[Team](#schemateam)|

<aside class="success">
This operation does not require authentication
</aside>

## destroy

<a id="opIddestroy"></a>

> Code samples

```shell
# You can also use wget
curl -X DELETE /api/projects/{id}/

```

```http
DELETE /api/projects/{id}/ HTTP/1.1

```

```javascript

fetch('/api/projects/{id}/',
{
  method: 'DELETE'

})
.then(function(res) {
    return res.json();
}).then(function(body) {
    console.log(body);
});

```

```ruby
require 'rest-client'
require 'json'

result = RestClient.delete '/api/projects/{id}/',
  params: {
  }

p JSON.parse(result)

```

```python
import requests

r = requests.delete('/api/projects/{id}/')

print(r.json())

```

```php
<?php

require 'vendor/autoload.php';

$client = new \GuzzleHttp\Client();

// Define array of request body.
$request_body = array();

try {
    $response = $client->request('DELETE','/api/projects/{id}/', array(
        'headers' => $headers,
        'json' => $request_body,
       )
    );
    print_r($response->getBody()->getContents());
 }
 catch (\GuzzleHttp\Exception\BadResponseException $e) {
    // handle exception or api errors.
    print_r($e->getMessage());
 }

 // ...

```

```java
URL obj = new URL("/api/projects/{id}/");
HttpURLConnection con = (HttpURLConnection) obj.openConnection();
con.setRequestMethod("DELETE");
int responseCode = con.getResponseCode();
BufferedReader in = new BufferedReader(
    new InputStreamReader(con.getInputStream()));
String inputLine;
StringBuffer response = new StringBuffer();
while ((inputLine = in.readLine()) != null) {
    response.append(inputLine);
}
in.close();
System.out.println(response.toString());

```

```go
package main

import (
       "bytes"
       "net/http"
)

func main() {

    data := bytes.NewBuffer([]byte{jsonReq})
    req, err := http.NewRequest("DELETE", "/api/projects/{id}/", data)
    req.Header = headers

    client := &http.Client{}
    resp, err := client.Do(req)
    // ...
}

```

`DELETE /api/projects/{id}/`

Projects for the current organization.

<h3 id="destroy-parameters">Parameters</h3>

|Name|In|Type|Required|Description|
|---|---|---|---|---|
|id|path|integer|true|A unique integer value identifying this team.|

<h3 id="destroy-responses">Responses</h3>

|Status|Meaning|Description|Schema|
|---|---|---|---|
|204|[No Content](https://tools.ietf.org/html/rfc7231#section-6.3.5)|No response body|None|

<aside class="success">
This operation does not require authentication
</aside>

<h1 id="-reset_token">reset_token</h1>

## reset_token_partial_update

<a id="opIdreset_token_partial_update"></a>

> Code samples

```shell
# You can also use wget
curl -X PATCH /api/projects/{id}/reset_token/ \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json'

```

```http
PATCH /api/projects/{id}/reset_token/ HTTP/1.1

Content-Type: application/json
Accept: application/json

```

```javascript
const inputBody = '{
  "app_urls": [
    "string"
  ],
  "name": "string",
  "slack_incoming_webhook": "string",
  "anonymize_ips": true,
  "completed_snippet_onboarding": true,
  "test_account_filters": {
    "property1": null,
    "property2": null
  },
  "path_cleaning_filters": {
    "property1": null,
    "property2": null
  },
  "timezone": "Africa/Abidjan",
  "data_attributes": {
    "property1": null,
    "property2": null
  },
  "correlation_config": {
    "property1": null,
    "property2": null
  },
  "session_recording_opt_in": true,
  "access_control": true
}';
const headers = {
  'Content-Type':'application/json',
  'Accept':'application/json'
};

fetch('/api/projects/{id}/reset_token/',
{
  method: 'PATCH',
  body: inputBody,
  headers: headers
})
.then(function(res) {
    return res.json();
}).then(function(body) {
    console.log(body);
});

```

```ruby
require 'rest-client'
require 'json'

headers = {
  'Content-Type' => 'application/json',
  'Accept' => 'application/json'
}

result = RestClient.patch '/api/projects/{id}/reset_token/',
  params: {
  }, headers: headers

p JSON.parse(result)

```

```python
import requests
headers = {
  'Content-Type': 'application/json',
  'Accept': 'application/json'
}

r = requests.patch('/api/projects/{id}/reset_token/', headers = headers)

print(r.json())

```

```php
<?php

require 'vendor/autoload.php';

$headers = array(
    'Content-Type' => 'application/json',
    'Accept' => 'application/json',
);

$client = new \GuzzleHttp\Client();

// Define array of request body.
$request_body = array();

try {
    $response = $client->request('PATCH','/api/projects/{id}/reset_token/', array(
        'headers' => $headers,
        'json' => $request_body,
       )
    );
    print_r($response->getBody()->getContents());
 }
 catch (\GuzzleHttp\Exception\BadResponseException $e) {
    // handle exception or api errors.
    print_r($e->getMessage());
 }

 // ...

```

```java
URL obj = new URL("/api/projects/{id}/reset_token/");
HttpURLConnection con = (HttpURLConnection) obj.openConnection();
con.setRequestMethod("PATCH");
int responseCode = con.getResponseCode();
BufferedReader in = new BufferedReader(
    new InputStreamReader(con.getInputStream()));
String inputLine;
StringBuffer response = new StringBuffer();
while ((inputLine = in.readLine()) != null) {
    response.append(inputLine);
}
in.close();
System.out.println(response.toString());

```

```go
package main

import (
       "bytes"
       "net/http"
)

func main() {

    headers := map[string][]string{
        "Content-Type": []string{"application/json"},
        "Accept": []string{"application/json"},
    }

    data := bytes.NewBuffer([]byte{jsonReq})
    req, err := http.NewRequest("PATCH", "/api/projects/{id}/reset_token/", data)
    req.Header = headers

    client := &http.Client{}
    resp, err := client.Do(req)
    // ...
}

```

`PATCH /api/projects/{id}/reset_token/`

Projects for the current organization.

> Body parameter

```json
{
  "app_urls": [
    "string"
  ],
  "name": "string",
  "slack_incoming_webhook": "string",
  "anonymize_ips": true,
  "completed_snippet_onboarding": true,
  "test_account_filters": {
    "property1": null,
    "property2": null
  },
  "path_cleaning_filters": {
    "property1": null,
    "property2": null
  },
  "timezone": "Africa/Abidjan",
  "data_attributes": {
    "property1": null,
    "property2": null
  },
  "correlation_config": {
    "property1": null,
    "property2": null
  },
  "session_recording_opt_in": true,
  "access_control": true
}
```

```yaml
app_urls:
  - string
name: string
slack_incoming_webhook: string
anonymize_ips: true
completed_snippet_onboarding: true
test_account_filters:
  ? property1
  ? property2
path_cleaning_filters:
  ? property1
  ? property2
timezone: Africa/Abidjan
data_attributes:
  ? property1
  ? property2
correlation_config:
  ? property1
  ? property2
session_recording_opt_in: true
access_control: true

```

<h3 id="reset_token_partial_update-parameters">Parameters</h3>

|Name|In|Type|Required|Description|
|---|---|---|---|---|
|id|path|integer|true|A unique integer value identifying this team.|
|body|body|[PatchedTeam](#schemapatchedteam)|false|none|

> Example responses

> 200 Response

```json
{
  "id": 0,
  "uuid": "095be615-a8ad-4c33-8e9c-c7612fbf6c9f",
  "organization": "452c1a86-a0af-475b-b03f-724878b0f387",
  "api_token": "string",
  "app_urls": [
    "string"
  ],
  "name": "string",
  "slack_incoming_webhook": "string",
  "created_at": "2019-08-24T14:15:22Z",
  "updated_at": "2019-08-24T14:15:22Z",
  "anonymize_ips": true,
  "completed_snippet_onboarding": true,
  "ingested_event": true,
  "test_account_filters": {
    "property1": null,
    "property2": null
  },
  "path_cleaning_filters": {
    "property1": null,
    "property2": null
  },
  "is_demo": true,
  "timezone": "Africa/Abidjan",
  "data_attributes": {
    "property1": null,
    "property2": null
  },
  "correlation_config": {
    "property1": null,
    "property2": null
  },
  "session_recording_opt_in": true,
  "effective_membership_level": 1,
  "access_control": true,
  "has_group_types": true
}
```

<h3 id="reset_token_partial_update-responses">Responses</h3>

|Status|Meaning|Description|Schema|
|---|---|---|---|
|200|[OK](https://tools.ietf.org/html/rfc7231#section-6.3.1)|none|[Team](#schemateam)|

<aside class="success">
This operation does not require authentication
</aside>

<h1 id="-actions">actions</h1>

## actions_list

<a id="opIdactions_list"></a>

> Code samples

```shell
# You can also use wget
curl -X GET /api/projects/{project_id}/actions/ \
  -H 'Accept: application/json'

```

```http
GET /api/projects/{project_id}/actions/ HTTP/1.1

Accept: application/json

```

```javascript

const headers = {
  'Accept':'application/json'
};

fetch('/api/projects/{project_id}/actions/',
{
  method: 'GET',

  headers: headers
})
.then(function(res) {
    return res.json();
}).then(function(body) {
    console.log(body);
});

```

```ruby
require 'rest-client'
require 'json'

headers = {
  'Accept' => 'application/json'
}

result = RestClient.get '/api/projects/{project_id}/actions/',
  params: {
  }, headers: headers

p JSON.parse(result)

```

```python
import requests
headers = {
  'Accept': 'application/json'
}

r = requests.get('/api/projects/{project_id}/actions/', headers = headers)

print(r.json())

```

```php
<?php

require 'vendor/autoload.php';

$headers = array(
    'Accept' => 'application/json',
);

$client = new \GuzzleHttp\Client();

// Define array of request body.
$request_body = array();

try {
    $response = $client->request('GET','/api/projects/{project_id}/actions/', array(
        'headers' => $headers,
        'json' => $request_body,
       )
    );
    print_r($response->getBody()->getContents());
 }
 catch (\GuzzleHttp\Exception\BadResponseException $e) {
    // handle exception or api errors.
    print_r($e->getMessage());
 }

 // ...

```

```java
URL obj = new URL("/api/projects/{project_id}/actions/");
HttpURLConnection con = (HttpURLConnection) obj.openConnection();
con.setRequestMethod("GET");
int responseCode = con.getResponseCode();
BufferedReader in = new BufferedReader(
    new InputStreamReader(con.getInputStream()));
String inputLine;
StringBuffer response = new StringBuffer();
while ((inputLine = in.readLine()) != null) {
    response.append(inputLine);
}
in.close();
System.out.println(response.toString());

```

```go
package main

import (
       "bytes"
       "net/http"
)

func main() {

    headers := map[string][]string{
        "Accept": []string{"application/json"},
    }

    data := bytes.NewBuffer([]byte{jsonReq})
    req, err := http.NewRequest("GET", "/api/projects/{project_id}/actions/", data)
    req.Header = headers

    client := &http.Client{}
    resp, err := client.Do(req)
    // ...
}

```

`GET /api/projects/{project_id}/actions/`

<h3 id="actions_list-parameters">Parameters</h3>

|Name|In|Type|Required|Description|
|---|---|---|---|---|
|format|query|string|false|none|
|limit|query|integer|false|Number of results to return per page.|
|offset|query|integer|false|The initial index from which to return the results.|
|project_id|path|string|true|Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/.|

#### Enumerated Values

|Parameter|Value|
|---|---|
|format|csv|
|format|json|

> Example responses

> 200 Response

```json
{
  "count": 123,
  "next": "http://api.example.org/accounts/?offset=400&limit=100",
  "previous": "http://api.example.org/accounts/?offset=200&limit=100",
  "results": [
    {
      "id": 0,
      "name": "string",
      "post_to_slack": true,
      "slack_message_format": "string",
      "steps": [
        {
          "id": "string",
          "event": "string",
          "tag_name": "string",
          "text": "string",
          "href": "string",
          "selector": "string",
          "url": "string",
          "name": "string",
          "url_matching": "contains",
          "properties": {
            "property1": null,
            "property2": null
          }
        }
      ],
      "created_at": "2019-08-24T14:15:22Z",
      "deleted": true,
      "is_calculating": true,
      "last_calculated_at": "2019-08-24T14:15:22Z",
      "created_by": {
        "id": 0,
        "uuid": "095be615-a8ad-4c33-8e9c-c7612fbf6c9f",
        "distinct_id": "string",
        "first_name": "string",
        "email": "user@example.com"
      },
      "team_id": 0
    }
  ]
}
```

<h3 id="actions_list-responses">Responses</h3>

|Status|Meaning|Description|Schema|
|---|---|---|---|
|200|[OK](https://tools.ietf.org/html/rfc7231#section-6.3.1)|none|[PaginatedActionList](#schemapaginatedactionlist)|

<aside class="success">
This operation does not require authentication
</aside>

## actions_create

<a id="opIdactions_create"></a>

> Code samples

```shell
# You can also use wget
curl -X POST /api/projects/{project_id}/actions/ \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json'

```

```http
POST /api/projects/{project_id}/actions/ HTTP/1.1

Content-Type: application/json
Accept: application/json

```

```javascript
const inputBody = '{
  "name": "string",
  "post_to_slack": true,
  "slack_message_format": "string",
  "steps": [
    {
      "id": "string",
      "event": "string",
      "tag_name": "string",
      "text": "string",
      "href": "string",
      "selector": "string",
      "url": "string",
      "name": "string",
      "url_matching": "contains",
      "properties": {
        "property1": null,
        "property2": null
      }
    }
  ],
  "deleted": true,
  "last_calculated_at": "2019-08-24T14:15:22Z"
}';
const headers = {
  'Content-Type':'application/json',
  'Accept':'application/json'
};

fetch('/api/projects/{project_id}/actions/',
{
  method: 'POST',
  body: inputBody,
  headers: headers
})
.then(function(res) {
    return res.json();
}).then(function(body) {
    console.log(body);
});

```

```ruby
require 'rest-client'
require 'json'

headers = {
  'Content-Type' => 'application/json',
  'Accept' => 'application/json'
}

result = RestClient.post '/api/projects/{project_id}/actions/',
  params: {
  }, headers: headers

p JSON.parse(result)

```

```python
import requests
headers = {
  'Content-Type': 'application/json',
  'Accept': 'application/json'
}

r = requests.post('/api/projects/{project_id}/actions/', headers = headers)

print(r.json())

```

```php
<?php

require 'vendor/autoload.php';

$headers = array(
    'Content-Type' => 'application/json',
    'Accept' => 'application/json',
);

$client = new \GuzzleHttp\Client();

// Define array of request body.
$request_body = array();

try {
    $response = $client->request('POST','/api/projects/{project_id}/actions/', array(
        'headers' => $headers,
        'json' => $request_body,
       )
    );
    print_r($response->getBody()->getContents());
 }
 catch (\GuzzleHttp\Exception\BadResponseException $e) {
    // handle exception or api errors.
    print_r($e->getMessage());
 }

 // ...

```

```java
URL obj = new URL("/api/projects/{project_id}/actions/");
HttpURLConnection con = (HttpURLConnection) obj.openConnection();
con.setRequestMethod("POST");
int responseCode = con.getResponseCode();
BufferedReader in = new BufferedReader(
    new InputStreamReader(con.getInputStream()));
String inputLine;
StringBuffer response = new StringBuffer();
while ((inputLine = in.readLine()) != null) {
    response.append(inputLine);
}
in.close();
System.out.println(response.toString());

```

```go
package main

import (
       "bytes"
       "net/http"
)

func main() {

    headers := map[string][]string{
        "Content-Type": []string{"application/json"},
        "Accept": []string{"application/json"},
    }

    data := bytes.NewBuffer([]byte{jsonReq})
    req, err := http.NewRequest("POST", "/api/projects/{project_id}/actions/", data)
    req.Header = headers

    client := &http.Client{}
    resp, err := client.Do(req)
    // ...
}

```

`POST /api/projects/{project_id}/actions/`

> Body parameter

```json
{
  "name": "string",
  "post_to_slack": true,
  "slack_message_format": "string",
  "steps": [
    {
      "id": "string",
      "event": "string",
      "tag_name": "string",
      "text": "string",
      "href": "string",
      "selector": "string",
      "url": "string",
      "name": "string",
      "url_matching": "contains",
      "properties": {
        "property1": null,
        "property2": null
      }
    }
  ],
  "deleted": true,
  "last_calculated_at": "2019-08-24T14:15:22Z"
}
```

```yaml
name: string
post_to_slack: true
slack_message_format: string
steps:
  - id: string
    event: string
    tag_name: string
    text: string
    href: string
    selector: string
    url: string
    name: string
    url_matching: contains
    properties:
      ? property1
      ? property2
deleted: true
last_calculated_at: 2019-08-24T14:15:22Z

```

<h3 id="actions_create-parameters">Parameters</h3>

|Name|In|Type|Required|Description|
|---|---|---|---|---|
|format|query|string|false|none|
|project_id|path|string|true|Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/.|
|body|body|[Action](#schemaaction)|false|none|

#### Enumerated Values

|Parameter|Value|
|---|---|
|format|csv|
|format|json|

> Example responses

> 201 Response

```json
{
  "id": 0,
  "name": "string",
  "post_to_slack": true,
  "slack_message_format": "string",
  "steps": [
    {
      "id": "string",
      "event": "string",
      "tag_name": "string",
      "text": "string",
      "href": "string",
      "selector": "string",
      "url": "string",
      "name": "string",
      "url_matching": "contains",
      "properties": {
        "property1": null,
        "property2": null
      }
    }
  ],
  "created_at": "2019-08-24T14:15:22Z",
  "deleted": true,
  "is_calculating": true,
  "last_calculated_at": "2019-08-24T14:15:22Z",
  "created_by": {
    "id": 0,
    "uuid": "095be615-a8ad-4c33-8e9c-c7612fbf6c9f",
    "distinct_id": "string",
    "first_name": "string",
    "email": "user@example.com"
  },
  "team_id": 0
}
```

<h3 id="actions_create-responses">Responses</h3>

|Status|Meaning|Description|Schema|
|---|---|---|---|
|201|[Created](https://tools.ietf.org/html/rfc7231#section-6.3.2)|none|[Action](#schemaaction)|

<aside class="success">
This operation does not require authentication
</aside>

## actions_retrieve

<a id="opIdactions_retrieve"></a>

> Code samples

```shell
# You can also use wget
curl -X GET /api/projects/{project_id}/actions/{id}/ \
  -H 'Accept: application/json'

```

```http
GET /api/projects/{project_id}/actions/{id}/ HTTP/1.1

Accept: application/json

```

```javascript

const headers = {
  'Accept':'application/json'
};

fetch('/api/projects/{project_id}/actions/{id}/',
{
  method: 'GET',

  headers: headers
})
.then(function(res) {
    return res.json();
}).then(function(body) {
    console.log(body);
});

```

```ruby
require 'rest-client'
require 'json'

headers = {
  'Accept' => 'application/json'
}

result = RestClient.get '/api/projects/{project_id}/actions/{id}/',
  params: {
  }, headers: headers

p JSON.parse(result)

```

```python
import requests
headers = {
  'Accept': 'application/json'
}

r = requests.get('/api/projects/{project_id}/actions/{id}/', headers = headers)

print(r.json())

```

```php
<?php

require 'vendor/autoload.php';

$headers = array(
    'Accept' => 'application/json',
);

$client = new \GuzzleHttp\Client();

// Define array of request body.
$request_body = array();

try {
    $response = $client->request('GET','/api/projects/{project_id}/actions/{id}/', array(
        'headers' => $headers,
        'json' => $request_body,
       )
    );
    print_r($response->getBody()->getContents());
 }
 catch (\GuzzleHttp\Exception\BadResponseException $e) {
    // handle exception or api errors.
    print_r($e->getMessage());
 }

 // ...

```

```java
URL obj = new URL("/api/projects/{project_id}/actions/{id}/");
HttpURLConnection con = (HttpURLConnection) obj.openConnection();
con.setRequestMethod("GET");
int responseCode = con.getResponseCode();
BufferedReader in = new BufferedReader(
    new InputStreamReader(con.getInputStream()));
String inputLine;
StringBuffer response = new StringBuffer();
while ((inputLine = in.readLine()) != null) {
    response.append(inputLine);
}
in.close();
System.out.println(response.toString());

```

```go
package main

import (
       "bytes"
       "net/http"
)

func main() {

    headers := map[string][]string{
        "Accept": []string{"application/json"},
    }

    data := bytes.NewBuffer([]byte{jsonReq})
    req, err := http.NewRequest("GET", "/api/projects/{project_id}/actions/{id}/", data)
    req.Header = headers

    client := &http.Client{}
    resp, err := client.Do(req)
    // ...
}

```

`GET /api/projects/{project_id}/actions/{id}/`

<h3 id="actions_retrieve-parameters">Parameters</h3>

|Name|In|Type|Required|Description|
|---|---|---|---|---|
|format|query|string|false|none|
|id|path|integer|true|A unique integer value identifying this action.|
|project_id|path|string|true|Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/.|

#### Enumerated Values

|Parameter|Value|
|---|---|
|format|csv|
|format|json|

> Example responses

> 200 Response

```json
{
  "id": 0,
  "name": "string",
  "post_to_slack": true,
  "slack_message_format": "string",
  "steps": [
    {
      "id": "string",
      "event": "string",
      "tag_name": "string",
      "text": "string",
      "href": "string",
      "selector": "string",
      "url": "string",
      "name": "string",
      "url_matching": "contains",
      "properties": {
        "property1": null,
        "property2": null
      }
    }
  ],
  "created_at": "2019-08-24T14:15:22Z",
  "deleted": true,
  "is_calculating": true,
  "last_calculated_at": "2019-08-24T14:15:22Z",
  "created_by": {
    "id": 0,
    "uuid": "095be615-a8ad-4c33-8e9c-c7612fbf6c9f",
    "distinct_id": "string",
    "first_name": "string",
    "email": "user@example.com"
  },
  "team_id": 0
}
```

<h3 id="actions_retrieve-responses">Responses</h3>

|Status|Meaning|Description|Schema|
|---|---|---|---|
|200|[OK](https://tools.ietf.org/html/rfc7231#section-6.3.1)|none|[Action](#schemaaction)|

<aside class="success">
This operation does not require authentication
</aside>

## actions_update

<a id="opIdactions_update"></a>

> Code samples

```shell
# You can also use wget
curl -X PUT /api/projects/{project_id}/actions/{id}/ \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json'

```

```http
PUT /api/projects/{project_id}/actions/{id}/ HTTP/1.1

Content-Type: application/json
Accept: application/json

```

```javascript
const inputBody = '{
  "name": "string",
  "post_to_slack": true,
  "slack_message_format": "string",
  "steps": [
    {
      "id": "string",
      "event": "string",
      "tag_name": "string",
      "text": "string",
      "href": "string",
      "selector": "string",
      "url": "string",
      "name": "string",
      "url_matching": "contains",
      "properties": {
        "property1": null,
        "property2": null
      }
    }
  ],
  "deleted": true,
  "last_calculated_at": "2019-08-24T14:15:22Z"
}';
const headers = {
  'Content-Type':'application/json',
  'Accept':'application/json'
};

fetch('/api/projects/{project_id}/actions/{id}/',
{
  method: 'PUT',
  body: inputBody,
  headers: headers
})
.then(function(res) {
    return res.json();
}).then(function(body) {
    console.log(body);
});

```

```ruby
require 'rest-client'
require 'json'

headers = {
  'Content-Type' => 'application/json',
  'Accept' => 'application/json'
}

result = RestClient.put '/api/projects/{project_id}/actions/{id}/',
  params: {
  }, headers: headers

p JSON.parse(result)

```

```python
import requests
headers = {
  'Content-Type': 'application/json',
  'Accept': 'application/json'
}

r = requests.put('/api/projects/{project_id}/actions/{id}/', headers = headers)

print(r.json())

```

```php
<?php

require 'vendor/autoload.php';

$headers = array(
    'Content-Type' => 'application/json',
    'Accept' => 'application/json',
);

$client = new \GuzzleHttp\Client();

// Define array of request body.
$request_body = array();

try {
    $response = $client->request('PUT','/api/projects/{project_id}/actions/{id}/', array(
        'headers' => $headers,
        'json' => $request_body,
       )
    );
    print_r($response->getBody()->getContents());
 }
 catch (\GuzzleHttp\Exception\BadResponseException $e) {
    // handle exception or api errors.
    print_r($e->getMessage());
 }

 // ...

```

```java
URL obj = new URL("/api/projects/{project_id}/actions/{id}/");
HttpURLConnection con = (HttpURLConnection) obj.openConnection();
con.setRequestMethod("PUT");
int responseCode = con.getResponseCode();
BufferedReader in = new BufferedReader(
    new InputStreamReader(con.getInputStream()));
String inputLine;
StringBuffer response = new StringBuffer();
while ((inputLine = in.readLine()) != null) {
    response.append(inputLine);
}
in.close();
System.out.println(response.toString());

```

```go
package main

import (
       "bytes"
       "net/http"
)

func main() {

    headers := map[string][]string{
        "Content-Type": []string{"application/json"},
        "Accept": []string{"application/json"},
    }

    data := bytes.NewBuffer([]byte{jsonReq})
    req, err := http.NewRequest("PUT", "/api/projects/{project_id}/actions/{id}/", data)
    req.Header = headers

    client := &http.Client{}
    resp, err := client.Do(req)
    // ...
}

```

`PUT /api/projects/{project_id}/actions/{id}/`

> Body parameter

```json
{
  "name": "string",
  "post_to_slack": true,
  "slack_message_format": "string",
  "steps": [
    {
      "id": "string",
      "event": "string",
      "tag_name": "string",
      "text": "string",
      "href": "string",
      "selector": "string",
      "url": "string",
      "name": "string",
      "url_matching": "contains",
      "properties": {
        "property1": null,
        "property2": null
      }
    }
  ],
  "deleted": true,
  "last_calculated_at": "2019-08-24T14:15:22Z"
}
```

```yaml
name: string
post_to_slack: true
slack_message_format: string
steps:
  - id: string
    event: string
    tag_name: string
    text: string
    href: string
    selector: string
    url: string
    name: string
    url_matching: contains
    properties:
      ? property1
      ? property2
deleted: true
last_calculated_at: 2019-08-24T14:15:22Z

```

<h3 id="actions_update-parameters">Parameters</h3>

|Name|In|Type|Required|Description|
|---|---|---|---|---|
|format|query|string|false|none|
|id|path|integer|true|A unique integer value identifying this action.|
|project_id|path|string|true|Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/.|
|body|body|[Action](#schemaaction)|false|none|

#### Enumerated Values

|Parameter|Value|
|---|---|
|format|csv|
|format|json|

> Example responses

> 200 Response

```json
{
  "id": 0,
  "name": "string",
  "post_to_slack": true,
  "slack_message_format": "string",
  "steps": [
    {
      "id": "string",
      "event": "string",
      "tag_name": "string",
      "text": "string",
      "href": "string",
      "selector": "string",
      "url": "string",
      "name": "string",
      "url_matching": "contains",
      "properties": {
        "property1": null,
        "property2": null
      }
    }
  ],
  "created_at": "2019-08-24T14:15:22Z",
  "deleted": true,
  "is_calculating": true,
  "last_calculated_at": "2019-08-24T14:15:22Z",
  "created_by": {
    "id": 0,
    "uuid": "095be615-a8ad-4c33-8e9c-c7612fbf6c9f",
    "distinct_id": "string",
    "first_name": "string",
    "email": "user@example.com"
  },
  "team_id": 0
}
```

<h3 id="actions_update-responses">Responses</h3>

|Status|Meaning|Description|Schema|
|---|---|---|---|
|200|[OK](https://tools.ietf.org/html/rfc7231#section-6.3.1)|none|[Action](#schemaaction)|

<aside class="success">
This operation does not require authentication
</aside>

## actions_partial_update

<a id="opIdactions_partial_update"></a>

> Code samples

```shell
# You can also use wget
curl -X PATCH /api/projects/{project_id}/actions/{id}/ \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json'

```

```http
PATCH /api/projects/{project_id}/actions/{id}/ HTTP/1.1

Content-Type: application/json
Accept: application/json

```

```javascript
const inputBody = '{
  "name": "string",
  "post_to_slack": true,
  "slack_message_format": "string",
  "steps": [
    {
      "id": "string",
      "event": "string",
      "tag_name": "string",
      "text": "string",
      "href": "string",
      "selector": "string",
      "url": "string",
      "name": "string",
      "url_matching": "contains",
      "properties": {
        "property1": null,
        "property2": null
      }
    }
  ],
  "deleted": true,
  "last_calculated_at": "2019-08-24T14:15:22Z"
}';
const headers = {
  'Content-Type':'application/json',
  'Accept':'application/json'
};

fetch('/api/projects/{project_id}/actions/{id}/',
{
  method: 'PATCH',
  body: inputBody,
  headers: headers
})
.then(function(res) {
    return res.json();
}).then(function(body) {
    console.log(body);
});

```

```ruby
require 'rest-client'
require 'json'

headers = {
  'Content-Type' => 'application/json',
  'Accept' => 'application/json'
}

result = RestClient.patch '/api/projects/{project_id}/actions/{id}/',
  params: {
  }, headers: headers

p JSON.parse(result)

```

```python
import requests
headers = {
  'Content-Type': 'application/json',
  'Accept': 'application/json'
}

r = requests.patch('/api/projects/{project_id}/actions/{id}/', headers = headers)

print(r.json())

```

```php
<?php

require 'vendor/autoload.php';

$headers = array(
    'Content-Type' => 'application/json',
    'Accept' => 'application/json',
);

$client = new \GuzzleHttp\Client();

// Define array of request body.
$request_body = array();

try {
    $response = $client->request('PATCH','/api/projects/{project_id}/actions/{id}/', array(
        'headers' => $headers,
        'json' => $request_body,
       )
    );
    print_r($response->getBody()->getContents());
 }
 catch (\GuzzleHttp\Exception\BadResponseException $e) {
    // handle exception or api errors.
    print_r($e->getMessage());
 }

 // ...

```

```java
URL obj = new URL("/api/projects/{project_id}/actions/{id}/");
HttpURLConnection con = (HttpURLConnection) obj.openConnection();
con.setRequestMethod("PATCH");
int responseCode = con.getResponseCode();
BufferedReader in = new BufferedReader(
    new InputStreamReader(con.getInputStream()));
String inputLine;
StringBuffer response = new StringBuffer();
while ((inputLine = in.readLine()) != null) {
    response.append(inputLine);
}
in.close();
System.out.println(response.toString());

```

```go
package main

import (
       "bytes"
       "net/http"
)

func main() {

    headers := map[string][]string{
        "Content-Type": []string{"application/json"},
        "Accept": []string{"application/json"},
    }

    data := bytes.NewBuffer([]byte{jsonReq})
    req, err := http.NewRequest("PATCH", "/api/projects/{project_id}/actions/{id}/", data)
    req.Header = headers

    client := &http.Client{}
    resp, err := client.Do(req)
    // ...
}

```

`PATCH /api/projects/{project_id}/actions/{id}/`

> Body parameter

```json
{
  "name": "string",
  "post_to_slack": true,
  "slack_message_format": "string",
  "steps": [
    {
      "id": "string",
      "event": "string",
      "tag_name": "string",
      "text": "string",
      "href": "string",
      "selector": "string",
      "url": "string",
      "name": "string",
      "url_matching": "contains",
      "properties": {
        "property1": null,
        "property2": null
      }
    }
  ],
  "deleted": true,
  "last_calculated_at": "2019-08-24T14:15:22Z"
}
```

```yaml
name: string
post_to_slack: true
slack_message_format: string
steps:
  - id: string
    event: string
    tag_name: string
    text: string
    href: string
    selector: string
    url: string
    name: string
    url_matching: contains
    properties:
      ? property1
      ? property2
deleted: true
last_calculated_at: 2019-08-24T14:15:22Z

```

<h3 id="actions_partial_update-parameters">Parameters</h3>

|Name|In|Type|Required|Description|
|---|---|---|---|---|
|format|query|string|false|none|
|id|path|integer|true|A unique integer value identifying this action.|
|project_id|path|string|true|Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/.|
|body|body|[PatchedAction](#schemapatchedaction)|false|none|

#### Enumerated Values

|Parameter|Value|
|---|---|
|format|csv|
|format|json|

> Example responses

> 200 Response

```json
{
  "id": 0,
  "name": "string",
  "post_to_slack": true,
  "slack_message_format": "string",
  "steps": [
    {
      "id": "string",
      "event": "string",
      "tag_name": "string",
      "text": "string",
      "href": "string",
      "selector": "string",
      "url": "string",
      "name": "string",
      "url_matching": "contains",
      "properties": {
        "property1": null,
        "property2": null
      }
    }
  ],
  "created_at": "2019-08-24T14:15:22Z",
  "deleted": true,
  "is_calculating": true,
  "last_calculated_at": "2019-08-24T14:15:22Z",
  "created_by": {
    "id": 0,
    "uuid": "095be615-a8ad-4c33-8e9c-c7612fbf6c9f",
    "distinct_id": "string",
    "first_name": "string",
    "email": "user@example.com"
  },
  "team_id": 0
}
```

<h3 id="actions_partial_update-responses">Responses</h3>

|Status|Meaning|Description|Schema|
|---|---|---|---|
|200|[OK](https://tools.ietf.org/html/rfc7231#section-6.3.1)|none|[Action](#schemaaction)|

<aside class="success">
This operation does not require authentication
</aside>

## actions_destroy

<a id="opIdactions_destroy"></a>

> Code samples

```shell
# You can also use wget
curl -X DELETE /api/projects/{project_id}/actions/{id}/

```

```http
DELETE /api/projects/{project_id}/actions/{id}/ HTTP/1.1

```

```javascript

fetch('/api/projects/{project_id}/actions/{id}/',
{
  method: 'DELETE'

})
.then(function(res) {
    return res.json();
}).then(function(body) {
    console.log(body);
});

```

```ruby
require 'rest-client'
require 'json'

result = RestClient.delete '/api/projects/{project_id}/actions/{id}/',
  params: {
  }

p JSON.parse(result)

```

```python
import requests

r = requests.delete('/api/projects/{project_id}/actions/{id}/')

print(r.json())

```

```php
<?php

require 'vendor/autoload.php';

$client = new \GuzzleHttp\Client();

// Define array of request body.
$request_body = array();

try {
    $response = $client->request('DELETE','/api/projects/{project_id}/actions/{id}/', array(
        'headers' => $headers,
        'json' => $request_body,
       )
    );
    print_r($response->getBody()->getContents());
 }
 catch (\GuzzleHttp\Exception\BadResponseException $e) {
    // handle exception or api errors.
    print_r($e->getMessage());
 }

 // ...

```

```java
URL obj = new URL("/api/projects/{project_id}/actions/{id}/");
HttpURLConnection con = (HttpURLConnection) obj.openConnection();
con.setRequestMethod("DELETE");
int responseCode = con.getResponseCode();
BufferedReader in = new BufferedReader(
    new InputStreamReader(con.getInputStream()));
String inputLine;
StringBuffer response = new StringBuffer();
while ((inputLine = in.readLine()) != null) {
    response.append(inputLine);
}
in.close();
System.out.println(response.toString());

```

```go
package main

import (
       "bytes"
       "net/http"
)

func main() {

    data := bytes.NewBuffer([]byte{jsonReq})
    req, err := http.NewRequest("DELETE", "/api/projects/{project_id}/actions/{id}/", data)
    req.Header = headers

    client := &http.Client{}
    resp, err := client.Do(req)
    // ...
}

```

`DELETE /api/projects/{project_id}/actions/{id}/`

<h3 id="actions_destroy-parameters">Parameters</h3>

|Name|In|Type|Required|Description|
|---|---|---|---|---|
|format|query|string|false|none|
|id|path|integer|true|A unique integer value identifying this action.|
|project_id|path|string|true|Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/.|

#### Enumerated Values

|Parameter|Value|
|---|---|
|format|csv|
|format|json|

<h3 id="actions_destroy-responses">Responses</h3>

|Status|Meaning|Description|Schema|
|---|---|---|---|
|204|[No Content](https://tools.ietf.org/html/rfc7231#section-6.3.5)|No response body|None|

<aside class="success">
This operation does not require authentication
</aside>

## actions_count_retrieve

<a id="opIdactions_count_retrieve"></a>

> Code samples

```shell
# You can also use wget
curl -X GET /api/projects/{project_id}/actions/{id}/count/ \
  -H 'Accept: application/json'

```

```http
GET /api/projects/{project_id}/actions/{id}/count/ HTTP/1.1

Accept: application/json

```

```javascript

const headers = {
  'Accept':'application/json'
};

fetch('/api/projects/{project_id}/actions/{id}/count/',
{
  method: 'GET',

  headers: headers
})
.then(function(res) {
    return res.json();
}).then(function(body) {
    console.log(body);
});

```

```ruby
require 'rest-client'
require 'json'

headers = {
  'Accept' => 'application/json'
}

result = RestClient.get '/api/projects/{project_id}/actions/{id}/count/',
  params: {
  }, headers: headers

p JSON.parse(result)

```

```python
import requests
headers = {
  'Accept': 'application/json'
}

r = requests.get('/api/projects/{project_id}/actions/{id}/count/', headers = headers)

print(r.json())

```

```php
<?php

require 'vendor/autoload.php';

$headers = array(
    'Accept' => 'application/json',
);

$client = new \GuzzleHttp\Client();

// Define array of request body.
$request_body = array();

try {
    $response = $client->request('GET','/api/projects/{project_id}/actions/{id}/count/', array(
        'headers' => $headers,
        'json' => $request_body,
       )
    );
    print_r($response->getBody()->getContents());
 }
 catch (\GuzzleHttp\Exception\BadResponseException $e) {
    // handle exception or api errors.
    print_r($e->getMessage());
 }

 // ...

```

```java
URL obj = new URL("/api/projects/{project_id}/actions/{id}/count/");
HttpURLConnection con = (HttpURLConnection) obj.openConnection();
con.setRequestMethod("GET");
int responseCode = con.getResponseCode();
BufferedReader in = new BufferedReader(
    new InputStreamReader(con.getInputStream()));
String inputLine;
StringBuffer response = new StringBuffer();
while ((inputLine = in.readLine()) != null) {
    response.append(inputLine);
}
in.close();
System.out.println(response.toString());

```

```go
package main

import (
       "bytes"
       "net/http"
)

func main() {

    headers := map[string][]string{
        "Accept": []string{"application/json"},
    }

    data := bytes.NewBuffer([]byte{jsonReq})
    req, err := http.NewRequest("GET", "/api/projects/{project_id}/actions/{id}/count/", data)
    req.Header = headers

    client := &http.Client{}
    resp, err := client.Do(req)
    // ...
}

```

`GET /api/projects/{project_id}/actions/{id}/count/`

<h3 id="actions_count_retrieve-parameters">Parameters</h3>

|Name|In|Type|Required|Description|
|---|---|---|---|---|
|format|query|string|false|none|
|id|path|integer|true|A unique integer value identifying this action.|
|project_id|path|string|true|Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/.|

#### Enumerated Values

|Parameter|Value|
|---|---|
|format|csv|
|format|json|

> Example responses

> 200 Response

```json
{
  "id": 0,
  "name": "string",
  "post_to_slack": true,
  "slack_message_format": "string",
  "steps": [
    {
      "id": "string",
      "event": "string",
      "tag_name": "string",
      "text": "string",
      "href": "string",
      "selector": "string",
      "url": "string",
      "name": "string",
      "url_matching": "contains",
      "properties": {
        "property1": null,
        "property2": null
      }
    }
  ],
  "created_at": "2019-08-24T14:15:22Z",
  "deleted": true,
  "is_calculating": true,
  "last_calculated_at": "2019-08-24T14:15:22Z",
  "created_by": {
    "id": 0,
    "uuid": "095be615-a8ad-4c33-8e9c-c7612fbf6c9f",
    "distinct_id": "string",
    "first_name": "string",
    "email": "user@example.com"
  },
  "team_id": 0
}
```

<h3 id="actions_count_retrieve-responses">Responses</h3>

|Status|Meaning|Description|Schema|
|---|---|---|---|
|200|[OK](https://tools.ietf.org/html/rfc7231#section-6.3.1)|none|[Action](#schemaaction)|

<aside class="success">
This operation does not require authentication
</aside>

## actions_funnel_retrieve

<a id="opIdactions_funnel_retrieve"></a>

> Code samples

```shell
# You can also use wget
curl -X GET /api/projects/{project_id}/actions/funnel/ \
  -H 'Accept: application/json'

```

```http
GET /api/projects/{project_id}/actions/funnel/ HTTP/1.1

Accept: application/json

```

```javascript

const headers = {
  'Accept':'application/json'
};

fetch('/api/projects/{project_id}/actions/funnel/',
{
  method: 'GET',

  headers: headers
})
.then(function(res) {
    return res.json();
}).then(function(body) {
    console.log(body);
});

```

```ruby
require 'rest-client'
require 'json'

headers = {
  'Accept' => 'application/json'
}

result = RestClient.get '/api/projects/{project_id}/actions/funnel/',
  params: {
  }, headers: headers

p JSON.parse(result)

```

```python
import requests
headers = {
  'Accept': 'application/json'
}

r = requests.get('/api/projects/{project_id}/actions/funnel/', headers = headers)

print(r.json())

```

```php
<?php

require 'vendor/autoload.php';

$headers = array(
    'Accept' => 'application/json',
);

$client = new \GuzzleHttp\Client();

// Define array of request body.
$request_body = array();

try {
    $response = $client->request('GET','/api/projects/{project_id}/actions/funnel/', array(
        'headers' => $headers,
        'json' => $request_body,
       )
    );
    print_r($response->getBody()->getContents());
 }
 catch (\GuzzleHttp\Exception\BadResponseException $e) {
    // handle exception or api errors.
    print_r($e->getMessage());
 }

 // ...

```

```java
URL obj = new URL("/api/projects/{project_id}/actions/funnel/");
HttpURLConnection con = (HttpURLConnection) obj.openConnection();
con.setRequestMethod("GET");
int responseCode = con.getResponseCode();
BufferedReader in = new BufferedReader(
    new InputStreamReader(con.getInputStream()));
String inputLine;
StringBuffer response = new StringBuffer();
while ((inputLine = in.readLine()) != null) {
    response.append(inputLine);
}
in.close();
System.out.println(response.toString());

```

```go
package main

import (
       "bytes"
       "net/http"
)

func main() {

    headers := map[string][]string{
        "Accept": []string{"application/json"},
    }

    data := bytes.NewBuffer([]byte{jsonReq})
    req, err := http.NewRequest("GET", "/api/projects/{project_id}/actions/funnel/", data)
    req.Header = headers

    client := &http.Client{}
    resp, err := client.Do(req)
    // ...
}

```

`GET /api/projects/{project_id}/actions/funnel/`

<h3 id="actions_funnel_retrieve-parameters">Parameters</h3>

|Name|In|Type|Required|Description|
|---|---|---|---|---|
|format|query|string|false|none|
|project_id|path|string|true|Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/.|

#### Enumerated Values

|Parameter|Value|
|---|---|
|format|csv|
|format|json|

> Example responses

> 200 Response

```json
{
  "id": 0,
  "name": "string",
  "post_to_slack": true,
  "slack_message_format": "string",
  "steps": [
    {
      "id": "string",
      "event": "string",
      "tag_name": "string",
      "text": "string",
      "href": "string",
      "selector": "string",
      "url": "string",
      "name": "string",
      "url_matching": "contains",
      "properties": {
        "property1": null,
        "property2": null
      }
    }
  ],
  "created_at": "2019-08-24T14:15:22Z",
  "deleted": true,
  "is_calculating": true,
  "last_calculated_at": "2019-08-24T14:15:22Z",
  "created_by": {
    "id": 0,
    "uuid": "095be615-a8ad-4c33-8e9c-c7612fbf6c9f",
    "distinct_id": "string",
    "first_name": "string",
    "email": "user@example.com"
  },
  "team_id": 0
}
```

<h3 id="actions_funnel_retrieve-responses">Responses</h3>

|Status|Meaning|Description|Schema|
|---|---|---|---|
|200|[OK](https://tools.ietf.org/html/rfc7231#section-6.3.1)|none|[Action](#schemaaction)|

<aside class="success">
This operation does not require authentication
</aside>

## actions_people_retrieve

<a id="opIdactions_people_retrieve"></a>

> Code samples

```shell
# You can also use wget
curl -X GET /api/projects/{project_id}/actions/people/ \
  -H 'Accept: application/json'

```

```http
GET /api/projects/{project_id}/actions/people/ HTTP/1.1

Accept: application/json

```

```javascript

const headers = {
  'Accept':'application/json'
};

fetch('/api/projects/{project_id}/actions/people/',
{
  method: 'GET',

  headers: headers
})
.then(function(res) {
    return res.json();
}).then(function(body) {
    console.log(body);
});

```

```ruby
require 'rest-client'
require 'json'

headers = {
  'Accept' => 'application/json'
}

result = RestClient.get '/api/projects/{project_id}/actions/people/',
  params: {
  }, headers: headers

p JSON.parse(result)

```

```python
import requests
headers = {
  'Accept': 'application/json'
}

r = requests.get('/api/projects/{project_id}/actions/people/', headers = headers)

print(r.json())

```

```php
<?php

require 'vendor/autoload.php';

$headers = array(
    'Accept' => 'application/json',
);

$client = new \GuzzleHttp\Client();

// Define array of request body.
$request_body = array();

try {
    $response = $client->request('GET','/api/projects/{project_id}/actions/people/', array(
        'headers' => $headers,
        'json' => $request_body,
       )
    );
    print_r($response->getBody()->getContents());
 }
 catch (\GuzzleHttp\Exception\BadResponseException $e) {
    // handle exception or api errors.
    print_r($e->getMessage());
 }

 // ...

```

```java
URL obj = new URL("/api/projects/{project_id}/actions/people/");
HttpURLConnection con = (HttpURLConnection) obj.openConnection();
con.setRequestMethod("GET");
int responseCode = con.getResponseCode();
BufferedReader in = new BufferedReader(
    new InputStreamReader(con.getInputStream()));
String inputLine;
StringBuffer response = new StringBuffer();
while ((inputLine = in.readLine()) != null) {
    response.append(inputLine);
}
in.close();
System.out.println(response.toString());

```

```go
package main

import (
       "bytes"
       "net/http"
)

func main() {

    headers := map[string][]string{
        "Accept": []string{"application/json"},
    }

    data := bytes.NewBuffer([]byte{jsonReq})
    req, err := http.NewRequest("GET", "/api/projects/{project_id}/actions/people/", data)
    req.Header = headers

    client := &http.Client{}
    resp, err := client.Do(req)
    // ...
}

```

`GET /api/projects/{project_id}/actions/people/`

<h3 id="actions_people_retrieve-parameters">Parameters</h3>

|Name|In|Type|Required|Description|
|---|---|---|---|---|
|format|query|string|false|none|
|project_id|path|string|true|Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/.|

#### Enumerated Values

|Parameter|Value|
|---|---|
|format|csv|
|format|json|

> Example responses

> 200 Response

```json
{
  "id": 0,
  "name": "string",
  "post_to_slack": true,
  "slack_message_format": "string",
  "steps": [
    {
      "id": "string",
      "event": "string",
      "tag_name": "string",
      "text": "string",
      "href": "string",
      "selector": "string",
      "url": "string",
      "name": "string",
      "url_matching": "contains",
      "properties": {
        "property1": null,
        "property2": null
      }
    }
  ],
  "created_at": "2019-08-24T14:15:22Z",
  "deleted": true,
  "is_calculating": true,
  "last_calculated_at": "2019-08-24T14:15:22Z",
  "created_by": {
    "id": 0,
    "uuid": "095be615-a8ad-4c33-8e9c-c7612fbf6c9f",
    "distinct_id": "string",
    "first_name": "string",
    "email": "user@example.com"
  },
  "team_id": 0
}
```

<h3 id="actions_people_retrieve-responses">Responses</h3>

|Status|Meaning|Description|Schema|
|---|---|---|---|
|200|[OK](https://tools.ietf.org/html/rfc7231#section-6.3.1)|none|[Action](#schemaaction)|

<aside class="success">
This operation does not require authentication
</aside>

## actions_retention_retrieve

<a id="opIdactions_retention_retrieve"></a>

> Code samples

```shell
# You can also use wget
curl -X GET /api/projects/{project_id}/actions/retention/ \
  -H 'Accept: application/json'

```

```http
GET /api/projects/{project_id}/actions/retention/ HTTP/1.1

Accept: application/json

```

```javascript

const headers = {
  'Accept':'application/json'
};

fetch('/api/projects/{project_id}/actions/retention/',
{
  method: 'GET',

  headers: headers
})
.then(function(res) {
    return res.json();
}).then(function(body) {
    console.log(body);
});

```

```ruby
require 'rest-client'
require 'json'

headers = {
  'Accept' => 'application/json'
}

result = RestClient.get '/api/projects/{project_id}/actions/retention/',
  params: {
  }, headers: headers

p JSON.parse(result)

```

```python
import requests
headers = {
  'Accept': 'application/json'
}

r = requests.get('/api/projects/{project_id}/actions/retention/', headers = headers)

print(r.json())

```

```php
<?php

require 'vendor/autoload.php';

$headers = array(
    'Accept' => 'application/json',
);

$client = new \GuzzleHttp\Client();

// Define array of request body.
$request_body = array();

try {
    $response = $client->request('GET','/api/projects/{project_id}/actions/retention/', array(
        'headers' => $headers,
        'json' => $request_body,
       )
    );
    print_r($response->getBody()->getContents());
 }
 catch (\GuzzleHttp\Exception\BadResponseException $e) {
    // handle exception or api errors.
    print_r($e->getMessage());
 }

 // ...

```

```java
URL obj = new URL("/api/projects/{project_id}/actions/retention/");
HttpURLConnection con = (HttpURLConnection) obj.openConnection();
con.setRequestMethod("GET");
int responseCode = con.getResponseCode();
BufferedReader in = new BufferedReader(
    new InputStreamReader(con.getInputStream()));
String inputLine;
StringBuffer response = new StringBuffer();
while ((inputLine = in.readLine()) != null) {
    response.append(inputLine);
}
in.close();
System.out.println(response.toString());

```

```go
package main

import (
       "bytes"
       "net/http"
)

func main() {

    headers := map[string][]string{
        "Accept": []string{"application/json"},
    }

    data := bytes.NewBuffer([]byte{jsonReq})
    req, err := http.NewRequest("GET", "/api/projects/{project_id}/actions/retention/", data)
    req.Header = headers

    client := &http.Client{}
    resp, err := client.Do(req)
    // ...
}

```

`GET /api/projects/{project_id}/actions/retention/`

<h3 id="actions_retention_retrieve-parameters">Parameters</h3>

|Name|In|Type|Required|Description|
|---|---|---|---|---|
|format|query|string|false|none|
|project_id|path|string|true|Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/.|

#### Enumerated Values

|Parameter|Value|
|---|---|
|format|csv|
|format|json|

> Example responses

> 200 Response

```json
{
  "id": 0,
  "name": "string",
  "post_to_slack": true,
  "slack_message_format": "string",
  "steps": [
    {
      "id": "string",
      "event": "string",
      "tag_name": "string",
      "text": "string",
      "href": "string",
      "selector": "string",
      "url": "string",
      "name": "string",
      "url_matching": "contains",
      "properties": {
        "property1": null,
        "property2": null
      }
    }
  ],
  "created_at": "2019-08-24T14:15:22Z",
  "deleted": true,
  "is_calculating": true,
  "last_calculated_at": "2019-08-24T14:15:22Z",
  "created_by": {
    "id": 0,
    "uuid": "095be615-a8ad-4c33-8e9c-c7612fbf6c9f",
    "distinct_id": "string",
    "first_name": "string",
    "email": "user@example.com"
  },
  "team_id": 0
}
```

<h3 id="actions_retention_retrieve-responses">Responses</h3>

|Status|Meaning|Description|Schema|
|---|---|---|---|
|200|[OK](https://tools.ietf.org/html/rfc7231#section-6.3.1)|none|[Action](#schemaaction)|

<aside class="success">
This operation does not require authentication
</aside>

## actions_trends_retrieve

<a id="opIdactions_trends_retrieve"></a>

> Code samples

```shell
# You can also use wget
curl -X GET /api/projects/{project_id}/actions/trends/ \
  -H 'Accept: application/json'

```

```http
GET /api/projects/{project_id}/actions/trends/ HTTP/1.1

Accept: application/json

```

```javascript

const headers = {
  'Accept':'application/json'
};

fetch('/api/projects/{project_id}/actions/trends/',
{
  method: 'GET',

  headers: headers
})
.then(function(res) {
    return res.json();
}).then(function(body) {
    console.log(body);
});

```

```ruby
require 'rest-client'
require 'json'

headers = {
  'Accept' => 'application/json'
}

result = RestClient.get '/api/projects/{project_id}/actions/trends/',
  params: {
  }, headers: headers

p JSON.parse(result)

```

```python
import requests
headers = {
  'Accept': 'application/json'
}

r = requests.get('/api/projects/{project_id}/actions/trends/', headers = headers)

print(r.json())

```

```php
<?php

require 'vendor/autoload.php';

$headers = array(
    'Accept' => 'application/json',
);

$client = new \GuzzleHttp\Client();

// Define array of request body.
$request_body = array();

try {
    $response = $client->request('GET','/api/projects/{project_id}/actions/trends/', array(
        'headers' => $headers,
        'json' => $request_body,
       )
    );
    print_r($response->getBody()->getContents());
 }
 catch (\GuzzleHttp\Exception\BadResponseException $e) {
    // handle exception or api errors.
    print_r($e->getMessage());
 }

 // ...

```

```java
URL obj = new URL("/api/projects/{project_id}/actions/trends/");
HttpURLConnection con = (HttpURLConnection) obj.openConnection();
con.setRequestMethod("GET");
int responseCode = con.getResponseCode();
BufferedReader in = new BufferedReader(
    new InputStreamReader(con.getInputStream()));
String inputLine;
StringBuffer response = new StringBuffer();
while ((inputLine = in.readLine()) != null) {
    response.append(inputLine);
}
in.close();
System.out.println(response.toString());

```

```go
package main

import (
       "bytes"
       "net/http"
)

func main() {

    headers := map[string][]string{
        "Accept": []string{"application/json"},
    }

    data := bytes.NewBuffer([]byte{jsonReq})
    req, err := http.NewRequest("GET", "/api/projects/{project_id}/actions/trends/", data)
    req.Header = headers

    client := &http.Client{}
    resp, err := client.Do(req)
    // ...
}

```

`GET /api/projects/{project_id}/actions/trends/`

<h3 id="actions_trends_retrieve-parameters">Parameters</h3>

|Name|In|Type|Required|Description|
|---|---|---|---|---|
|format|query|string|false|none|
|project_id|path|string|true|Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/.|

#### Enumerated Values

|Parameter|Value|
|---|---|
|format|csv|
|format|json|

> Example responses

> 200 Response

```json
{
  "id": 0,
  "name": "string",
  "post_to_slack": true,
  "slack_message_format": "string",
  "steps": [
    {
      "id": "string",
      "event": "string",
      "tag_name": "string",
      "text": "string",
      "href": "string",
      "selector": "string",
      "url": "string",
      "name": "string",
      "url_matching": "contains",
      "properties": {
        "property1": null,
        "property2": null
      }
    }
  ],
  "created_at": "2019-08-24T14:15:22Z",
  "deleted": true,
  "is_calculating": true,
  "last_calculated_at": "2019-08-24T14:15:22Z",
  "created_by": {
    "id": 0,
    "uuid": "095be615-a8ad-4c33-8e9c-c7612fbf6c9f",
    "distinct_id": "string",
    "first_name": "string",
    "email": "user@example.com"
  },
  "team_id": 0
}
```

<h3 id="actions_trends_retrieve-responses">Responses</h3>

|Status|Meaning|Description|Schema|
|---|---|---|---|
|200|[OK](https://tools.ietf.org/html/rfc7231#section-6.3.1)|none|[Action](#schemaaction)|

<aside class="success">
This operation does not require authentication
</aside>

<h1 id="-annotations">annotations</h1>

## annotations_list

<a id="opIdannotations_list"></a>

> Code samples

```shell
# You can also use wget
curl -X GET /api/projects/{project_id}/annotations/ \
  -H 'Accept: application/json'

```

```http
GET /api/projects/{project_id}/annotations/ HTTP/1.1

Accept: application/json

```

```javascript

const headers = {
  'Accept':'application/json'
};

fetch('/api/projects/{project_id}/annotations/',
{
  method: 'GET',

  headers: headers
})
.then(function(res) {
    return res.json();
}).then(function(body) {
    console.log(body);
});

```

```ruby
require 'rest-client'
require 'json'

headers = {
  'Accept' => 'application/json'
}

result = RestClient.get '/api/projects/{project_id}/annotations/',
  params: {
  }, headers: headers

p JSON.parse(result)

```

```python
import requests
headers = {
  'Accept': 'application/json'
}

r = requests.get('/api/projects/{project_id}/annotations/', headers = headers)

print(r.json())

```

```php
<?php

require 'vendor/autoload.php';

$headers = array(
    'Accept' => 'application/json',
);

$client = new \GuzzleHttp\Client();

// Define array of request body.
$request_body = array();

try {
    $response = $client->request('GET','/api/projects/{project_id}/annotations/', array(
        'headers' => $headers,
        'json' => $request_body,
       )
    );
    print_r($response->getBody()->getContents());
 }
 catch (\GuzzleHttp\Exception\BadResponseException $e) {
    // handle exception or api errors.
    print_r($e->getMessage());
 }

 // ...

```

```java
URL obj = new URL("/api/projects/{project_id}/annotations/");
HttpURLConnection con = (HttpURLConnection) obj.openConnection();
con.setRequestMethod("GET");
int responseCode = con.getResponseCode();
BufferedReader in = new BufferedReader(
    new InputStreamReader(con.getInputStream()));
String inputLine;
StringBuffer response = new StringBuffer();
while ((inputLine = in.readLine()) != null) {
    response.append(inputLine);
}
in.close();
System.out.println(response.toString());

```

```go
package main

import (
       "bytes"
       "net/http"
)

func main() {

    headers := map[string][]string{
        "Accept": []string{"application/json"},
    }

    data := bytes.NewBuffer([]byte{jsonReq})
    req, err := http.NewRequest("GET", "/api/projects/{project_id}/annotations/", data)
    req.Header = headers

    client := &http.Client{}
    resp, err := client.Do(req)
    // ...
}

```

`GET /api/projects/{project_id}/annotations/`

Create, Read, Update and Delete annotations. [See docs](https://posthog.com/docs/user-guides/annotations) for more information on annotations.

<h3 id="annotations_list-parameters">Parameters</h3>

|Name|In|Type|Required|Description|
|---|---|---|---|---|
|limit|query|integer|false|Number of results to return per page.|
|offset|query|integer|false|The initial index from which to return the results.|
|project_id|path|string|true|Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/.|

> Example responses

> 200 Response

```json
{
  "count": 123,
  "next": "http://api.example.org/accounts/?offset=400&limit=100",
  "previous": "http://api.example.org/accounts/?offset=200&limit=100",
  "results": [
    {
      "id": 0,
      "content": "string",
      "date_marker": "2019-08-24T14:15:22Z",
      "creation_type": "USR",
      "dashboard_item": 0,
      "created_by": {
        "id": 0,
        "uuid": "095be615-a8ad-4c33-8e9c-c7612fbf6c9f",
        "distinct_id": "string",
        "first_name": "string",
        "email": "user@example.com"
      },
      "created_at": "2019-08-24T14:15:22Z",
      "updated_at": "2019-08-24T14:15:22Z",
      "deleted": true,
      "scope": "dashboard_item"
    }
  ]
}
```

<h3 id="annotations_list-responses">Responses</h3>

|Status|Meaning|Description|Schema|
|---|---|---|---|
|200|[OK](https://tools.ietf.org/html/rfc7231#section-6.3.1)|none|[PaginatedAnnotationList](#schemapaginatedannotationlist)|

<aside class="success">
This operation does not require authentication
</aside>

## annotations_create

<a id="opIdannotations_create"></a>

> Code samples

```shell
# You can also use wget
curl -X POST /api/projects/{project_id}/annotations/ \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json'

```

```http
POST /api/projects/{project_id}/annotations/ HTTP/1.1

Content-Type: application/json
Accept: application/json

```

```javascript
const inputBody = '{
  "content": "string",
  "date_marker": "2019-08-24T14:15:22Z",
  "dashboard_item": 0,
  "deleted": true,
  "scope": "dashboard_item"
}';
const headers = {
  'Content-Type':'application/json',
  'Accept':'application/json'
};

fetch('/api/projects/{project_id}/annotations/',
{
  method: 'POST',
  body: inputBody,
  headers: headers
})
.then(function(res) {
    return res.json();
}).then(function(body) {
    console.log(body);
});

```

```ruby
require 'rest-client'
require 'json'

headers = {
  'Content-Type' => 'application/json',
  'Accept' => 'application/json'
}

result = RestClient.post '/api/projects/{project_id}/annotations/',
  params: {
  }, headers: headers

p JSON.parse(result)

```

```python
import requests
headers = {
  'Content-Type': 'application/json',
  'Accept': 'application/json'
}

r = requests.post('/api/projects/{project_id}/annotations/', headers = headers)

print(r.json())

```

```php
<?php

require 'vendor/autoload.php';

$headers = array(
    'Content-Type' => 'application/json',
    'Accept' => 'application/json',
);

$client = new \GuzzleHttp\Client();

// Define array of request body.
$request_body = array();

try {
    $response = $client->request('POST','/api/projects/{project_id}/annotations/', array(
        'headers' => $headers,
        'json' => $request_body,
       )
    );
    print_r($response->getBody()->getContents());
 }
 catch (\GuzzleHttp\Exception\BadResponseException $e) {
    // handle exception or api errors.
    print_r($e->getMessage());
 }

 // ...

```

```java
URL obj = new URL("/api/projects/{project_id}/annotations/");
HttpURLConnection con = (HttpURLConnection) obj.openConnection();
con.setRequestMethod("POST");
int responseCode = con.getResponseCode();
BufferedReader in = new BufferedReader(
    new InputStreamReader(con.getInputStream()));
String inputLine;
StringBuffer response = new StringBuffer();
while ((inputLine = in.readLine()) != null) {
    response.append(inputLine);
}
in.close();
System.out.println(response.toString());

```

```go
package main

import (
       "bytes"
       "net/http"
)

func main() {

    headers := map[string][]string{
        "Content-Type": []string{"application/json"},
        "Accept": []string{"application/json"},
    }

    data := bytes.NewBuffer([]byte{jsonReq})
    req, err := http.NewRequest("POST", "/api/projects/{project_id}/annotations/", data)
    req.Header = headers

    client := &http.Client{}
    resp, err := client.Do(req)
    // ...
}

```

`POST /api/projects/{project_id}/annotations/`

Create, Read, Update and Delete annotations. [See docs](https://posthog.com/docs/user-guides/annotations) for more information on annotations.

> Body parameter

```json
{
  "content": "string",
  "date_marker": "2019-08-24T14:15:22Z",
  "dashboard_item": 0,
  "deleted": true,
  "scope": "dashboard_item"
}
```

```yaml
content: string
date_marker: 2019-08-24T14:15:22Z
dashboard_item: 0
deleted: true
scope: dashboard_item

```

<h3 id="annotations_create-parameters">Parameters</h3>

|Name|In|Type|Required|Description|
|---|---|---|---|---|
|project_id|path|string|true|Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/.|
|body|body|[Annotation](#schemaannotation)|false|none|

> Example responses

> 201 Response

```json
{
  "id": 0,
  "content": "string",
  "date_marker": "2019-08-24T14:15:22Z",
  "creation_type": "USR",
  "dashboard_item": 0,
  "created_by": {
    "id": 0,
    "uuid": "095be615-a8ad-4c33-8e9c-c7612fbf6c9f",
    "distinct_id": "string",
    "first_name": "string",
    "email": "user@example.com"
  },
  "created_at": "2019-08-24T14:15:22Z",
  "updated_at": "2019-08-24T14:15:22Z",
  "deleted": true,
  "scope": "dashboard_item"
}
```

<h3 id="annotations_create-responses">Responses</h3>

|Status|Meaning|Description|Schema|
|---|---|---|---|
|201|[Created](https://tools.ietf.org/html/rfc7231#section-6.3.2)|none|[Annotation](#schemaannotation)|

<aside class="success">
This operation does not require authentication
</aside>

## annotations_retrieve

<a id="opIdannotations_retrieve"></a>

> Code samples

```shell
# You can also use wget
curl -X GET /api/projects/{project_id}/annotations/{id}/ \
  -H 'Accept: application/json'

```

```http
GET /api/projects/{project_id}/annotations/{id}/ HTTP/1.1

Accept: application/json

```

```javascript

const headers = {
  'Accept':'application/json'
};

fetch('/api/projects/{project_id}/annotations/{id}/',
{
  method: 'GET',

  headers: headers
})
.then(function(res) {
    return res.json();
}).then(function(body) {
    console.log(body);
});

```

```ruby
require 'rest-client'
require 'json'

headers = {
  'Accept' => 'application/json'
}

result = RestClient.get '/api/projects/{project_id}/annotations/{id}/',
  params: {
  }, headers: headers

p JSON.parse(result)

```

```python
import requests
headers = {
  'Accept': 'application/json'
}

r = requests.get('/api/projects/{project_id}/annotations/{id}/', headers = headers)

print(r.json())

```

```php
<?php

require 'vendor/autoload.php';

$headers = array(
    'Accept' => 'application/json',
);

$client = new \GuzzleHttp\Client();

// Define array of request body.
$request_body = array();

try {
    $response = $client->request('GET','/api/projects/{project_id}/annotations/{id}/', array(
        'headers' => $headers,
        'json' => $request_body,
       )
    );
    print_r($response->getBody()->getContents());
 }
 catch (\GuzzleHttp\Exception\BadResponseException $e) {
    // handle exception or api errors.
    print_r($e->getMessage());
 }

 // ...

```

```java
URL obj = new URL("/api/projects/{project_id}/annotations/{id}/");
HttpURLConnection con = (HttpURLConnection) obj.openConnection();
con.setRequestMethod("GET");
int responseCode = con.getResponseCode();
BufferedReader in = new BufferedReader(
    new InputStreamReader(con.getInputStream()));
String inputLine;
StringBuffer response = new StringBuffer();
while ((inputLine = in.readLine()) != null) {
    response.append(inputLine);
}
in.close();
System.out.println(response.toString());

```

```go
package main

import (
       "bytes"
       "net/http"
)

func main() {

    headers := map[string][]string{
        "Accept": []string{"application/json"},
    }

    data := bytes.NewBuffer([]byte{jsonReq})
    req, err := http.NewRequest("GET", "/api/projects/{project_id}/annotations/{id}/", data)
    req.Header = headers

    client := &http.Client{}
    resp, err := client.Do(req)
    // ...
}

```

`GET /api/projects/{project_id}/annotations/{id}/`

Create, Read, Update and Delete annotations. [See docs](https://posthog.com/docs/user-guides/annotations) for more information on annotations.

<h3 id="annotations_retrieve-parameters">Parameters</h3>

|Name|In|Type|Required|Description|
|---|---|---|---|---|
|id|path|integer|true|A unique integer value identifying this annotation.|
|project_id|path|string|true|Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/.|

> Example responses

> 200 Response

```json
{
  "id": 0,
  "content": "string",
  "date_marker": "2019-08-24T14:15:22Z",
  "creation_type": "USR",
  "dashboard_item": 0,
  "created_by": {
    "id": 0,
    "uuid": "095be615-a8ad-4c33-8e9c-c7612fbf6c9f",
    "distinct_id": "string",
    "first_name": "string",
    "email": "user@example.com"
  },
  "created_at": "2019-08-24T14:15:22Z",
  "updated_at": "2019-08-24T14:15:22Z",
  "deleted": true,
  "scope": "dashboard_item"
}
```

<h3 id="annotations_retrieve-responses">Responses</h3>

|Status|Meaning|Description|Schema|
|---|---|---|---|
|200|[OK](https://tools.ietf.org/html/rfc7231#section-6.3.1)|none|[Annotation](#schemaannotation)|

<aside class="success">
This operation does not require authentication
</aside>

## annotations_update

<a id="opIdannotations_update"></a>

> Code samples

```shell
# You can also use wget
curl -X PUT /api/projects/{project_id}/annotations/{id}/ \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json'

```

```http
PUT /api/projects/{project_id}/annotations/{id}/ HTTP/1.1

Content-Type: application/json
Accept: application/json

```

```javascript
const inputBody = '{
  "content": "string",
  "date_marker": "2019-08-24T14:15:22Z",
  "dashboard_item": 0,
  "deleted": true,
  "scope": "dashboard_item"
}';
const headers = {
  'Content-Type':'application/json',
  'Accept':'application/json'
};

fetch('/api/projects/{project_id}/annotations/{id}/',
{
  method: 'PUT',
  body: inputBody,
  headers: headers
})
.then(function(res) {
    return res.json();
}).then(function(body) {
    console.log(body);
});

```

```ruby
require 'rest-client'
require 'json'

headers = {
  'Content-Type' => 'application/json',
  'Accept' => 'application/json'
}

result = RestClient.put '/api/projects/{project_id}/annotations/{id}/',
  params: {
  }, headers: headers

p JSON.parse(result)

```

```python
import requests
headers = {
  'Content-Type': 'application/json',
  'Accept': 'application/json'
}

r = requests.put('/api/projects/{project_id}/annotations/{id}/', headers = headers)

print(r.json())

```

```php
<?php

require 'vendor/autoload.php';

$headers = array(
    'Content-Type' => 'application/json',
    'Accept' => 'application/json',
);

$client = new \GuzzleHttp\Client();

// Define array of request body.
$request_body = array();

try {
    $response = $client->request('PUT','/api/projects/{project_id}/annotations/{id}/', array(
        'headers' => $headers,
        'json' => $request_body,
       )
    );
    print_r($response->getBody()->getContents());
 }
 catch (\GuzzleHttp\Exception\BadResponseException $e) {
    // handle exception or api errors.
    print_r($e->getMessage());
 }

 // ...

```

```java
URL obj = new URL("/api/projects/{project_id}/annotations/{id}/");
HttpURLConnection con = (HttpURLConnection) obj.openConnection();
con.setRequestMethod("PUT");
int responseCode = con.getResponseCode();
BufferedReader in = new BufferedReader(
    new InputStreamReader(con.getInputStream()));
String inputLine;
StringBuffer response = new StringBuffer();
while ((inputLine = in.readLine()) != null) {
    response.append(inputLine);
}
in.close();
System.out.println(response.toString());

```

```go
package main

import (
       "bytes"
       "net/http"
)

func main() {

    headers := map[string][]string{
        "Content-Type": []string{"application/json"},
        "Accept": []string{"application/json"},
    }

    data := bytes.NewBuffer([]byte{jsonReq})
    req, err := http.NewRequest("PUT", "/api/projects/{project_id}/annotations/{id}/", data)
    req.Header = headers

    client := &http.Client{}
    resp, err := client.Do(req)
    // ...
}

```

`PUT /api/projects/{project_id}/annotations/{id}/`

Create, Read, Update and Delete annotations. [See docs](https://posthog.com/docs/user-guides/annotations) for more information on annotations.

> Body parameter

```json
{
  "content": "string",
  "date_marker": "2019-08-24T14:15:22Z",
  "dashboard_item": 0,
  "deleted": true,
  "scope": "dashboard_item"
}
```

```yaml
content: string
date_marker: 2019-08-24T14:15:22Z
dashboard_item: 0
deleted: true
scope: dashboard_item

```

<h3 id="annotations_update-parameters">Parameters</h3>

|Name|In|Type|Required|Description|
|---|---|---|---|---|
|id|path|integer|true|A unique integer value identifying this annotation.|
|project_id|path|string|true|Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/.|
|body|body|[Annotation](#schemaannotation)|false|none|

> Example responses

> 200 Response

```json
{
  "id": 0,
  "content": "string",
  "date_marker": "2019-08-24T14:15:22Z",
  "creation_type": "USR",
  "dashboard_item": 0,
  "created_by": {
    "id": 0,
    "uuid": "095be615-a8ad-4c33-8e9c-c7612fbf6c9f",
    "distinct_id": "string",
    "first_name": "string",
    "email": "user@example.com"
  },
  "created_at": "2019-08-24T14:15:22Z",
  "updated_at": "2019-08-24T14:15:22Z",
  "deleted": true,
  "scope": "dashboard_item"
}
```

<h3 id="annotations_update-responses">Responses</h3>

|Status|Meaning|Description|Schema|
|---|---|---|---|
|200|[OK](https://tools.ietf.org/html/rfc7231#section-6.3.1)|none|[Annotation](#schemaannotation)|

<aside class="success">
This operation does not require authentication
</aside>

## annotations_partial_update

<a id="opIdannotations_partial_update"></a>

> Code samples

```shell
# You can also use wget
curl -X PATCH /api/projects/{project_id}/annotations/{id}/ \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json'

```

```http
PATCH /api/projects/{project_id}/annotations/{id}/ HTTP/1.1

Content-Type: application/json
Accept: application/json

```

```javascript
const inputBody = '{
  "content": "string",
  "date_marker": "2019-08-24T14:15:22Z",
  "dashboard_item": 0,
  "deleted": true,
  "scope": "dashboard_item"
}';
const headers = {
  'Content-Type':'application/json',
  'Accept':'application/json'
};

fetch('/api/projects/{project_id}/annotations/{id}/',
{
  method: 'PATCH',
  body: inputBody,
  headers: headers
})
.then(function(res) {
    return res.json();
}).then(function(body) {
    console.log(body);
});

```

```ruby
require 'rest-client'
require 'json'

headers = {
  'Content-Type' => 'application/json',
  'Accept' => 'application/json'
}

result = RestClient.patch '/api/projects/{project_id}/annotations/{id}/',
  params: {
  }, headers: headers

p JSON.parse(result)

```

```python
import requests
headers = {
  'Content-Type': 'application/json',
  'Accept': 'application/json'
}

r = requests.patch('/api/projects/{project_id}/annotations/{id}/', headers = headers)

print(r.json())

```

```php
<?php

require 'vendor/autoload.php';

$headers = array(
    'Content-Type' => 'application/json',
    'Accept' => 'application/json',
);

$client = new \GuzzleHttp\Client();

// Define array of request body.
$request_body = array();

try {
    $response = $client->request('PATCH','/api/projects/{project_id}/annotations/{id}/', array(
        'headers' => $headers,
        'json' => $request_body,
       )
    );
    print_r($response->getBody()->getContents());
 }
 catch (\GuzzleHttp\Exception\BadResponseException $e) {
    // handle exception or api errors.
    print_r($e->getMessage());
 }

 // ...

```

```java
URL obj = new URL("/api/projects/{project_id}/annotations/{id}/");
HttpURLConnection con = (HttpURLConnection) obj.openConnection();
con.setRequestMethod("PATCH");
int responseCode = con.getResponseCode();
BufferedReader in = new BufferedReader(
    new InputStreamReader(con.getInputStream()));
String inputLine;
StringBuffer response = new StringBuffer();
while ((inputLine = in.readLine()) != null) {
    response.append(inputLine);
}
in.close();
System.out.println(response.toString());

```

```go
package main

import (
       "bytes"
       "net/http"
)

func main() {

    headers := map[string][]string{
        "Content-Type": []string{"application/json"},
        "Accept": []string{"application/json"},
    }

    data := bytes.NewBuffer([]byte{jsonReq})
    req, err := http.NewRequest("PATCH", "/api/projects/{project_id}/annotations/{id}/", data)
    req.Header = headers

    client := &http.Client{}
    resp, err := client.Do(req)
    // ...
}

```

`PATCH /api/projects/{project_id}/annotations/{id}/`

Create, Read, Update and Delete annotations. [See docs](https://posthog.com/docs/user-guides/annotations) for more information on annotations.

> Body parameter

```json
{
  "content": "string",
  "date_marker": "2019-08-24T14:15:22Z",
  "dashboard_item": 0,
  "deleted": true,
  "scope": "dashboard_item"
}
```

```yaml
content: string
date_marker: 2019-08-24T14:15:22Z
dashboard_item: 0
deleted: true
scope: dashboard_item

```

<h3 id="annotations_partial_update-parameters">Parameters</h3>

|Name|In|Type|Required|Description|
|---|---|---|---|---|
|id|path|integer|true|A unique integer value identifying this annotation.|
|project_id|path|string|true|Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/.|
|body|body|[PatchedAnnotation](#schemapatchedannotation)|false|none|

> Example responses

> 200 Response

```json
{
  "id": 0,
  "content": "string",
  "date_marker": "2019-08-24T14:15:22Z",
  "creation_type": "USR",
  "dashboard_item": 0,
  "created_by": {
    "id": 0,
    "uuid": "095be615-a8ad-4c33-8e9c-c7612fbf6c9f",
    "distinct_id": "string",
    "first_name": "string",
    "email": "user@example.com"
  },
  "created_at": "2019-08-24T14:15:22Z",
  "updated_at": "2019-08-24T14:15:22Z",
  "deleted": true,
  "scope": "dashboard_item"
}
```

<h3 id="annotations_partial_update-responses">Responses</h3>

|Status|Meaning|Description|Schema|
|---|---|---|---|
|200|[OK](https://tools.ietf.org/html/rfc7231#section-6.3.1)|none|[Annotation](#schemaannotation)|

<aside class="success">
This operation does not require authentication
</aside>

## annotations_destroy

<a id="opIdannotations_destroy"></a>

> Code samples

```shell
# You can also use wget
curl -X DELETE /api/projects/{project_id}/annotations/{id}/

```

```http
DELETE /api/projects/{project_id}/annotations/{id}/ HTTP/1.1

```

```javascript

fetch('/api/projects/{project_id}/annotations/{id}/',
{
  method: 'DELETE'

})
.then(function(res) {
    return res.json();
}).then(function(body) {
    console.log(body);
});

```

```ruby
require 'rest-client'
require 'json'

result = RestClient.delete '/api/projects/{project_id}/annotations/{id}/',
  params: {
  }

p JSON.parse(result)

```

```python
import requests

r = requests.delete('/api/projects/{project_id}/annotations/{id}/')

print(r.json())

```

```php
<?php

require 'vendor/autoload.php';

$client = new \GuzzleHttp\Client();

// Define array of request body.
$request_body = array();

try {
    $response = $client->request('DELETE','/api/projects/{project_id}/annotations/{id}/', array(
        'headers' => $headers,
        'json' => $request_body,
       )
    );
    print_r($response->getBody()->getContents());
 }
 catch (\GuzzleHttp\Exception\BadResponseException $e) {
    // handle exception or api errors.
    print_r($e->getMessage());
 }

 // ...

```

```java
URL obj = new URL("/api/projects/{project_id}/annotations/{id}/");
HttpURLConnection con = (HttpURLConnection) obj.openConnection();
con.setRequestMethod("DELETE");
int responseCode = con.getResponseCode();
BufferedReader in = new BufferedReader(
    new InputStreamReader(con.getInputStream()));
String inputLine;
StringBuffer response = new StringBuffer();
while ((inputLine = in.readLine()) != null) {
    response.append(inputLine);
}
in.close();
System.out.println(response.toString());

```

```go
package main

import (
       "bytes"
       "net/http"
)

func main() {

    data := bytes.NewBuffer([]byte{jsonReq})
    req, err := http.NewRequest("DELETE", "/api/projects/{project_id}/annotations/{id}/", data)
    req.Header = headers

    client := &http.Client{}
    resp, err := client.Do(req)
    // ...
}

```

`DELETE /api/projects/{project_id}/annotations/{id}/`

Create, Read, Update and Delete annotations. [See docs](https://posthog.com/docs/user-guides/annotations) for more information on annotations.

<h3 id="annotations_destroy-parameters">Parameters</h3>

|Name|In|Type|Required|Description|
|---|---|---|---|---|
|id|path|integer|true|A unique integer value identifying this annotation.|
|project_id|path|string|true|Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/.|

<h3 id="annotations_destroy-responses">Responses</h3>

|Status|Meaning|Description|Schema|
|---|---|---|---|
|204|[No Content](https://tools.ietf.org/html/rfc7231#section-6.3.5)|No response body|None|

<aside class="success">
This operation does not require authentication
</aside>

<h1 id="-cohorts">cohorts</h1>

## cohorts_list

<a id="opIdcohorts_list"></a>

> Code samples

```shell
# You can also use wget
curl -X GET /api/projects/{project_id}/cohorts/ \
  -H 'Accept: application/json'

```

```http
GET /api/projects/{project_id}/cohorts/ HTTP/1.1

Accept: application/json

```

```javascript

const headers = {
  'Accept':'application/json'
};

fetch('/api/projects/{project_id}/cohorts/',
{
  method: 'GET',

  headers: headers
})
.then(function(res) {
    return res.json();
}).then(function(body) {
    console.log(body);
});

```

```ruby
require 'rest-client'
require 'json'

headers = {
  'Accept' => 'application/json'
}

result = RestClient.get '/api/projects/{project_id}/cohorts/',
  params: {
  }, headers: headers

p JSON.parse(result)

```

```python
import requests
headers = {
  'Accept': 'application/json'
}

r = requests.get('/api/projects/{project_id}/cohorts/', headers = headers)

print(r.json())

```

```php
<?php

require 'vendor/autoload.php';

$headers = array(
    'Accept' => 'application/json',
);

$client = new \GuzzleHttp\Client();

// Define array of request body.
$request_body = array();

try {
    $response = $client->request('GET','/api/projects/{project_id}/cohorts/', array(
        'headers' => $headers,
        'json' => $request_body,
       )
    );
    print_r($response->getBody()->getContents());
 }
 catch (\GuzzleHttp\Exception\BadResponseException $e) {
    // handle exception or api errors.
    print_r($e->getMessage());
 }

 // ...

```

```java
URL obj = new URL("/api/projects/{project_id}/cohorts/");
HttpURLConnection con = (HttpURLConnection) obj.openConnection();
con.setRequestMethod("GET");
int responseCode = con.getResponseCode();
BufferedReader in = new BufferedReader(
    new InputStreamReader(con.getInputStream()));
String inputLine;
StringBuffer response = new StringBuffer();
while ((inputLine = in.readLine()) != null) {
    response.append(inputLine);
}
in.close();
System.out.println(response.toString());

```

```go
package main

import (
       "bytes"
       "net/http"
)

func main() {

    headers := map[string][]string{
        "Accept": []string{"application/json"},
    }

    data := bytes.NewBuffer([]byte{jsonReq})
    req, err := http.NewRequest("GET", "/api/projects/{project_id}/cohorts/", data)
    req.Header = headers

    client := &http.Client{}
    resp, err := client.Do(req)
    // ...
}

```

`GET /api/projects/{project_id}/cohorts/`

<h3 id="cohorts_list-parameters">Parameters</h3>

|Name|In|Type|Required|Description|
|---|---|---|---|---|
|limit|query|integer|false|Number of results to return per page.|
|offset|query|integer|false|The initial index from which to return the results.|
|project_id|path|string|true|Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/.|

> Example responses

> 200 Response

```json
{
  "count": 123,
  "next": "http://api.example.org/accounts/?offset=400&limit=100",
  "previous": "http://api.example.org/accounts/?offset=200&limit=100",
  "results": [
    {
      "id": 0,
      "name": "string",
      "description": "string",
      "groups": {
        "property1": null,
        "property2": null
      },
      "deleted": true,
      "is_calculating": true,
      "created_by": {
        "id": 0,
        "uuid": "095be615-a8ad-4c33-8e9c-c7612fbf6c9f",
        "distinct_id": "string",
        "first_name": "string",
        "email": "user@example.com"
      },
      "created_at": "2019-08-24T14:15:22Z",
      "last_calculation": "2019-08-24T14:15:22Z",
      "errors_calculating": 0,
      "count": 0,
      "is_static": true
    }
  ]
}
```

<h3 id="cohorts_list-responses">Responses</h3>

|Status|Meaning|Description|Schema|
|---|---|---|---|
|200|[OK](https://tools.ietf.org/html/rfc7231#section-6.3.1)|none|[PaginatedClickhouseCohortList](#schemapaginatedclickhousecohortlist)|

<aside class="success">
This operation does not require authentication
</aside>

## cohorts_create

<a id="opIdcohorts_create"></a>

> Code samples

```shell
# You can also use wget
curl -X POST /api/projects/{project_id}/cohorts/ \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json'

```

```http
POST /api/projects/{project_id}/cohorts/ HTTP/1.1

Content-Type: application/json
Accept: application/json

```

```javascript
const inputBody = '{
  "name": "string",
  "description": "string",
  "groups": {
    "property1": null,
    "property2": null
  },
  "deleted": true,
  "is_static": true
}';
const headers = {
  'Content-Type':'application/json',
  'Accept':'application/json'
};

fetch('/api/projects/{project_id}/cohorts/',
{
  method: 'POST',
  body: inputBody,
  headers: headers
})
.then(function(res) {
    return res.json();
}).then(function(body) {
    console.log(body);
});

```

```ruby
require 'rest-client'
require 'json'

headers = {
  'Content-Type' => 'application/json',
  'Accept' => 'application/json'
}

result = RestClient.post '/api/projects/{project_id}/cohorts/',
  params: {
  }, headers: headers

p JSON.parse(result)

```

```python
import requests
headers = {
  'Content-Type': 'application/json',
  'Accept': 'application/json'
}

r = requests.post('/api/projects/{project_id}/cohorts/', headers = headers)

print(r.json())

```

```php
<?php

require 'vendor/autoload.php';

$headers = array(
    'Content-Type' => 'application/json',
    'Accept' => 'application/json',
);

$client = new \GuzzleHttp\Client();

// Define array of request body.
$request_body = array();

try {
    $response = $client->request('POST','/api/projects/{project_id}/cohorts/', array(
        'headers' => $headers,
        'json' => $request_body,
       )
    );
    print_r($response->getBody()->getContents());
 }
 catch (\GuzzleHttp\Exception\BadResponseException $e) {
    // handle exception or api errors.
    print_r($e->getMessage());
 }

 // ...

```

```java
URL obj = new URL("/api/projects/{project_id}/cohorts/");
HttpURLConnection con = (HttpURLConnection) obj.openConnection();
con.setRequestMethod("POST");
int responseCode = con.getResponseCode();
BufferedReader in = new BufferedReader(
    new InputStreamReader(con.getInputStream()));
String inputLine;
StringBuffer response = new StringBuffer();
while ((inputLine = in.readLine()) != null) {
    response.append(inputLine);
}
in.close();
System.out.println(response.toString());

```

```go
package main

import (
       "bytes"
       "net/http"
)

func main() {

    headers := map[string][]string{
        "Content-Type": []string{"application/json"},
        "Accept": []string{"application/json"},
    }

    data := bytes.NewBuffer([]byte{jsonReq})
    req, err := http.NewRequest("POST", "/api/projects/{project_id}/cohorts/", data)
    req.Header = headers

    client := &http.Client{}
    resp, err := client.Do(req)
    // ...
}

```

`POST /api/projects/{project_id}/cohorts/`

> Body parameter

```json
{
  "name": "string",
  "description": "string",
  "groups": {
    "property1": null,
    "property2": null
  },
  "deleted": true,
  "is_static": true
}
```

```yaml
name: string
description: string
groups:
  ? property1
  ? property2
deleted: true
is_static: true

```

<h3 id="cohorts_create-parameters">Parameters</h3>

|Name|In|Type|Required|Description|
|---|---|---|---|---|
|project_id|path|string|true|Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/.|
|body|body|[ClickhouseCohort](#schemaclickhousecohort)|false|none|

> Example responses

> 201 Response

```json
{
  "id": 0,
  "name": "string",
  "description": "string",
  "groups": {
    "property1": null,
    "property2": null
  },
  "deleted": true,
  "is_calculating": true,
  "created_by": {
    "id": 0,
    "uuid": "095be615-a8ad-4c33-8e9c-c7612fbf6c9f",
    "distinct_id": "string",
    "first_name": "string",
    "email": "user@example.com"
  },
  "created_at": "2019-08-24T14:15:22Z",
  "last_calculation": "2019-08-24T14:15:22Z",
  "errors_calculating": 0,
  "count": 0,
  "is_static": true
}
```

<h3 id="cohorts_create-responses">Responses</h3>

|Status|Meaning|Description|Schema|
|---|---|---|---|
|201|[Created](https://tools.ietf.org/html/rfc7231#section-6.3.2)|none|[ClickhouseCohort](#schemaclickhousecohort)|

<aside class="success">
This operation does not require authentication
</aside>

## cohorts_retrieve

<a id="opIdcohorts_retrieve"></a>

> Code samples

```shell
# You can also use wget
curl -X GET /api/projects/{project_id}/cohorts/{id}/ \
  -H 'Accept: application/json'

```

```http
GET /api/projects/{project_id}/cohorts/{id}/ HTTP/1.1

Accept: application/json

```

```javascript

const headers = {
  'Accept':'application/json'
};

fetch('/api/projects/{project_id}/cohorts/{id}/',
{
  method: 'GET',

  headers: headers
})
.then(function(res) {
    return res.json();
}).then(function(body) {
    console.log(body);
});

```

```ruby
require 'rest-client'
require 'json'

headers = {
  'Accept' => 'application/json'
}

result = RestClient.get '/api/projects/{project_id}/cohorts/{id}/',
  params: {
  }, headers: headers

p JSON.parse(result)

```

```python
import requests
headers = {
  'Accept': 'application/json'
}

r = requests.get('/api/projects/{project_id}/cohorts/{id}/', headers = headers)

print(r.json())

```

```php
<?php

require 'vendor/autoload.php';

$headers = array(
    'Accept' => 'application/json',
);

$client = new \GuzzleHttp\Client();

// Define array of request body.
$request_body = array();

try {
    $response = $client->request('GET','/api/projects/{project_id}/cohorts/{id}/', array(
        'headers' => $headers,
        'json' => $request_body,
       )
    );
    print_r($response->getBody()->getContents());
 }
 catch (\GuzzleHttp\Exception\BadResponseException $e) {
    // handle exception or api errors.
    print_r($e->getMessage());
 }

 // ...

```

```java
URL obj = new URL("/api/projects/{project_id}/cohorts/{id}/");
HttpURLConnection con = (HttpURLConnection) obj.openConnection();
con.setRequestMethod("GET");
int responseCode = con.getResponseCode();
BufferedReader in = new BufferedReader(
    new InputStreamReader(con.getInputStream()));
String inputLine;
StringBuffer response = new StringBuffer();
while ((inputLine = in.readLine()) != null) {
    response.append(inputLine);
}
in.close();
System.out.println(response.toString());

```

```go
package main

import (
       "bytes"
       "net/http"
)

func main() {

    headers := map[string][]string{
        "Accept": []string{"application/json"},
    }

    data := bytes.NewBuffer([]byte{jsonReq})
    req, err := http.NewRequest("GET", "/api/projects/{project_id}/cohorts/{id}/", data)
    req.Header = headers

    client := &http.Client{}
    resp, err := client.Do(req)
    // ...
}

```

`GET /api/projects/{project_id}/cohorts/{id}/`

<h3 id="cohorts_retrieve-parameters">Parameters</h3>

|Name|In|Type|Required|Description|
|---|---|---|---|---|
|id|path|integer|true|A unique integer value identifying this cohort.|
|project_id|path|string|true|Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/.|

> Example responses

> 200 Response

```json
{
  "id": 0,
  "name": "string",
  "description": "string",
  "groups": {
    "property1": null,
    "property2": null
  },
  "deleted": true,
  "is_calculating": true,
  "created_by": {
    "id": 0,
    "uuid": "095be615-a8ad-4c33-8e9c-c7612fbf6c9f",
    "distinct_id": "string",
    "first_name": "string",
    "email": "user@example.com"
  },
  "created_at": "2019-08-24T14:15:22Z",
  "last_calculation": "2019-08-24T14:15:22Z",
  "errors_calculating": 0,
  "count": 0,
  "is_static": true
}
```

<h3 id="cohorts_retrieve-responses">Responses</h3>

|Status|Meaning|Description|Schema|
|---|---|---|---|
|200|[OK](https://tools.ietf.org/html/rfc7231#section-6.3.1)|none|[ClickhouseCohort](#schemaclickhousecohort)|

<aside class="success">
This operation does not require authentication
</aside>

## cohorts_update

<a id="opIdcohorts_update"></a>

> Code samples

```shell
# You can also use wget
curl -X PUT /api/projects/{project_id}/cohorts/{id}/ \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json'

```

```http
PUT /api/projects/{project_id}/cohorts/{id}/ HTTP/1.1

Content-Type: application/json
Accept: application/json

```

```javascript
const inputBody = '{
  "name": "string",
  "description": "string",
  "groups": {
    "property1": null,
    "property2": null
  },
  "deleted": true,
  "is_static": true
}';
const headers = {
  'Content-Type':'application/json',
  'Accept':'application/json'
};

fetch('/api/projects/{project_id}/cohorts/{id}/',
{
  method: 'PUT',
  body: inputBody,
  headers: headers
})
.then(function(res) {
    return res.json();
}).then(function(body) {
    console.log(body);
});

```

```ruby
require 'rest-client'
require 'json'

headers = {
  'Content-Type' => 'application/json',
  'Accept' => 'application/json'
}

result = RestClient.put '/api/projects/{project_id}/cohorts/{id}/',
  params: {
  }, headers: headers

p JSON.parse(result)

```

```python
import requests
headers = {
  'Content-Type': 'application/json',
  'Accept': 'application/json'
}

r = requests.put('/api/projects/{project_id}/cohorts/{id}/', headers = headers)

print(r.json())

```

```php
<?php

require 'vendor/autoload.php';

$headers = array(
    'Content-Type' => 'application/json',
    'Accept' => 'application/json',
);

$client = new \GuzzleHttp\Client();

// Define array of request body.
$request_body = array();

try {
    $response = $client->request('PUT','/api/projects/{project_id}/cohorts/{id}/', array(
        'headers' => $headers,
        'json' => $request_body,
       )
    );
    print_r($response->getBody()->getContents());
 }
 catch (\GuzzleHttp\Exception\BadResponseException $e) {
    // handle exception or api errors.
    print_r($e->getMessage());
 }

 // ...

```

```java
URL obj = new URL("/api/projects/{project_id}/cohorts/{id}/");
HttpURLConnection con = (HttpURLConnection) obj.openConnection();
con.setRequestMethod("PUT");
int responseCode = con.getResponseCode();
BufferedReader in = new BufferedReader(
    new InputStreamReader(con.getInputStream()));
String inputLine;
StringBuffer response = new StringBuffer();
while ((inputLine = in.readLine()) != null) {
    response.append(inputLine);
}
in.close();
System.out.println(response.toString());

```

```go
package main

import (
       "bytes"
       "net/http"
)

func main() {

    headers := map[string][]string{
        "Content-Type": []string{"application/json"},
        "Accept": []string{"application/json"},
    }

    data := bytes.NewBuffer([]byte{jsonReq})
    req, err := http.NewRequest("PUT", "/api/projects/{project_id}/cohorts/{id}/", data)
    req.Header = headers

    client := &http.Client{}
    resp, err := client.Do(req)
    // ...
}

```

`PUT /api/projects/{project_id}/cohorts/{id}/`

> Body parameter

```json
{
  "name": "string",
  "description": "string",
  "groups": {
    "property1": null,
    "property2": null
  },
  "deleted": true,
  "is_static": true
}
```

```yaml
name: string
description: string
groups:
  ? property1
  ? property2
deleted: true
is_static: true

```

<h3 id="cohorts_update-parameters">Parameters</h3>

|Name|In|Type|Required|Description|
|---|---|---|---|---|
|id|path|integer|true|A unique integer value identifying this cohort.|
|project_id|path|string|true|Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/.|
|body|body|[ClickhouseCohort](#schemaclickhousecohort)|false|none|

> Example responses

> 200 Response

```json
{
  "id": 0,
  "name": "string",
  "description": "string",
  "groups": {
    "property1": null,
    "property2": null
  },
  "deleted": true,
  "is_calculating": true,
  "created_by": {
    "id": 0,
    "uuid": "095be615-a8ad-4c33-8e9c-c7612fbf6c9f",
    "distinct_id": "string",
    "first_name": "string",
    "email": "user@example.com"
  },
  "created_at": "2019-08-24T14:15:22Z",
  "last_calculation": "2019-08-24T14:15:22Z",
  "errors_calculating": 0,
  "count": 0,
  "is_static": true
}
```

<h3 id="cohorts_update-responses">Responses</h3>

|Status|Meaning|Description|Schema|
|---|---|---|---|
|200|[OK](https://tools.ietf.org/html/rfc7231#section-6.3.1)|none|[ClickhouseCohort](#schemaclickhousecohort)|

<aside class="success">
This operation does not require authentication
</aside>

## cohorts_partial_update

<a id="opIdcohorts_partial_update"></a>

> Code samples

```shell
# You can also use wget
curl -X PATCH /api/projects/{project_id}/cohorts/{id}/ \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json'

```

```http
PATCH /api/projects/{project_id}/cohorts/{id}/ HTTP/1.1

Content-Type: application/json
Accept: application/json

```

```javascript
const inputBody = '{
  "name": "string",
  "description": "string",
  "groups": {
    "property1": null,
    "property2": null
  },
  "deleted": true,
  "is_static": true
}';
const headers = {
  'Content-Type':'application/json',
  'Accept':'application/json'
};

fetch('/api/projects/{project_id}/cohorts/{id}/',
{
  method: 'PATCH',
  body: inputBody,
  headers: headers
})
.then(function(res) {
    return res.json();
}).then(function(body) {
    console.log(body);
});

```

```ruby
require 'rest-client'
require 'json'

headers = {
  'Content-Type' => 'application/json',
  'Accept' => 'application/json'
}

result = RestClient.patch '/api/projects/{project_id}/cohorts/{id}/',
  params: {
  }, headers: headers

p JSON.parse(result)

```

```python
import requests
headers = {
  'Content-Type': 'application/json',
  'Accept': 'application/json'
}

r = requests.patch('/api/projects/{project_id}/cohorts/{id}/', headers = headers)

print(r.json())

```

```php
<?php

require 'vendor/autoload.php';

$headers = array(
    'Content-Type' => 'application/json',
    'Accept' => 'application/json',
);

$client = new \GuzzleHttp\Client();

// Define array of request body.
$request_body = array();

try {
    $response = $client->request('PATCH','/api/projects/{project_id}/cohorts/{id}/', array(
        'headers' => $headers,
        'json' => $request_body,
       )
    );
    print_r($response->getBody()->getContents());
 }
 catch (\GuzzleHttp\Exception\BadResponseException $e) {
    // handle exception or api errors.
    print_r($e->getMessage());
 }

 // ...

```

```java
URL obj = new URL("/api/projects/{project_id}/cohorts/{id}/");
HttpURLConnection con = (HttpURLConnection) obj.openConnection();
con.setRequestMethod("PATCH");
int responseCode = con.getResponseCode();
BufferedReader in = new BufferedReader(
    new InputStreamReader(con.getInputStream()));
String inputLine;
StringBuffer response = new StringBuffer();
while ((inputLine = in.readLine()) != null) {
    response.append(inputLine);
}
in.close();
System.out.println(response.toString());

```

```go
package main

import (
       "bytes"
       "net/http"
)

func main() {

    headers := map[string][]string{
        "Content-Type": []string{"application/json"},
        "Accept": []string{"application/json"},
    }

    data := bytes.NewBuffer([]byte{jsonReq})
    req, err := http.NewRequest("PATCH", "/api/projects/{project_id}/cohorts/{id}/", data)
    req.Header = headers

    client := &http.Client{}
    resp, err := client.Do(req)
    // ...
}

```

`PATCH /api/projects/{project_id}/cohorts/{id}/`

> Body parameter

```json
{
  "name": "string",
  "description": "string",
  "groups": {
    "property1": null,
    "property2": null
  },
  "deleted": true,
  "is_static": true
}
```

```yaml
name: string
description: string
groups:
  ? property1
  ? property2
deleted: true
is_static: true

```

<h3 id="cohorts_partial_update-parameters">Parameters</h3>

|Name|In|Type|Required|Description|
|---|---|---|---|---|
|id|path|integer|true|A unique integer value identifying this cohort.|
|project_id|path|string|true|Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/.|
|body|body|[PatchedClickhouseCohort](#schemapatchedclickhousecohort)|false|none|

> Example responses

> 200 Response

```json
{
  "id": 0,
  "name": "string",
  "description": "string",
  "groups": {
    "property1": null,
    "property2": null
  },
  "deleted": true,
  "is_calculating": true,
  "created_by": {
    "id": 0,
    "uuid": "095be615-a8ad-4c33-8e9c-c7612fbf6c9f",
    "distinct_id": "string",
    "first_name": "string",
    "email": "user@example.com"
  },
  "created_at": "2019-08-24T14:15:22Z",
  "last_calculation": "2019-08-24T14:15:22Z",
  "errors_calculating": 0,
  "count": 0,
  "is_static": true
}
```

<h3 id="cohorts_partial_update-responses">Responses</h3>

|Status|Meaning|Description|Schema|
|---|---|---|---|
|200|[OK](https://tools.ietf.org/html/rfc7231#section-6.3.1)|none|[ClickhouseCohort](#schemaclickhousecohort)|

<aside class="success">
This operation does not require authentication
</aside>

## cohorts_destroy

<a id="opIdcohorts_destroy"></a>

> Code samples

```shell
# You can also use wget
curl -X DELETE /api/projects/{project_id}/cohorts/{id}/

```

```http
DELETE /api/projects/{project_id}/cohorts/{id}/ HTTP/1.1

```

```javascript

fetch('/api/projects/{project_id}/cohorts/{id}/',
{
  method: 'DELETE'

})
.then(function(res) {
    return res.json();
}).then(function(body) {
    console.log(body);
});

```

```ruby
require 'rest-client'
require 'json'

result = RestClient.delete '/api/projects/{project_id}/cohorts/{id}/',
  params: {
  }

p JSON.parse(result)

```

```python
import requests

r = requests.delete('/api/projects/{project_id}/cohorts/{id}/')

print(r.json())

```

```php
<?php

require 'vendor/autoload.php';

$client = new \GuzzleHttp\Client();

// Define array of request body.
$request_body = array();

try {
    $response = $client->request('DELETE','/api/projects/{project_id}/cohorts/{id}/', array(
        'headers' => $headers,
        'json' => $request_body,
       )
    );
    print_r($response->getBody()->getContents());
 }
 catch (\GuzzleHttp\Exception\BadResponseException $e) {
    // handle exception or api errors.
    print_r($e->getMessage());
 }

 // ...

```

```java
URL obj = new URL("/api/projects/{project_id}/cohorts/{id}/");
HttpURLConnection con = (HttpURLConnection) obj.openConnection();
con.setRequestMethod("DELETE");
int responseCode = con.getResponseCode();
BufferedReader in = new BufferedReader(
    new InputStreamReader(con.getInputStream()));
String inputLine;
StringBuffer response = new StringBuffer();
while ((inputLine = in.readLine()) != null) {
    response.append(inputLine);
}
in.close();
System.out.println(response.toString());

```

```go
package main

import (
       "bytes"
       "net/http"
)

func main() {

    data := bytes.NewBuffer([]byte{jsonReq})
    req, err := http.NewRequest("DELETE", "/api/projects/{project_id}/cohorts/{id}/", data)
    req.Header = headers

    client := &http.Client{}
    resp, err := client.Do(req)
    // ...
}

```

`DELETE /api/projects/{project_id}/cohorts/{id}/`

<h3 id="cohorts_destroy-parameters">Parameters</h3>

|Name|In|Type|Required|Description|
|---|---|---|---|---|
|id|path|integer|true|A unique integer value identifying this cohort.|
|project_id|path|string|true|Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/.|

<h3 id="cohorts_destroy-responses">Responses</h3>

|Status|Meaning|Description|Schema|
|---|---|---|---|
|204|[No Content](https://tools.ietf.org/html/rfc7231#section-6.3.5)|No response body|None|

<aside class="success">
This operation does not require authentication
</aside>

<h1 id="-dashboards">dashboards</h1>

## dashboards_list

<a id="opIddashboards_list"></a>

> Code samples

```shell
# You can also use wget
curl -X GET /api/projects/{project_id}/dashboards/ \
  -H 'Accept: application/json'

```

```http
GET /api/projects/{project_id}/dashboards/ HTTP/1.1

Accept: application/json

```

```javascript

const headers = {
  'Accept':'application/json'
};

fetch('/api/projects/{project_id}/dashboards/',
{
  method: 'GET',

  headers: headers
})
.then(function(res) {
    return res.json();
}).then(function(body) {
    console.log(body);
});

```

```ruby
require 'rest-client'
require 'json'

headers = {
  'Accept' => 'application/json'
}

result = RestClient.get '/api/projects/{project_id}/dashboards/',
  params: {
  }, headers: headers

p JSON.parse(result)

```

```python
import requests
headers = {
  'Accept': 'application/json'
}

r = requests.get('/api/projects/{project_id}/dashboards/', headers = headers)

print(r.json())

```

```php
<?php

require 'vendor/autoload.php';

$headers = array(
    'Accept' => 'application/json',
);

$client = new \GuzzleHttp\Client();

// Define array of request body.
$request_body = array();

try {
    $response = $client->request('GET','/api/projects/{project_id}/dashboards/', array(
        'headers' => $headers,
        'json' => $request_body,
       )
    );
    print_r($response->getBody()->getContents());
 }
 catch (\GuzzleHttp\Exception\BadResponseException $e) {
    // handle exception or api errors.
    print_r($e->getMessage());
 }

 // ...

```

```java
URL obj = new URL("/api/projects/{project_id}/dashboards/");
HttpURLConnection con = (HttpURLConnection) obj.openConnection();
con.setRequestMethod("GET");
int responseCode = con.getResponseCode();
BufferedReader in = new BufferedReader(
    new InputStreamReader(con.getInputStream()));
String inputLine;
StringBuffer response = new StringBuffer();
while ((inputLine = in.readLine()) != null) {
    response.append(inputLine);
}
in.close();
System.out.println(response.toString());

```

```go
package main

import (
       "bytes"
       "net/http"
)

func main() {

    headers := map[string][]string{
        "Accept": []string{"application/json"},
    }

    data := bytes.NewBuffer([]byte{jsonReq})
    req, err := http.NewRequest("GET", "/api/projects/{project_id}/dashboards/", data)
    req.Header = headers

    client := &http.Client{}
    resp, err := client.Do(req)
    // ...
}

```

`GET /api/projects/{project_id}/dashboards/`

<h3 id="dashboards_list-parameters">Parameters</h3>

|Name|In|Type|Required|Description|
|---|---|---|---|---|
|limit|query|integer|false|Number of results to return per page.|
|offset|query|integer|false|The initial index from which to return the results.|
|project_id|path|string|true|Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/.|

> Example responses

> 200 Response

```json
{
  "count": 123,
  "next": "http://api.example.org/accounts/?offset=400&limit=100",
  "previous": "http://api.example.org/accounts/?offset=200&limit=100",
  "results": [
    {
      "id": 0,
      "name": "string",
      "description": "string",
      "pinned": true,
      "items": "string",
      "created_at": "2019-08-24T14:15:22Z",
      "created_by": {
        "id": 0,
        "uuid": "095be615-a8ad-4c33-8e9c-c7612fbf6c9f",
        "distinct_id": "string",
        "first_name": "string",
        "email": "user@example.com"
      },
      "is_shared": true,
      "share_token": "string",
      "deleted": true,
      "creation_mode": "default",
      "filters": {
        "property1": null,
        "property2": null
      },
      "tags": [
        "string"
      ]
    }
  ]
}
```

<h3 id="dashboards_list-responses">Responses</h3>

|Status|Meaning|Description|Schema|
|---|---|---|---|
|200|[OK](https://tools.ietf.org/html/rfc7231#section-6.3.1)|none|[PaginatedDashboardList](#schemapaginateddashboardlist)|

<aside class="success">
This operation does not require authentication
</aside>

## dashboards_create

<a id="opIddashboards_create"></a>

> Code samples

```shell
# You can also use wget
curl -X POST /api/projects/{project_id}/dashboards/ \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json'

```

```http
POST /api/projects/{project_id}/dashboards/ HTTP/1.1

Content-Type: application/json
Accept: application/json

```

```javascript
const inputBody = '{
  "name": "string",
  "description": "string",
  "pinned": true,
  "is_shared": true,
  "share_token": "string",
  "deleted": true,
  "use_template": "string",
  "use_dashboard": 0,
  "filters": {
    "property1": null,
    "property2": null
  },
  "tags": [
    "string"
  ]
}';
const headers = {
  'Content-Type':'application/json',
  'Accept':'application/json'
};

fetch('/api/projects/{project_id}/dashboards/',
{
  method: 'POST',
  body: inputBody,
  headers: headers
})
.then(function(res) {
    return res.json();
}).then(function(body) {
    console.log(body);
});

```

```ruby
require 'rest-client'
require 'json'

headers = {
  'Content-Type' => 'application/json',
  'Accept' => 'application/json'
}

result = RestClient.post '/api/projects/{project_id}/dashboards/',
  params: {
  }, headers: headers

p JSON.parse(result)

```

```python
import requests
headers = {
  'Content-Type': 'application/json',
  'Accept': 'application/json'
}

r = requests.post('/api/projects/{project_id}/dashboards/', headers = headers)

print(r.json())

```

```php
<?php

require 'vendor/autoload.php';

$headers = array(
    'Content-Type' => 'application/json',
    'Accept' => 'application/json',
);

$client = new \GuzzleHttp\Client();

// Define array of request body.
$request_body = array();

try {
    $response = $client->request('POST','/api/projects/{project_id}/dashboards/', array(
        'headers' => $headers,
        'json' => $request_body,
       )
    );
    print_r($response->getBody()->getContents());
 }
 catch (\GuzzleHttp\Exception\BadResponseException $e) {
    // handle exception or api errors.
    print_r($e->getMessage());
 }

 // ...

```

```java
URL obj = new URL("/api/projects/{project_id}/dashboards/");
HttpURLConnection con = (HttpURLConnection) obj.openConnection();
con.setRequestMethod("POST");
int responseCode = con.getResponseCode();
BufferedReader in = new BufferedReader(
    new InputStreamReader(con.getInputStream()));
String inputLine;
StringBuffer response = new StringBuffer();
while ((inputLine = in.readLine()) != null) {
    response.append(inputLine);
}
in.close();
System.out.println(response.toString());

```

```go
package main

import (
       "bytes"
       "net/http"
)

func main() {

    headers := map[string][]string{
        "Content-Type": []string{"application/json"},
        "Accept": []string{"application/json"},
    }

    data := bytes.NewBuffer([]byte{jsonReq})
    req, err := http.NewRequest("POST", "/api/projects/{project_id}/dashboards/", data)
    req.Header = headers

    client := &http.Client{}
    resp, err := client.Do(req)
    // ...
}

```

`POST /api/projects/{project_id}/dashboards/`

> Body parameter

```json
{
  "name": "string",
  "description": "string",
  "pinned": true,
  "is_shared": true,
  "share_token": "string",
  "deleted": true,
  "use_template": "string",
  "use_dashboard": 0,
  "filters": {
    "property1": null,
    "property2": null
  },
  "tags": [
    "string"
  ]
}
```

```yaml
name: string
description: string
pinned: true
is_shared: true
share_token: string
deleted: true
use_template: string
use_dashboard: 0
filters:
  ? property1
  ? property2
tags:
  - string

```

<h3 id="dashboards_create-parameters">Parameters</h3>

|Name|In|Type|Required|Description|
|---|---|---|---|---|
|project_id|path|string|true|Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/.|
|body|body|[Dashboard](#schemadashboard)|false|none|

> Example responses

> 201 Response

```json
{
  "id": 0,
  "name": "string",
  "description": "string",
  "pinned": true,
  "items": "string",
  "created_at": "2019-08-24T14:15:22Z",
  "created_by": {
    "id": 0,
    "uuid": "095be615-a8ad-4c33-8e9c-c7612fbf6c9f",
    "distinct_id": "string",
    "first_name": "string",
    "email": "user@example.com"
  },
  "is_shared": true,
  "share_token": "string",
  "deleted": true,
  "creation_mode": "default",
  "filters": {
    "property1": null,
    "property2": null
  },
  "tags": [
    "string"
  ]
}
```

<h3 id="dashboards_create-responses">Responses</h3>

|Status|Meaning|Description|Schema|
|---|---|---|---|
|201|[Created](https://tools.ietf.org/html/rfc7231#section-6.3.2)|none|[Dashboard](#schemadashboard)|

<aside class="success">
This operation does not require authentication
</aside>

## dashboards_retrieve

<a id="opIddashboards_retrieve"></a>

> Code samples

```shell
# You can also use wget
curl -X GET /api/projects/{project_id}/dashboards/{id}/ \
  -H 'Accept: application/json'

```

```http
GET /api/projects/{project_id}/dashboards/{id}/ HTTP/1.1

Accept: application/json

```

```javascript

const headers = {
  'Accept':'application/json'
};

fetch('/api/projects/{project_id}/dashboards/{id}/',
{
  method: 'GET',

  headers: headers
})
.then(function(res) {
    return res.json();
}).then(function(body) {
    console.log(body);
});

```

```ruby
require 'rest-client'
require 'json'

headers = {
  'Accept' => 'application/json'
}

result = RestClient.get '/api/projects/{project_id}/dashboards/{id}/',
  params: {
  }, headers: headers

p JSON.parse(result)

```

```python
import requests
headers = {
  'Accept': 'application/json'
}

r = requests.get('/api/projects/{project_id}/dashboards/{id}/', headers = headers)

print(r.json())

```

```php
<?php

require 'vendor/autoload.php';

$headers = array(
    'Accept' => 'application/json',
);

$client = new \GuzzleHttp\Client();

// Define array of request body.
$request_body = array();

try {
    $response = $client->request('GET','/api/projects/{project_id}/dashboards/{id}/', array(
        'headers' => $headers,
        'json' => $request_body,
       )
    );
    print_r($response->getBody()->getContents());
 }
 catch (\GuzzleHttp\Exception\BadResponseException $e) {
    // handle exception or api errors.
    print_r($e->getMessage());
 }

 // ...

```

```java
URL obj = new URL("/api/projects/{project_id}/dashboards/{id}/");
HttpURLConnection con = (HttpURLConnection) obj.openConnection();
con.setRequestMethod("GET");
int responseCode = con.getResponseCode();
BufferedReader in = new BufferedReader(
    new InputStreamReader(con.getInputStream()));
String inputLine;
StringBuffer response = new StringBuffer();
while ((inputLine = in.readLine()) != null) {
    response.append(inputLine);
}
in.close();
System.out.println(response.toString());

```

```go
package main

import (
       "bytes"
       "net/http"
)

func main() {

    headers := map[string][]string{
        "Accept": []string{"application/json"},
    }

    data := bytes.NewBuffer([]byte{jsonReq})
    req, err := http.NewRequest("GET", "/api/projects/{project_id}/dashboards/{id}/", data)
    req.Header = headers

    client := &http.Client{}
    resp, err := client.Do(req)
    // ...
}

```

`GET /api/projects/{project_id}/dashboards/{id}/`

<h3 id="dashboards_retrieve-parameters">Parameters</h3>

|Name|In|Type|Required|Description|
|---|---|---|---|---|
|id|path|integer|true|A unique integer value identifying this dashboard.|
|project_id|path|string|true|Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/.|

> Example responses

> 200 Response

```json
{
  "id": 0,
  "name": "string",
  "description": "string",
  "pinned": true,
  "items": "string",
  "created_at": "2019-08-24T14:15:22Z",
  "created_by": {
    "id": 0,
    "uuid": "095be615-a8ad-4c33-8e9c-c7612fbf6c9f",
    "distinct_id": "string",
    "first_name": "string",
    "email": "user@example.com"
  },
  "is_shared": true,
  "share_token": "string",
  "deleted": true,
  "creation_mode": "default",
  "filters": {
    "property1": null,
    "property2": null
  },
  "tags": [
    "string"
  ]
}
```

<h3 id="dashboards_retrieve-responses">Responses</h3>

|Status|Meaning|Description|Schema|
|---|---|---|---|
|200|[OK](https://tools.ietf.org/html/rfc7231#section-6.3.1)|none|[Dashboard](#schemadashboard)|

<aside class="success">
This operation does not require authentication
</aside>

## dashboards_update

<a id="opIddashboards_update"></a>

> Code samples

```shell
# You can also use wget
curl -X PUT /api/projects/{project_id}/dashboards/{id}/ \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json'

```

```http
PUT /api/projects/{project_id}/dashboards/{id}/ HTTP/1.1

Content-Type: application/json
Accept: application/json

```

```javascript
const inputBody = '{
  "name": "string",
  "description": "string",
  "pinned": true,
  "is_shared": true,
  "share_token": "string",
  "deleted": true,
  "use_template": "string",
  "use_dashboard": 0,
  "filters": {
    "property1": null,
    "property2": null
  },
  "tags": [
    "string"
  ]
}';
const headers = {
  'Content-Type':'application/json',
  'Accept':'application/json'
};

fetch('/api/projects/{project_id}/dashboards/{id}/',
{
  method: 'PUT',
  body: inputBody,
  headers: headers
})
.then(function(res) {
    return res.json();
}).then(function(body) {
    console.log(body);
});

```

```ruby
require 'rest-client'
require 'json'

headers = {
  'Content-Type' => 'application/json',
  'Accept' => 'application/json'
}

result = RestClient.put '/api/projects/{project_id}/dashboards/{id}/',
  params: {
  }, headers: headers

p JSON.parse(result)

```

```python
import requests
headers = {
  'Content-Type': 'application/json',
  'Accept': 'application/json'
}

r = requests.put('/api/projects/{project_id}/dashboards/{id}/', headers = headers)

print(r.json())

```

```php
<?php

require 'vendor/autoload.php';

$headers = array(
    'Content-Type' => 'application/json',
    'Accept' => 'application/json',
);

$client = new \GuzzleHttp\Client();

// Define array of request body.
$request_body = array();

try {
    $response = $client->request('PUT','/api/projects/{project_id}/dashboards/{id}/', array(
        'headers' => $headers,
        'json' => $request_body,
       )
    );
    print_r($response->getBody()->getContents());
 }
 catch (\GuzzleHttp\Exception\BadResponseException $e) {
    // handle exception or api errors.
    print_r($e->getMessage());
 }

 // ...

```

```java
URL obj = new URL("/api/projects/{project_id}/dashboards/{id}/");
HttpURLConnection con = (HttpURLConnection) obj.openConnection();
con.setRequestMethod("PUT");
int responseCode = con.getResponseCode();
BufferedReader in = new BufferedReader(
    new InputStreamReader(con.getInputStream()));
String inputLine;
StringBuffer response = new StringBuffer();
while ((inputLine = in.readLine()) != null) {
    response.append(inputLine);
}
in.close();
System.out.println(response.toString());

```

```go
package main

import (
       "bytes"
       "net/http"
)

func main() {

    headers := map[string][]string{
        "Content-Type": []string{"application/json"},
        "Accept": []string{"application/json"},
    }

    data := bytes.NewBuffer([]byte{jsonReq})
    req, err := http.NewRequest("PUT", "/api/projects/{project_id}/dashboards/{id}/", data)
    req.Header = headers

    client := &http.Client{}
    resp, err := client.Do(req)
    // ...
}

```

`PUT /api/projects/{project_id}/dashboards/{id}/`

> Body parameter

```json
{
  "name": "string",
  "description": "string",
  "pinned": true,
  "is_shared": true,
  "share_token": "string",
  "deleted": true,
  "use_template": "string",
  "use_dashboard": 0,
  "filters": {
    "property1": null,
    "property2": null
  },
  "tags": [
    "string"
  ]
}
```

```yaml
name: string
description: string
pinned: true
is_shared: true
share_token: string
deleted: true
use_template: string
use_dashboard: 0
filters:
  ? property1
  ? property2
tags:
  - string

```

<h3 id="dashboards_update-parameters">Parameters</h3>

|Name|In|Type|Required|Description|
|---|---|---|---|---|
|id|path|integer|true|A unique integer value identifying this dashboard.|
|project_id|path|string|true|Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/.|
|body|body|[Dashboard](#schemadashboard)|false|none|

> Example responses

> 200 Response

```json
{
  "id": 0,
  "name": "string",
  "description": "string",
  "pinned": true,
  "items": "string",
  "created_at": "2019-08-24T14:15:22Z",
  "created_by": {
    "id": 0,
    "uuid": "095be615-a8ad-4c33-8e9c-c7612fbf6c9f",
    "distinct_id": "string",
    "first_name": "string",
    "email": "user@example.com"
  },
  "is_shared": true,
  "share_token": "string",
  "deleted": true,
  "creation_mode": "default",
  "filters": {
    "property1": null,
    "property2": null
  },
  "tags": [
    "string"
  ]
}
```

<h3 id="dashboards_update-responses">Responses</h3>

|Status|Meaning|Description|Schema|
|---|---|---|---|
|200|[OK](https://tools.ietf.org/html/rfc7231#section-6.3.1)|none|[Dashboard](#schemadashboard)|

<aside class="success">
This operation does not require authentication
</aside>

## dashboards_partial_update

<a id="opIddashboards_partial_update"></a>

> Code samples

```shell
# You can also use wget
curl -X PATCH /api/projects/{project_id}/dashboards/{id}/ \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json'

```

```http
PATCH /api/projects/{project_id}/dashboards/{id}/ HTTP/1.1

Content-Type: application/json
Accept: application/json

```

```javascript
const inputBody = '{
  "name": "string",
  "description": "string",
  "pinned": true,
  "is_shared": true,
  "share_token": "string",
  "deleted": true,
  "use_template": "string",
  "use_dashboard": 0,
  "filters": {
    "property1": null,
    "property2": null
  },
  "tags": [
    "string"
  ]
}';
const headers = {
  'Content-Type':'application/json',
  'Accept':'application/json'
};

fetch('/api/projects/{project_id}/dashboards/{id}/',
{
  method: 'PATCH',
  body: inputBody,
  headers: headers
})
.then(function(res) {
    return res.json();
}).then(function(body) {
    console.log(body);
});

```

```ruby
require 'rest-client'
require 'json'

headers = {
  'Content-Type' => 'application/json',
  'Accept' => 'application/json'
}

result = RestClient.patch '/api/projects/{project_id}/dashboards/{id}/',
  params: {
  }, headers: headers

p JSON.parse(result)

```

```python
import requests
headers = {
  'Content-Type': 'application/json',
  'Accept': 'application/json'
}

r = requests.patch('/api/projects/{project_id}/dashboards/{id}/', headers = headers)

print(r.json())

```

```php
<?php

require 'vendor/autoload.php';

$headers = array(
    'Content-Type' => 'application/json',
    'Accept' => 'application/json',
);

$client = new \GuzzleHttp\Client();

// Define array of request body.
$request_body = array();

try {
    $response = $client->request('PATCH','/api/projects/{project_id}/dashboards/{id}/', array(
        'headers' => $headers,
        'json' => $request_body,
       )
    );
    print_r($response->getBody()->getContents());
 }
 catch (\GuzzleHttp\Exception\BadResponseException $e) {
    // handle exception or api errors.
    print_r($e->getMessage());
 }

 // ...

```

```java
URL obj = new URL("/api/projects/{project_id}/dashboards/{id}/");
HttpURLConnection con = (HttpURLConnection) obj.openConnection();
con.setRequestMethod("PATCH");
int responseCode = con.getResponseCode();
BufferedReader in = new BufferedReader(
    new InputStreamReader(con.getInputStream()));
String inputLine;
StringBuffer response = new StringBuffer();
while ((inputLine = in.readLine()) != null) {
    response.append(inputLine);
}
in.close();
System.out.println(response.toString());

```

```go
package main

import (
       "bytes"
       "net/http"
)

func main() {

    headers := map[string][]string{
        "Content-Type": []string{"application/json"},
        "Accept": []string{"application/json"},
    }

    data := bytes.NewBuffer([]byte{jsonReq})
    req, err := http.NewRequest("PATCH", "/api/projects/{project_id}/dashboards/{id}/", data)
    req.Header = headers

    client := &http.Client{}
    resp, err := client.Do(req)
    // ...
}

```

`PATCH /api/projects/{project_id}/dashboards/{id}/`

> Body parameter

```json
{
  "name": "string",
  "description": "string",
  "pinned": true,
  "is_shared": true,
  "share_token": "string",
  "deleted": true,
  "use_template": "string",
  "use_dashboard": 0,
  "filters": {
    "property1": null,
    "property2": null
  },
  "tags": [
    "string"
  ]
}
```

```yaml
name: string
description: string
pinned: true
is_shared: true
share_token: string
deleted: true
use_template: string
use_dashboard: 0
filters:
  ? property1
  ? property2
tags:
  - string

```

<h3 id="dashboards_partial_update-parameters">Parameters</h3>

|Name|In|Type|Required|Description|
|---|---|---|---|---|
|id|path|integer|true|A unique integer value identifying this dashboard.|
|project_id|path|string|true|Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/.|
|body|body|[PatchedDashboard](#schemapatcheddashboard)|false|none|

> Example responses

> 200 Response

```json
{
  "id": 0,
  "name": "string",
  "description": "string",
  "pinned": true,
  "items": "string",
  "created_at": "2019-08-24T14:15:22Z",
  "created_by": {
    "id": 0,
    "uuid": "095be615-a8ad-4c33-8e9c-c7612fbf6c9f",
    "distinct_id": "string",
    "first_name": "string",
    "email": "user@example.com"
  },
  "is_shared": true,
  "share_token": "string",
  "deleted": true,
  "creation_mode": "default",
  "filters": {
    "property1": null,
    "property2": null
  },
  "tags": [
    "string"
  ]
}
```

<h3 id="dashboards_partial_update-responses">Responses</h3>

|Status|Meaning|Description|Schema|
|---|---|---|---|
|200|[OK](https://tools.ietf.org/html/rfc7231#section-6.3.1)|none|[Dashboard](#schemadashboard)|

<aside class="success">
This operation does not require authentication
</aside>

## dashboards_destroy

<a id="opIddashboards_destroy"></a>

> Code samples

```shell
# You can also use wget
curl -X DELETE /api/projects/{project_id}/dashboards/{id}/

```

```http
DELETE /api/projects/{project_id}/dashboards/{id}/ HTTP/1.1

```

```javascript

fetch('/api/projects/{project_id}/dashboards/{id}/',
{
  method: 'DELETE'

})
.then(function(res) {
    return res.json();
}).then(function(body) {
    console.log(body);
});

```

```ruby
require 'rest-client'
require 'json'

result = RestClient.delete '/api/projects/{project_id}/dashboards/{id}/',
  params: {
  }

p JSON.parse(result)

```

```python
import requests

r = requests.delete('/api/projects/{project_id}/dashboards/{id}/')

print(r.json())

```

```php
<?php

require 'vendor/autoload.php';

$client = new \GuzzleHttp\Client();

// Define array of request body.
$request_body = array();

try {
    $response = $client->request('DELETE','/api/projects/{project_id}/dashboards/{id}/', array(
        'headers' => $headers,
        'json' => $request_body,
       )
    );
    print_r($response->getBody()->getContents());
 }
 catch (\GuzzleHttp\Exception\BadResponseException $e) {
    // handle exception or api errors.
    print_r($e->getMessage());
 }

 // ...

```

```java
URL obj = new URL("/api/projects/{project_id}/dashboards/{id}/");
HttpURLConnection con = (HttpURLConnection) obj.openConnection();
con.setRequestMethod("DELETE");
int responseCode = con.getResponseCode();
BufferedReader in = new BufferedReader(
    new InputStreamReader(con.getInputStream()));
String inputLine;
StringBuffer response = new StringBuffer();
while ((inputLine = in.readLine()) != null) {
    response.append(inputLine);
}
in.close();
System.out.println(response.toString());

```

```go
package main

import (
       "bytes"
       "net/http"
)

func main() {

    data := bytes.NewBuffer([]byte{jsonReq})
    req, err := http.NewRequest("DELETE", "/api/projects/{project_id}/dashboards/{id}/", data)
    req.Header = headers

    client := &http.Client{}
    resp, err := client.Do(req)
    // ...
}

```

`DELETE /api/projects/{project_id}/dashboards/{id}/`

<h3 id="dashboards_destroy-parameters">Parameters</h3>

|Name|In|Type|Required|Description|
|---|---|---|---|---|
|id|path|integer|true|A unique integer value identifying this dashboard.|
|project_id|path|string|true|Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/.|

<h3 id="dashboards_destroy-responses">Responses</h3>

|Status|Meaning|Description|Schema|
|---|---|---|---|
|204|[No Content](https://tools.ietf.org/html/rfc7231#section-6.3.5)|No response body|None|

<aside class="success">
This operation does not require authentication
</aside>

<h1 id="-event_definitions">event_definitions</h1>

## event_definitions_retrieve

<a id="opIdevent_definitions_retrieve"></a>

> Code samples

```shell
# You can also use wget
curl -X GET /api/projects/{project_id}/event_definitions/

```

```http
GET /api/projects/{project_id}/event_definitions/ HTTP/1.1

```

```javascript

fetch('/api/projects/{project_id}/event_definitions/',
{
  method: 'GET'

})
.then(function(res) {
    return res.json();
}).then(function(body) {
    console.log(body);
});

```

```ruby
require 'rest-client'
require 'json'

result = RestClient.get '/api/projects/{project_id}/event_definitions/',
  params: {
  }

p JSON.parse(result)

```

```python
import requests

r = requests.get('/api/projects/{project_id}/event_definitions/')

print(r.json())

```

```php
<?php

require 'vendor/autoload.php';

$client = new \GuzzleHttp\Client();

// Define array of request body.
$request_body = array();

try {
    $response = $client->request('GET','/api/projects/{project_id}/event_definitions/', array(
        'headers' => $headers,
        'json' => $request_body,
       )
    );
    print_r($response->getBody()->getContents());
 }
 catch (\GuzzleHttp\Exception\BadResponseException $e) {
    // handle exception or api errors.
    print_r($e->getMessage());
 }

 // ...

```

```java
URL obj = new URL("/api/projects/{project_id}/event_definitions/");
HttpURLConnection con = (HttpURLConnection) obj.openConnection();
con.setRequestMethod("GET");
int responseCode = con.getResponseCode();
BufferedReader in = new BufferedReader(
    new InputStreamReader(con.getInputStream()));
String inputLine;
StringBuffer response = new StringBuffer();
while ((inputLine = in.readLine()) != null) {
    response.append(inputLine);
}
in.close();
System.out.println(response.toString());

```

```go
package main

import (
       "bytes"
       "net/http"
)

func main() {

    data := bytes.NewBuffer([]byte{jsonReq})
    req, err := http.NewRequest("GET", "/api/projects/{project_id}/event_definitions/", data)
    req.Header = headers

    client := &http.Client{}
    resp, err := client.Do(req)
    // ...
}

```

`GET /api/projects/{project_id}/event_definitions/`

<h3 id="event_definitions_retrieve-parameters">Parameters</h3>

|Name|In|Type|Required|Description|
|---|---|---|---|---|
|project_id|path|string|true|Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/.|

<h3 id="event_definitions_retrieve-responses">Responses</h3>

|Status|Meaning|Description|Schema|
|---|---|---|---|
|200|[OK](https://tools.ietf.org/html/rfc7231#section-6.3.1)|No response body|None|

<aside class="success">
This operation does not require authentication
</aside>

## event_definitions_retrieve_2

<a id="opIdevent_definitions_retrieve_2"></a>

> Code samples

```shell
# You can also use wget
curl -X GET /api/projects/{project_id}/event_definitions/{id}/

```

```http
GET /api/projects/{project_id}/event_definitions/{id}/ HTTP/1.1

```

```javascript

fetch('/api/projects/{project_id}/event_definitions/{id}/',
{
  method: 'GET'

})
.then(function(res) {
    return res.json();
}).then(function(body) {
    console.log(body);
});

```

```ruby
require 'rest-client'
require 'json'

result = RestClient.get '/api/projects/{project_id}/event_definitions/{id}/',
  params: {
  }

p JSON.parse(result)

```

```python
import requests

r = requests.get('/api/projects/{project_id}/event_definitions/{id}/')

print(r.json())

```

```php
<?php

require 'vendor/autoload.php';

$client = new \GuzzleHttp\Client();

// Define array of request body.
$request_body = array();

try {
    $response = $client->request('GET','/api/projects/{project_id}/event_definitions/{id}/', array(
        'headers' => $headers,
        'json' => $request_body,
       )
    );
    print_r($response->getBody()->getContents());
 }
 catch (\GuzzleHttp\Exception\BadResponseException $e) {
    // handle exception or api errors.
    print_r($e->getMessage());
 }

 // ...

```

```java
URL obj = new URL("/api/projects/{project_id}/event_definitions/{id}/");
HttpURLConnection con = (HttpURLConnection) obj.openConnection();
con.setRequestMethod("GET");
int responseCode = con.getResponseCode();
BufferedReader in = new BufferedReader(
    new InputStreamReader(con.getInputStream()));
String inputLine;
StringBuffer response = new StringBuffer();
while ((inputLine = in.readLine()) != null) {
    response.append(inputLine);
}
in.close();
System.out.println(response.toString());

```

```go
package main

import (
       "bytes"
       "net/http"
)

func main() {

    data := bytes.NewBuffer([]byte{jsonReq})
    req, err := http.NewRequest("GET", "/api/projects/{project_id}/event_definitions/{id}/", data)
    req.Header = headers

    client := &http.Client{}
    resp, err := client.Do(req)
    // ...
}

```

`GET /api/projects/{project_id}/event_definitions/{id}/`

<h3 id="event_definitions_retrieve_2-parameters">Parameters</h3>

|Name|In|Type|Required|Description|
|---|---|---|---|---|
|id|path|string|true|none|
|project_id|path|string|true|Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/.|

<h3 id="event_definitions_retrieve_2-responses">Responses</h3>

|Status|Meaning|Description|Schema|
|---|---|---|---|
|200|[OK](https://tools.ietf.org/html/rfc7231#section-6.3.1)|No response body|None|

<aside class="success">
This operation does not require authentication
</aside>

## event_definitions_update

<a id="opIdevent_definitions_update"></a>

> Code samples

```shell
# You can also use wget
curl -X PUT /api/projects/{project_id}/event_definitions/{id}/

```

```http
PUT /api/projects/{project_id}/event_definitions/{id}/ HTTP/1.1

```

```javascript

fetch('/api/projects/{project_id}/event_definitions/{id}/',
{
  method: 'PUT'

})
.then(function(res) {
    return res.json();
}).then(function(body) {
    console.log(body);
});

```

```ruby
require 'rest-client'
require 'json'

result = RestClient.put '/api/projects/{project_id}/event_definitions/{id}/',
  params: {
  }

p JSON.parse(result)

```

```python
import requests

r = requests.put('/api/projects/{project_id}/event_definitions/{id}/')

print(r.json())

```

```php
<?php

require 'vendor/autoload.php';

$client = new \GuzzleHttp\Client();

// Define array of request body.
$request_body = array();

try {
    $response = $client->request('PUT','/api/projects/{project_id}/event_definitions/{id}/', array(
        'headers' => $headers,
        'json' => $request_body,
       )
    );
    print_r($response->getBody()->getContents());
 }
 catch (\GuzzleHttp\Exception\BadResponseException $e) {
    // handle exception or api errors.
    print_r($e->getMessage());
 }

 // ...

```

```java
URL obj = new URL("/api/projects/{project_id}/event_definitions/{id}/");
HttpURLConnection con = (HttpURLConnection) obj.openConnection();
con.setRequestMethod("PUT");
int responseCode = con.getResponseCode();
BufferedReader in = new BufferedReader(
    new InputStreamReader(con.getInputStream()));
String inputLine;
StringBuffer response = new StringBuffer();
while ((inputLine = in.readLine()) != null) {
    response.append(inputLine);
}
in.close();
System.out.println(response.toString());

```

```go
package main

import (
       "bytes"
       "net/http"
)

func main() {

    data := bytes.NewBuffer([]byte{jsonReq})
    req, err := http.NewRequest("PUT", "/api/projects/{project_id}/event_definitions/{id}/", data)
    req.Header = headers

    client := &http.Client{}
    resp, err := client.Do(req)
    // ...
}

```

`PUT /api/projects/{project_id}/event_definitions/{id}/`

<h3 id="event_definitions_update-parameters">Parameters</h3>

|Name|In|Type|Required|Description|
|---|---|---|---|---|
|id|path|string|true|none|
|project_id|path|string|true|Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/.|

<h3 id="event_definitions_update-responses">Responses</h3>

|Status|Meaning|Description|Schema|
|---|---|---|---|
|200|[OK](https://tools.ietf.org/html/rfc7231#section-6.3.1)|No response body|None|

<aside class="success">
This operation does not require authentication
</aside>

## event_definitions_partial_update

<a id="opIdevent_definitions_partial_update"></a>

> Code samples

```shell
# You can also use wget
curl -X PATCH /api/projects/{project_id}/event_definitions/{id}/

```

```http
PATCH /api/projects/{project_id}/event_definitions/{id}/ HTTP/1.1

```

```javascript

fetch('/api/projects/{project_id}/event_definitions/{id}/',
{
  method: 'PATCH'

})
.then(function(res) {
    return res.json();
}).then(function(body) {
    console.log(body);
});

```

```ruby
require 'rest-client'
require 'json'

result = RestClient.patch '/api/projects/{project_id}/event_definitions/{id}/',
  params: {
  }

p JSON.parse(result)

```

```python
import requests

r = requests.patch('/api/projects/{project_id}/event_definitions/{id}/')

print(r.json())

```

```php
<?php

require 'vendor/autoload.php';

$client = new \GuzzleHttp\Client();

// Define array of request body.
$request_body = array();

try {
    $response = $client->request('PATCH','/api/projects/{project_id}/event_definitions/{id}/', array(
        'headers' => $headers,
        'json' => $request_body,
       )
    );
    print_r($response->getBody()->getContents());
 }
 catch (\GuzzleHttp\Exception\BadResponseException $e) {
    // handle exception or api errors.
    print_r($e->getMessage());
 }

 // ...

```

```java
URL obj = new URL("/api/projects/{project_id}/event_definitions/{id}/");
HttpURLConnection con = (HttpURLConnection) obj.openConnection();
con.setRequestMethod("PATCH");
int responseCode = con.getResponseCode();
BufferedReader in = new BufferedReader(
    new InputStreamReader(con.getInputStream()));
String inputLine;
StringBuffer response = new StringBuffer();
while ((inputLine = in.readLine()) != null) {
    response.append(inputLine);
}
in.close();
System.out.println(response.toString());

```

```go
package main

import (
       "bytes"
       "net/http"
)

func main() {

    data := bytes.NewBuffer([]byte{jsonReq})
    req, err := http.NewRequest("PATCH", "/api/projects/{project_id}/event_definitions/{id}/", data)
    req.Header = headers

    client := &http.Client{}
    resp, err := client.Do(req)
    // ...
}

```

`PATCH /api/projects/{project_id}/event_definitions/{id}/`

<h3 id="event_definitions_partial_update-parameters">Parameters</h3>

|Name|In|Type|Required|Description|
|---|---|---|---|---|
|id|path|string|true|none|
|project_id|path|string|true|Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/.|

<h3 id="event_definitions_partial_update-responses">Responses</h3>

|Status|Meaning|Description|Schema|
|---|---|---|---|
|200|[OK](https://tools.ietf.org/html/rfc7231#section-6.3.1)|No response body|None|

<aside class="success">
This operation does not require authentication
</aside>

<h1 id="-events">events</h1>

## events_list

<a id="opIdevents_list"></a>

> Code samples

```shell
# You can also use wget
curl -X GET /api/projects/{project_id}/events/ \
  -H 'Accept: application/json'

```

```http
GET /api/projects/{project_id}/events/ HTTP/1.1

Accept: application/json

```

```javascript

const headers = {
  'Accept':'application/json'
};

fetch('/api/projects/{project_id}/events/',
{
  method: 'GET',

  headers: headers
})
.then(function(res) {
    return res.json();
}).then(function(body) {
    console.log(body);
});

```

```ruby
require 'rest-client'
require 'json'

headers = {
  'Accept' => 'application/json'
}

result = RestClient.get '/api/projects/{project_id}/events/',
  params: {
  }, headers: headers

p JSON.parse(result)

```

```python
import requests
headers = {
  'Accept': 'application/json'
}

r = requests.get('/api/projects/{project_id}/events/', headers = headers)

print(r.json())

```

```php
<?php

require 'vendor/autoload.php';

$headers = array(
    'Accept' => 'application/json',
);

$client = new \GuzzleHttp\Client();

// Define array of request body.
$request_body = array();

try {
    $response = $client->request('GET','/api/projects/{project_id}/events/', array(
        'headers' => $headers,
        'json' => $request_body,
       )
    );
    print_r($response->getBody()->getContents());
 }
 catch (\GuzzleHttp\Exception\BadResponseException $e) {
    // handle exception or api errors.
    print_r($e->getMessage());
 }

 // ...

```

```java
URL obj = new URL("/api/projects/{project_id}/events/");
HttpURLConnection con = (HttpURLConnection) obj.openConnection();
con.setRequestMethod("GET");
int responseCode = con.getResponseCode();
BufferedReader in = new BufferedReader(
    new InputStreamReader(con.getInputStream()));
String inputLine;
StringBuffer response = new StringBuffer();
while ((inputLine = in.readLine()) != null) {
    response.append(inputLine);
}
in.close();
System.out.println(response.toString());

```

```go
package main

import (
       "bytes"
       "net/http"
)

func main() {

    headers := map[string][]string{
        "Accept": []string{"application/json"},
    }

    data := bytes.NewBuffer([]byte{jsonReq})
    req, err := http.NewRequest("GET", "/api/projects/{project_id}/events/", data)
    req.Header = headers

    client := &http.Client{}
    resp, err := client.Do(req)
    // ...
}

```

`GET /api/projects/{project_id}/events/`

<h3 id="events_list-parameters">Parameters</h3>

|Name|In|Type|Required|Description|
|---|---|---|---|---|
|format|query|string|false|none|
|limit|query|integer|false|Number of results to return per page.|
|offset|query|integer|false|The initial index from which to return the results.|
|project_id|path|string|true|Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/.|
|properties|query|array[object]|false|none|

#### Enumerated Values

|Parameter|Value|
|---|---|
|format|csv|
|format|json|

> Example responses

> 200 Response

```json
{
  "count": 123,
  "next": "http://api.example.org/accounts/?offset=400&limit=100",
  "previous": "http://api.example.org/accounts/?offset=200&limit=100",
  "results": [
    {
      "id": "string",
      "distinct_id": "string",
      "properties": "string",
      "event": "string",
      "timestamp": "string",
      "person": "string",
      "elements": "string",
      "elements_chain": "string"
    }
  ]
}
```

<h3 id="events_list-responses">Responses</h3>

|Status|Meaning|Description|Schema|
|---|---|---|---|
|200|[OK](https://tools.ietf.org/html/rfc7231#section-6.3.1)|none|[PaginatedClickhouseEventList](#schemapaginatedclickhouseeventlist)|

<aside class="success">
This operation does not require authentication
</aside>

## events_retrieve

<a id="opIdevents_retrieve"></a>

> Code samples

```shell
# You can also use wget
curl -X GET /api/projects/{project_id}/events/{id}/ \
  -H 'Accept: application/json'

```

```http
GET /api/projects/{project_id}/events/{id}/ HTTP/1.1

Accept: application/json

```

```javascript

const headers = {
  'Accept':'application/json'
};

fetch('/api/projects/{project_id}/events/{id}/',
{
  method: 'GET',

  headers: headers
})
.then(function(res) {
    return res.json();
}).then(function(body) {
    console.log(body);
});

```

```ruby
require 'rest-client'
require 'json'

headers = {
  'Accept' => 'application/json'
}

result = RestClient.get '/api/projects/{project_id}/events/{id}/',
  params: {
  }, headers: headers

p JSON.parse(result)

```

```python
import requests
headers = {
  'Accept': 'application/json'
}

r = requests.get('/api/projects/{project_id}/events/{id}/', headers = headers)

print(r.json())

```

```php
<?php

require 'vendor/autoload.php';

$headers = array(
    'Accept' => 'application/json',
);

$client = new \GuzzleHttp\Client();

// Define array of request body.
$request_body = array();

try {
    $response = $client->request('GET','/api/projects/{project_id}/events/{id}/', array(
        'headers' => $headers,
        'json' => $request_body,
       )
    );
    print_r($response->getBody()->getContents());
 }
 catch (\GuzzleHttp\Exception\BadResponseException $e) {
    // handle exception or api errors.
    print_r($e->getMessage());
 }

 // ...

```

```java
URL obj = new URL("/api/projects/{project_id}/events/{id}/");
HttpURLConnection con = (HttpURLConnection) obj.openConnection();
con.setRequestMethod("GET");
int responseCode = con.getResponseCode();
BufferedReader in = new BufferedReader(
    new InputStreamReader(con.getInputStream()));
String inputLine;
StringBuffer response = new StringBuffer();
while ((inputLine = in.readLine()) != null) {
    response.append(inputLine);
}
in.close();
System.out.println(response.toString());

```

```go
package main

import (
       "bytes"
       "net/http"
)

func main() {

    headers := map[string][]string{
        "Accept": []string{"application/json"},
    }

    data := bytes.NewBuffer([]byte{jsonReq})
    req, err := http.NewRequest("GET", "/api/projects/{project_id}/events/{id}/", data)
    req.Header = headers

    client := &http.Client{}
    resp, err := client.Do(req)
    // ...
}

```

`GET /api/projects/{project_id}/events/{id}/`

<h3 id="events_retrieve-parameters">Parameters</h3>

|Name|In|Type|Required|Description|
|---|---|---|---|---|
|format|query|string|false|none|
|id|path|integer|true|A unique integer value identifying this event.|
|project_id|path|string|true|Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/.|

#### Enumerated Values

|Parameter|Value|
|---|---|
|format|csv|
|format|json|

> Example responses

> 200 Response

```json
{
  "id": "string",
  "distinct_id": "string",
  "properties": "string",
  "event": "string",
  "timestamp": "string",
  "person": "string",
  "elements": "string",
  "elements_chain": "string"
}
```

<h3 id="events_retrieve-responses">Responses</h3>

|Status|Meaning|Description|Schema|
|---|---|---|---|
|200|[OK](https://tools.ietf.org/html/rfc7231#section-6.3.1)|none|[ClickhouseEvent](#schemaclickhouseevent)|

<aside class="success">
This operation does not require authentication
</aside>

## events_values_retrieve

<a id="opIdevents_values_retrieve"></a>

> Code samples

```shell
# You can also use wget
curl -X GET /api/projects/{project_id}/events/values/ \
  -H 'Accept: application/json'

```

```http
GET /api/projects/{project_id}/events/values/ HTTP/1.1

Accept: application/json

```

```javascript

const headers = {
  'Accept':'application/json'
};

fetch('/api/projects/{project_id}/events/values/',
{
  method: 'GET',

  headers: headers
})
.then(function(res) {
    return res.json();
}).then(function(body) {
    console.log(body);
});

```

```ruby
require 'rest-client'
require 'json'

headers = {
  'Accept' => 'application/json'
}

result = RestClient.get '/api/projects/{project_id}/events/values/',
  params: {
  }, headers: headers

p JSON.parse(result)

```

```python
import requests
headers = {
  'Accept': 'application/json'
}

r = requests.get('/api/projects/{project_id}/events/values/', headers = headers)

print(r.json())

```

```php
<?php

require 'vendor/autoload.php';

$headers = array(
    'Accept' => 'application/json',
);

$client = new \GuzzleHttp\Client();

// Define array of request body.
$request_body = array();

try {
    $response = $client->request('GET','/api/projects/{project_id}/events/values/', array(
        'headers' => $headers,
        'json' => $request_body,
       )
    );
    print_r($response->getBody()->getContents());
 }
 catch (\GuzzleHttp\Exception\BadResponseException $e) {
    // handle exception or api errors.
    print_r($e->getMessage());
 }

 // ...

```

```java
URL obj = new URL("/api/projects/{project_id}/events/values/");
HttpURLConnection con = (HttpURLConnection) obj.openConnection();
con.setRequestMethod("GET");
int responseCode = con.getResponseCode();
BufferedReader in = new BufferedReader(
    new InputStreamReader(con.getInputStream()));
String inputLine;
StringBuffer response = new StringBuffer();
while ((inputLine = in.readLine()) != null) {
    response.append(inputLine);
}
in.close();
System.out.println(response.toString());

```

```go
package main

import (
       "bytes"
       "net/http"
)

func main() {

    headers := map[string][]string{
        "Accept": []string{"application/json"},
    }

    data := bytes.NewBuffer([]byte{jsonReq})
    req, err := http.NewRequest("GET", "/api/projects/{project_id}/events/values/", data)
    req.Header = headers

    client := &http.Client{}
    resp, err := client.Do(req)
    // ...
}

```

`GET /api/projects/{project_id}/events/values/`

<h3 id="events_values_retrieve-parameters">Parameters</h3>

|Name|In|Type|Required|Description|
|---|---|---|---|---|
|format|query|string|false|none|
|project_id|path|string|true|Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/.|

#### Enumerated Values

|Parameter|Value|
|---|---|
|format|csv|
|format|json|

> Example responses

> 200 Response

```json
{
  "id": "string",
  "distinct_id": "string",
  "properties": "string",
  "event": "string",
  "timestamp": "string",
  "person": "string",
  "elements": "string",
  "elements_chain": "string"
}
```

<h3 id="events_values_retrieve-responses">Responses</h3>

|Status|Meaning|Description|Schema|
|---|---|---|---|
|200|[OK](https://tools.ietf.org/html/rfc7231#section-6.3.1)|none|[ClickhouseEvent](#schemaclickhouseevent)|

<aside class="success">
This operation does not require authentication
</aside>

<h1 id="-experiments">experiments</h1>

## experiments_list

<a id="opIdexperiments_list"></a>

> Code samples

```shell
# You can also use wget
curl -X GET /api/projects/{project_id}/experiments/ \
  -H 'Accept: application/json'

```

```http
GET /api/projects/{project_id}/experiments/ HTTP/1.1

Accept: application/json

```

```javascript

const headers = {
  'Accept':'application/json'
};

fetch('/api/projects/{project_id}/experiments/',
{
  method: 'GET',

  headers: headers
})
.then(function(res) {
    return res.json();
}).then(function(body) {
    console.log(body);
});

```

```ruby
require 'rest-client'
require 'json'

headers = {
  'Accept' => 'application/json'
}

result = RestClient.get '/api/projects/{project_id}/experiments/',
  params: {
  }, headers: headers

p JSON.parse(result)

```

```python
import requests
headers = {
  'Accept': 'application/json'
}

r = requests.get('/api/projects/{project_id}/experiments/', headers = headers)

print(r.json())

```

```php
<?php

require 'vendor/autoload.php';

$headers = array(
    'Accept' => 'application/json',
);

$client = new \GuzzleHttp\Client();

// Define array of request body.
$request_body = array();

try {
    $response = $client->request('GET','/api/projects/{project_id}/experiments/', array(
        'headers' => $headers,
        'json' => $request_body,
       )
    );
    print_r($response->getBody()->getContents());
 }
 catch (\GuzzleHttp\Exception\BadResponseException $e) {
    // handle exception or api errors.
    print_r($e->getMessage());
 }

 // ...

```

```java
URL obj = new URL("/api/projects/{project_id}/experiments/");
HttpURLConnection con = (HttpURLConnection) obj.openConnection();
con.setRequestMethod("GET");
int responseCode = con.getResponseCode();
BufferedReader in = new BufferedReader(
    new InputStreamReader(con.getInputStream()));
String inputLine;
StringBuffer response = new StringBuffer();
while ((inputLine = in.readLine()) != null) {
    response.append(inputLine);
}
in.close();
System.out.println(response.toString());

```

```go
package main

import (
       "bytes"
       "net/http"
)

func main() {

    headers := map[string][]string{
        "Accept": []string{"application/json"},
    }

    data := bytes.NewBuffer([]byte{jsonReq})
    req, err := http.NewRequest("GET", "/api/projects/{project_id}/experiments/", data)
    req.Header = headers

    client := &http.Client{}
    resp, err := client.Do(req)
    // ...
}

```

`GET /api/projects/{project_id}/experiments/`

<h3 id="experiments_list-parameters">Parameters</h3>

|Name|In|Type|Required|Description|
|---|---|---|---|---|
|limit|query|integer|false|Number of results to return per page.|
|offset|query|integer|false|The initial index from which to return the results.|
|project_id|path|string|true|Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/.|

> Example responses

> 200 Response

```json
{
  "count": 123,
  "next": "http://api.example.org/accounts/?offset=400&limit=100",
  "previous": "http://api.example.org/accounts/?offset=200&limit=100",
  "results": [
    {
      "id": 0,
      "name": "string",
      "description": "string",
      "start_date": "2019-08-24T14:15:22Z",
      "end_date": "2019-08-24T14:15:22Z",
      "feature_flag_key": "string",
      "parameters": {
        "property1": null,
        "property2": null
      },
      "secondary_metrics": {
        "property1": null,
        "property2": null
      },
      "filters": {
        "property1": null,
        "property2": null
      },
      "archived": true,
      "created_by": {
        "id": 0,
        "uuid": "095be615-a8ad-4c33-8e9c-c7612fbf6c9f",
        "distinct_id": "string",
        "first_name": "string",
        "email": "user@example.com"
      },
      "created_at": "2019-08-24T14:15:22Z",
      "updated_at": "2019-08-24T14:15:22Z"
    }
  ]
}
```

<h3 id="experiments_list-responses">Responses</h3>

|Status|Meaning|Description|Schema|
|---|---|---|---|
|200|[OK](https://tools.ietf.org/html/rfc7231#section-6.3.1)|none|[PaginatedExperimentList](#schemapaginatedexperimentlist)|

<aside class="success">
This operation does not require authentication
</aside>

## experiments_create

<a id="opIdexperiments_create"></a>

> Code samples

```shell
# You can also use wget
curl -X POST /api/projects/{project_id}/experiments/ \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json'

```

```http
POST /api/projects/{project_id}/experiments/ HTTP/1.1

Content-Type: application/json
Accept: application/json

```

```javascript
const inputBody = '{
  "name": "string",
  "description": "string",
  "start_date": "2019-08-24T14:15:22Z",
  "end_date": "2019-08-24T14:15:22Z",
  "feature_flag_key": "string",
  "parameters": {
    "property1": null,
    "property2": null
  },
  "secondary_metrics": {
    "property1": null,
    "property2": null
  },
  "filters": {
    "property1": null,
    "property2": null
  },
  "archived": true
}';
const headers = {
  'Content-Type':'application/json',
  'Accept':'application/json'
};

fetch('/api/projects/{project_id}/experiments/',
{
  method: 'POST',
  body: inputBody,
  headers: headers
})
.then(function(res) {
    return res.json();
}).then(function(body) {
    console.log(body);
});

```

```ruby
require 'rest-client'
require 'json'

headers = {
  'Content-Type' => 'application/json',
  'Accept' => 'application/json'
}

result = RestClient.post '/api/projects/{project_id}/experiments/',
  params: {
  }, headers: headers

p JSON.parse(result)

```

```python
import requests
headers = {
  'Content-Type': 'application/json',
  'Accept': 'application/json'
}

r = requests.post('/api/projects/{project_id}/experiments/', headers = headers)

print(r.json())

```

```php
<?php

require 'vendor/autoload.php';

$headers = array(
    'Content-Type' => 'application/json',
    'Accept' => 'application/json',
);

$client = new \GuzzleHttp\Client();

// Define array of request body.
$request_body = array();

try {
    $response = $client->request('POST','/api/projects/{project_id}/experiments/', array(
        'headers' => $headers,
        'json' => $request_body,
       )
    );
    print_r($response->getBody()->getContents());
 }
 catch (\GuzzleHttp\Exception\BadResponseException $e) {
    // handle exception or api errors.
    print_r($e->getMessage());
 }

 // ...

```

```java
URL obj = new URL("/api/projects/{project_id}/experiments/");
HttpURLConnection con = (HttpURLConnection) obj.openConnection();
con.setRequestMethod("POST");
int responseCode = con.getResponseCode();
BufferedReader in = new BufferedReader(
    new InputStreamReader(con.getInputStream()));
String inputLine;
StringBuffer response = new StringBuffer();
while ((inputLine = in.readLine()) != null) {
    response.append(inputLine);
}
in.close();
System.out.println(response.toString());

```

```go
package main

import (
       "bytes"
       "net/http"
)

func main() {

    headers := map[string][]string{
        "Content-Type": []string{"application/json"},
        "Accept": []string{"application/json"},
    }

    data := bytes.NewBuffer([]byte{jsonReq})
    req, err := http.NewRequest("POST", "/api/projects/{project_id}/experiments/", data)
    req.Header = headers

    client := &http.Client{}
    resp, err := client.Do(req)
    // ...
}

```

`POST /api/projects/{project_id}/experiments/`

> Body parameter

```json
{
  "name": "string",
  "description": "string",
  "start_date": "2019-08-24T14:15:22Z",
  "end_date": "2019-08-24T14:15:22Z",
  "feature_flag_key": "string",
  "parameters": {
    "property1": null,
    "property2": null
  },
  "secondary_metrics": {
    "property1": null,
    "property2": null
  },
  "filters": {
    "property1": null,
    "property2": null
  },
  "archived": true
}
```

```yaml
name: string
description: string
start_date: 2019-08-24T14:15:22Z
end_date: 2019-08-24T14:15:22Z
feature_flag_key: string
parameters:
  ? property1
  ? property2
secondary_metrics:
  ? property1
  ? property2
filters:
  ? property1
  ? property2
archived: true

```

<h3 id="experiments_create-parameters">Parameters</h3>

|Name|In|Type|Required|Description|
|---|---|---|---|---|
|project_id|path|string|true|Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/.|
|body|body|[Experiment](#schemaexperiment)|true|none|

> Example responses

> 201 Response

```json
{
  "id": 0,
  "name": "string",
  "description": "string",
  "start_date": "2019-08-24T14:15:22Z",
  "end_date": "2019-08-24T14:15:22Z",
  "feature_flag_key": "string",
  "parameters": {
    "property1": null,
    "property2": null
  },
  "secondary_metrics": {
    "property1": null,
    "property2": null
  },
  "filters": {
    "property1": null,
    "property2": null
  },
  "archived": true,
  "created_by": {
    "id": 0,
    "uuid": "095be615-a8ad-4c33-8e9c-c7612fbf6c9f",
    "distinct_id": "string",
    "first_name": "string",
    "email": "user@example.com"
  },
  "created_at": "2019-08-24T14:15:22Z",
  "updated_at": "2019-08-24T14:15:22Z"
}
```

<h3 id="experiments_create-responses">Responses</h3>

|Status|Meaning|Description|Schema|
|---|---|---|---|
|201|[Created](https://tools.ietf.org/html/rfc7231#section-6.3.2)|none|[Experiment](#schemaexperiment)|

<aside class="success">
This operation does not require authentication
</aside>

## experiments_retrieve

<a id="opIdexperiments_retrieve"></a>

> Code samples

```shell
# You can also use wget
curl -X GET /api/projects/{project_id}/experiments/{id}/ \
  -H 'Accept: application/json'

```

```http
GET /api/projects/{project_id}/experiments/{id}/ HTTP/1.1

Accept: application/json

```

```javascript

const headers = {
  'Accept':'application/json'
};

fetch('/api/projects/{project_id}/experiments/{id}/',
{
  method: 'GET',

  headers: headers
})
.then(function(res) {
    return res.json();
}).then(function(body) {
    console.log(body);
});

```

```ruby
require 'rest-client'
require 'json'

headers = {
  'Accept' => 'application/json'
}

result = RestClient.get '/api/projects/{project_id}/experiments/{id}/',
  params: {
  }, headers: headers

p JSON.parse(result)

```

```python
import requests
headers = {
  'Accept': 'application/json'
}

r = requests.get('/api/projects/{project_id}/experiments/{id}/', headers = headers)

print(r.json())

```

```php
<?php

require 'vendor/autoload.php';

$headers = array(
    'Accept' => 'application/json',
);

$client = new \GuzzleHttp\Client();

// Define array of request body.
$request_body = array();

try {
    $response = $client->request('GET','/api/projects/{project_id}/experiments/{id}/', array(
        'headers' => $headers,
        'json' => $request_body,
       )
    );
    print_r($response->getBody()->getContents());
 }
 catch (\GuzzleHttp\Exception\BadResponseException $e) {
    // handle exception or api errors.
    print_r($e->getMessage());
 }

 // ...

```

```java
URL obj = new URL("/api/projects/{project_id}/experiments/{id}/");
HttpURLConnection con = (HttpURLConnection) obj.openConnection();
con.setRequestMethod("GET");
int responseCode = con.getResponseCode();
BufferedReader in = new BufferedReader(
    new InputStreamReader(con.getInputStream()));
String inputLine;
StringBuffer response = new StringBuffer();
while ((inputLine = in.readLine()) != null) {
    response.append(inputLine);
}
in.close();
System.out.println(response.toString());

```

```go
package main

import (
       "bytes"
       "net/http"
)

func main() {

    headers := map[string][]string{
        "Accept": []string{"application/json"},
    }

    data := bytes.NewBuffer([]byte{jsonReq})
    req, err := http.NewRequest("GET", "/api/projects/{project_id}/experiments/{id}/", data)
    req.Header = headers

    client := &http.Client{}
    resp, err := client.Do(req)
    // ...
}

```

`GET /api/projects/{project_id}/experiments/{id}/`

<h3 id="experiments_retrieve-parameters">Parameters</h3>

|Name|In|Type|Required|Description|
|---|---|---|---|---|
|id|path|integer|true|A unique integer value identifying this experiment.|
|project_id|path|string|true|Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/.|

> Example responses

> 200 Response

```json
{
  "id": 0,
  "name": "string",
  "description": "string",
  "start_date": "2019-08-24T14:15:22Z",
  "end_date": "2019-08-24T14:15:22Z",
  "feature_flag_key": "string",
  "parameters": {
    "property1": null,
    "property2": null
  },
  "secondary_metrics": {
    "property1": null,
    "property2": null
  },
  "filters": {
    "property1": null,
    "property2": null
  },
  "archived": true,
  "created_by": {
    "id": 0,
    "uuid": "095be615-a8ad-4c33-8e9c-c7612fbf6c9f",
    "distinct_id": "string",
    "first_name": "string",
    "email": "user@example.com"
  },
  "created_at": "2019-08-24T14:15:22Z",
  "updated_at": "2019-08-24T14:15:22Z"
}
```

<h3 id="experiments_retrieve-responses">Responses</h3>

|Status|Meaning|Description|Schema|
|---|---|---|---|
|200|[OK](https://tools.ietf.org/html/rfc7231#section-6.3.1)|none|[Experiment](#schemaexperiment)|

<aside class="success">
This operation does not require authentication
</aside>

## experiments_update

<a id="opIdexperiments_update"></a>

> Code samples

```shell
# You can also use wget
curl -X PUT /api/projects/{project_id}/experiments/{id}/ \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json'

```

```http
PUT /api/projects/{project_id}/experiments/{id}/ HTTP/1.1

Content-Type: application/json
Accept: application/json

```

```javascript
const inputBody = '{
  "name": "string",
  "description": "string",
  "start_date": "2019-08-24T14:15:22Z",
  "end_date": "2019-08-24T14:15:22Z",
  "feature_flag_key": "string",
  "parameters": {
    "property1": null,
    "property2": null
  },
  "secondary_metrics": {
    "property1": null,
    "property2": null
  },
  "filters": {
    "property1": null,
    "property2": null
  },
  "archived": true
}';
const headers = {
  'Content-Type':'application/json',
  'Accept':'application/json'
};

fetch('/api/projects/{project_id}/experiments/{id}/',
{
  method: 'PUT',
  body: inputBody,
  headers: headers
})
.then(function(res) {
    return res.json();
}).then(function(body) {
    console.log(body);
});

```

```ruby
require 'rest-client'
require 'json'

headers = {
  'Content-Type' => 'application/json',
  'Accept' => 'application/json'
}

result = RestClient.put '/api/projects/{project_id}/experiments/{id}/',
  params: {
  }, headers: headers

p JSON.parse(result)

```

```python
import requests
headers = {
  'Content-Type': 'application/json',
  'Accept': 'application/json'
}

r = requests.put('/api/projects/{project_id}/experiments/{id}/', headers = headers)

print(r.json())

```

```php
<?php

require 'vendor/autoload.php';

$headers = array(
    'Content-Type' => 'application/json',
    'Accept' => 'application/json',
);

$client = new \GuzzleHttp\Client();

// Define array of request body.
$request_body = array();

try {
    $response = $client->request('PUT','/api/projects/{project_id}/experiments/{id}/', array(
        'headers' => $headers,
        'json' => $request_body,
       )
    );
    print_r($response->getBody()->getContents());
 }
 catch (\GuzzleHttp\Exception\BadResponseException $e) {
    // handle exception or api errors.
    print_r($e->getMessage());
 }

 // ...

```

```java
URL obj = new URL("/api/projects/{project_id}/experiments/{id}/");
HttpURLConnection con = (HttpURLConnection) obj.openConnection();
con.setRequestMethod("PUT");
int responseCode = con.getResponseCode();
BufferedReader in = new BufferedReader(
    new InputStreamReader(con.getInputStream()));
String inputLine;
StringBuffer response = new StringBuffer();
while ((inputLine = in.readLine()) != null) {
    response.append(inputLine);
}
in.close();
System.out.println(response.toString());

```

```go
package main

import (
       "bytes"
       "net/http"
)

func main() {

    headers := map[string][]string{
        "Content-Type": []string{"application/json"},
        "Accept": []string{"application/json"},
    }

    data := bytes.NewBuffer([]byte{jsonReq})
    req, err := http.NewRequest("PUT", "/api/projects/{project_id}/experiments/{id}/", data)
    req.Header = headers

    client := &http.Client{}
    resp, err := client.Do(req)
    // ...
}

```

`PUT /api/projects/{project_id}/experiments/{id}/`

> Body parameter

```json
{
  "name": "string",
  "description": "string",
  "start_date": "2019-08-24T14:15:22Z",
  "end_date": "2019-08-24T14:15:22Z",
  "feature_flag_key": "string",
  "parameters": {
    "property1": null,
    "property2": null
  },
  "secondary_metrics": {
    "property1": null,
    "property2": null
  },
  "filters": {
    "property1": null,
    "property2": null
  },
  "archived": true
}
```

```yaml
name: string
description: string
start_date: 2019-08-24T14:15:22Z
end_date: 2019-08-24T14:15:22Z
feature_flag_key: string
parameters:
  ? property1
  ? property2
secondary_metrics:
  ? property1
  ? property2
filters:
  ? property1
  ? property2
archived: true

```

<h3 id="experiments_update-parameters">Parameters</h3>

|Name|In|Type|Required|Description|
|---|---|---|---|---|
|id|path|integer|true|A unique integer value identifying this experiment.|
|project_id|path|string|true|Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/.|
|body|body|[Experiment](#schemaexperiment)|true|none|

> Example responses

> 200 Response

```json
{
  "id": 0,
  "name": "string",
  "description": "string",
  "start_date": "2019-08-24T14:15:22Z",
  "end_date": "2019-08-24T14:15:22Z",
  "feature_flag_key": "string",
  "parameters": {
    "property1": null,
    "property2": null
  },
  "secondary_metrics": {
    "property1": null,
    "property2": null
  },
  "filters": {
    "property1": null,
    "property2": null
  },
  "archived": true,
  "created_by": {
    "id": 0,
    "uuid": "095be615-a8ad-4c33-8e9c-c7612fbf6c9f",
    "distinct_id": "string",
    "first_name": "string",
    "email": "user@example.com"
  },
  "created_at": "2019-08-24T14:15:22Z",
  "updated_at": "2019-08-24T14:15:22Z"
}
```

<h3 id="experiments_update-responses">Responses</h3>

|Status|Meaning|Description|Schema|
|---|---|---|---|
|200|[OK](https://tools.ietf.org/html/rfc7231#section-6.3.1)|none|[Experiment](#schemaexperiment)|

<aside class="success">
This operation does not require authentication
</aside>

## experiments_partial_update

<a id="opIdexperiments_partial_update"></a>

> Code samples

```shell
# You can also use wget
curl -X PATCH /api/projects/{project_id}/experiments/{id}/ \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json'

```

```http
PATCH /api/projects/{project_id}/experiments/{id}/ HTTP/1.1

Content-Type: application/json
Accept: application/json

```

```javascript
const inputBody = '{
  "name": "string",
  "description": "string",
  "start_date": "2019-08-24T14:15:22Z",
  "end_date": "2019-08-24T14:15:22Z",
  "feature_flag_key": "string",
  "parameters": {
    "property1": null,
    "property2": null
  },
  "secondary_metrics": {
    "property1": null,
    "property2": null
  },
  "filters": {
    "property1": null,
    "property2": null
  },
  "archived": true
}';
const headers = {
  'Content-Type':'application/json',
  'Accept':'application/json'
};

fetch('/api/projects/{project_id}/experiments/{id}/',
{
  method: 'PATCH',
  body: inputBody,
  headers: headers
})
.then(function(res) {
    return res.json();
}).then(function(body) {
    console.log(body);
});

```

```ruby
require 'rest-client'
require 'json'

headers = {
  'Content-Type' => 'application/json',
  'Accept' => 'application/json'
}

result = RestClient.patch '/api/projects/{project_id}/experiments/{id}/',
  params: {
  }, headers: headers

p JSON.parse(result)

```

```python
import requests
headers = {
  'Content-Type': 'application/json',
  'Accept': 'application/json'
}

r = requests.patch('/api/projects/{project_id}/experiments/{id}/', headers = headers)

print(r.json())

```

```php
<?php

require 'vendor/autoload.php';

$headers = array(
    'Content-Type' => 'application/json',
    'Accept' => 'application/json',
);

$client = new \GuzzleHttp\Client();

// Define array of request body.
$request_body = array();

try {
    $response = $client->request('PATCH','/api/projects/{project_id}/experiments/{id}/', array(
        'headers' => $headers,
        'json' => $request_body,
       )
    );
    print_r($response->getBody()->getContents());
 }
 catch (\GuzzleHttp\Exception\BadResponseException $e) {
    // handle exception or api errors.
    print_r($e->getMessage());
 }

 // ...

```

```java
URL obj = new URL("/api/projects/{project_id}/experiments/{id}/");
HttpURLConnection con = (HttpURLConnection) obj.openConnection();
con.setRequestMethod("PATCH");
int responseCode = con.getResponseCode();
BufferedReader in = new BufferedReader(
    new InputStreamReader(con.getInputStream()));
String inputLine;
StringBuffer response = new StringBuffer();
while ((inputLine = in.readLine()) != null) {
    response.append(inputLine);
}
in.close();
System.out.println(response.toString());

```

```go
package main

import (
       "bytes"
       "net/http"
)

func main() {

    headers := map[string][]string{
        "Content-Type": []string{"application/json"},
        "Accept": []string{"application/json"},
    }

    data := bytes.NewBuffer([]byte{jsonReq})
    req, err := http.NewRequest("PATCH", "/api/projects/{project_id}/experiments/{id}/", data)
    req.Header = headers

    client := &http.Client{}
    resp, err := client.Do(req)
    // ...
}

```

`PATCH /api/projects/{project_id}/experiments/{id}/`

> Body parameter

```json
{
  "name": "string",
  "description": "string",
  "start_date": "2019-08-24T14:15:22Z",
  "end_date": "2019-08-24T14:15:22Z",
  "feature_flag_key": "string",
  "parameters": {
    "property1": null,
    "property2": null
  },
  "secondary_metrics": {
    "property1": null,
    "property2": null
  },
  "filters": {
    "property1": null,
    "property2": null
  },
  "archived": true
}
```

```yaml
name: string
description: string
start_date: 2019-08-24T14:15:22Z
end_date: 2019-08-24T14:15:22Z
feature_flag_key: string
parameters:
  ? property1
  ? property2
secondary_metrics:
  ? property1
  ? property2
filters:
  ? property1
  ? property2
archived: true

```

<h3 id="experiments_partial_update-parameters">Parameters</h3>

|Name|In|Type|Required|Description|
|---|---|---|---|---|
|id|path|integer|true|A unique integer value identifying this experiment.|
|project_id|path|string|true|Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/.|
|body|body|[PatchedExperiment](#schemapatchedexperiment)|false|none|

> Example responses

> 200 Response

```json
{
  "id": 0,
  "name": "string",
  "description": "string",
  "start_date": "2019-08-24T14:15:22Z",
  "end_date": "2019-08-24T14:15:22Z",
  "feature_flag_key": "string",
  "parameters": {
    "property1": null,
    "property2": null
  },
  "secondary_metrics": {
    "property1": null,
    "property2": null
  },
  "filters": {
    "property1": null,
    "property2": null
  },
  "archived": true,
  "created_by": {
    "id": 0,
    "uuid": "095be615-a8ad-4c33-8e9c-c7612fbf6c9f",
    "distinct_id": "string",
    "first_name": "string",
    "email": "user@example.com"
  },
  "created_at": "2019-08-24T14:15:22Z",
  "updated_at": "2019-08-24T14:15:22Z"
}
```

<h3 id="experiments_partial_update-responses">Responses</h3>

|Status|Meaning|Description|Schema|
|---|---|---|---|
|200|[OK](https://tools.ietf.org/html/rfc7231#section-6.3.1)|none|[Experiment](#schemaexperiment)|

<aside class="success">
This operation does not require authentication
</aside>

## experiments_destroy

<a id="opIdexperiments_destroy"></a>

> Code samples

```shell
# You can also use wget
curl -X DELETE /api/projects/{project_id}/experiments/{id}/

```

```http
DELETE /api/projects/{project_id}/experiments/{id}/ HTTP/1.1

```

```javascript

fetch('/api/projects/{project_id}/experiments/{id}/',
{
  method: 'DELETE'

})
.then(function(res) {
    return res.json();
}).then(function(body) {
    console.log(body);
});

```

```ruby
require 'rest-client'
require 'json'

result = RestClient.delete '/api/projects/{project_id}/experiments/{id}/',
  params: {
  }

p JSON.parse(result)

```

```python
import requests

r = requests.delete('/api/projects/{project_id}/experiments/{id}/')

print(r.json())

```

```php
<?php

require 'vendor/autoload.php';

$client = new \GuzzleHttp\Client();

// Define array of request body.
$request_body = array();

try {
    $response = $client->request('DELETE','/api/projects/{project_id}/experiments/{id}/', array(
        'headers' => $headers,
        'json' => $request_body,
       )
    );
    print_r($response->getBody()->getContents());
 }
 catch (\GuzzleHttp\Exception\BadResponseException $e) {
    // handle exception or api errors.
    print_r($e->getMessage());
 }

 // ...

```

```java
URL obj = new URL("/api/projects/{project_id}/experiments/{id}/");
HttpURLConnection con = (HttpURLConnection) obj.openConnection();
con.setRequestMethod("DELETE");
int responseCode = con.getResponseCode();
BufferedReader in = new BufferedReader(
    new InputStreamReader(con.getInputStream()));
String inputLine;
StringBuffer response = new StringBuffer();
while ((inputLine = in.readLine()) != null) {
    response.append(inputLine);
}
in.close();
System.out.println(response.toString());

```

```go
package main

import (
       "bytes"
       "net/http"
)

func main() {

    data := bytes.NewBuffer([]byte{jsonReq})
    req, err := http.NewRequest("DELETE", "/api/projects/{project_id}/experiments/{id}/", data)
    req.Header = headers

    client := &http.Client{}
    resp, err := client.Do(req)
    // ...
}

```

`DELETE /api/projects/{project_id}/experiments/{id}/`

<h3 id="experiments_destroy-parameters">Parameters</h3>

|Name|In|Type|Required|Description|
|---|---|---|---|---|
|id|path|integer|true|A unique integer value identifying this experiment.|
|project_id|path|string|true|Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/.|

<h3 id="experiments_destroy-responses">Responses</h3>

|Status|Meaning|Description|Schema|
|---|---|---|---|
|204|[No Content](https://tools.ietf.org/html/rfc7231#section-6.3.5)|No response body|None|

<aside class="success">
This operation does not require authentication
</aside>

## experiments_results_retrieve

<a id="opIdexperiments_results_retrieve"></a>

> Code samples

```shell
# You can also use wget
curl -X GET /api/projects/{project_id}/experiments/{id}/results/ \
  -H 'Accept: application/json'

```

```http
GET /api/projects/{project_id}/experiments/{id}/results/ HTTP/1.1

Accept: application/json

```

```javascript

const headers = {
  'Accept':'application/json'
};

fetch('/api/projects/{project_id}/experiments/{id}/results/',
{
  method: 'GET',

  headers: headers
})
.then(function(res) {
    return res.json();
}).then(function(body) {
    console.log(body);
});

```

```ruby
require 'rest-client'
require 'json'

headers = {
  'Accept' => 'application/json'
}

result = RestClient.get '/api/projects/{project_id}/experiments/{id}/results/',
  params: {
  }, headers: headers

p JSON.parse(result)

```

```python
import requests
headers = {
  'Accept': 'application/json'
}

r = requests.get('/api/projects/{project_id}/experiments/{id}/results/', headers = headers)

print(r.json())

```

```php
<?php

require 'vendor/autoload.php';

$headers = array(
    'Accept' => 'application/json',
);

$client = new \GuzzleHttp\Client();

// Define array of request body.
$request_body = array();

try {
    $response = $client->request('GET','/api/projects/{project_id}/experiments/{id}/results/', array(
        'headers' => $headers,
        'json' => $request_body,
       )
    );
    print_r($response->getBody()->getContents());
 }
 catch (\GuzzleHttp\Exception\BadResponseException $e) {
    // handle exception or api errors.
    print_r($e->getMessage());
 }

 // ...

```

```java
URL obj = new URL("/api/projects/{project_id}/experiments/{id}/results/");
HttpURLConnection con = (HttpURLConnection) obj.openConnection();
con.setRequestMethod("GET");
int responseCode = con.getResponseCode();
BufferedReader in = new BufferedReader(
    new InputStreamReader(con.getInputStream()));
String inputLine;
StringBuffer response = new StringBuffer();
while ((inputLine = in.readLine()) != null) {
    response.append(inputLine);
}
in.close();
System.out.println(response.toString());

```

```go
package main

import (
       "bytes"
       "net/http"
)

func main() {

    headers := map[string][]string{
        "Accept": []string{"application/json"},
    }

    data := bytes.NewBuffer([]byte{jsonReq})
    req, err := http.NewRequest("GET", "/api/projects/{project_id}/experiments/{id}/results/", data)
    req.Header = headers

    client := &http.Client{}
    resp, err := client.Do(req)
    // ...
}

```

`GET /api/projects/{project_id}/experiments/{id}/results/`

<h3 id="experiments_results_retrieve-parameters">Parameters</h3>

|Name|In|Type|Required|Description|
|---|---|---|---|---|
|id|path|integer|true|A unique integer value identifying this experiment.|
|project_id|path|string|true|Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/.|

> Example responses

> 200 Response

```json
{
  "id": 0,
  "name": "string",
  "description": "string",
  "start_date": "2019-08-24T14:15:22Z",
  "end_date": "2019-08-24T14:15:22Z",
  "feature_flag_key": "string",
  "parameters": {
    "property1": null,
    "property2": null
  },
  "secondary_metrics": {
    "property1": null,
    "property2": null
  },
  "filters": {
    "property1": null,
    "property2": null
  },
  "archived": true,
  "created_by": {
    "id": 0,
    "uuid": "095be615-a8ad-4c33-8e9c-c7612fbf6c9f",
    "distinct_id": "string",
    "first_name": "string",
    "email": "user@example.com"
  },
  "created_at": "2019-08-24T14:15:22Z",
  "updated_at": "2019-08-24T14:15:22Z"
}
```

<h3 id="experiments_results_retrieve-responses">Responses</h3>

|Status|Meaning|Description|Schema|
|---|---|---|---|
|200|[OK](https://tools.ietf.org/html/rfc7231#section-6.3.1)|none|[Experiment](#schemaexperiment)|

<aside class="success">
This operation does not require authentication
</aside>

## experiments_secondary_results_retrieve

<a id="opIdexperiments_secondary_results_retrieve"></a>

> Code samples

```shell
# You can also use wget
curl -X GET /api/projects/{project_id}/experiments/{id}/secondary_results/ \
  -H 'Accept: application/json'

```

```http
GET /api/projects/{project_id}/experiments/{id}/secondary_results/ HTTP/1.1

Accept: application/json

```

```javascript

const headers = {
  'Accept':'application/json'
};

fetch('/api/projects/{project_id}/experiments/{id}/secondary_results/',
{
  method: 'GET',

  headers: headers
})
.then(function(res) {
    return res.json();
}).then(function(body) {
    console.log(body);
});

```

```ruby
require 'rest-client'
require 'json'

headers = {
  'Accept' => 'application/json'
}

result = RestClient.get '/api/projects/{project_id}/experiments/{id}/secondary_results/',
  params: {
  }, headers: headers

p JSON.parse(result)

```

```python
import requests
headers = {
  'Accept': 'application/json'
}

r = requests.get('/api/projects/{project_id}/experiments/{id}/secondary_results/', headers = headers)

print(r.json())

```

```php
<?php

require 'vendor/autoload.php';

$headers = array(
    'Accept' => 'application/json',
);

$client = new \GuzzleHttp\Client();

// Define array of request body.
$request_body = array();

try {
    $response = $client->request('GET','/api/projects/{project_id}/experiments/{id}/secondary_results/', array(
        'headers' => $headers,
        'json' => $request_body,
       )
    );
    print_r($response->getBody()->getContents());
 }
 catch (\GuzzleHttp\Exception\BadResponseException $e) {
    // handle exception or api errors.
    print_r($e->getMessage());
 }

 // ...

```

```java
URL obj = new URL("/api/projects/{project_id}/experiments/{id}/secondary_results/");
HttpURLConnection con = (HttpURLConnection) obj.openConnection();
con.setRequestMethod("GET");
int responseCode = con.getResponseCode();
BufferedReader in = new BufferedReader(
    new InputStreamReader(con.getInputStream()));
String inputLine;
StringBuffer response = new StringBuffer();
while ((inputLine = in.readLine()) != null) {
    response.append(inputLine);
}
in.close();
System.out.println(response.toString());

```

```go
package main

import (
       "bytes"
       "net/http"
)

func main() {

    headers := map[string][]string{
        "Accept": []string{"application/json"},
    }

    data := bytes.NewBuffer([]byte{jsonReq})
    req, err := http.NewRequest("GET", "/api/projects/{project_id}/experiments/{id}/secondary_results/", data)
    req.Header = headers

    client := &http.Client{}
    resp, err := client.Do(req)
    // ...
}

```

`GET /api/projects/{project_id}/experiments/{id}/secondary_results/`

<h3 id="experiments_secondary_results_retrieve-parameters">Parameters</h3>

|Name|In|Type|Required|Description|
|---|---|---|---|---|
|id|path|integer|true|A unique integer value identifying this experiment.|
|project_id|path|string|true|Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/.|

> Example responses

> 200 Response

```json
{
  "id": 0,
  "name": "string",
  "description": "string",
  "start_date": "2019-08-24T14:15:22Z",
  "end_date": "2019-08-24T14:15:22Z",
  "feature_flag_key": "string",
  "parameters": {
    "property1": null,
    "property2": null
  },
  "secondary_metrics": {
    "property1": null,
    "property2": null
  },
  "filters": {
    "property1": null,
    "property2": null
  },
  "archived": true,
  "created_by": {
    "id": 0,
    "uuid": "095be615-a8ad-4c33-8e9c-c7612fbf6c9f",
    "distinct_id": "string",
    "first_name": "string",
    "email": "user@example.com"
  },
  "created_at": "2019-08-24T14:15:22Z",
  "updated_at": "2019-08-24T14:15:22Z"
}
```

<h3 id="experiments_secondary_results_retrieve-responses">Responses</h3>

|Status|Meaning|Description|Schema|
|---|---|---|---|
|200|[OK](https://tools.ietf.org/html/rfc7231#section-6.3.1)|none|[Experiment](#schemaexperiment)|

<aside class="success">
This operation does not require authentication
</aside>

<h1 id="-feature_flags">feature_flags</h1>

## feature_flags_list

<a id="opIdfeature_flags_list"></a>

> Code samples

```shell
# You can also use wget
curl -X GET /api/projects/{project_id}/feature_flags/ \
  -H 'Accept: application/json'

```

```http
GET /api/projects/{project_id}/feature_flags/ HTTP/1.1

Accept: application/json

```

```javascript

const headers = {
  'Accept':'application/json'
};

fetch('/api/projects/{project_id}/feature_flags/',
{
  method: 'GET',

  headers: headers
})
.then(function(res) {
    return res.json();
}).then(function(body) {
    console.log(body);
});

```

```ruby
require 'rest-client'
require 'json'

headers = {
  'Accept' => 'application/json'
}

result = RestClient.get '/api/projects/{project_id}/feature_flags/',
  params: {
  }, headers: headers

p JSON.parse(result)

```

```python
import requests
headers = {
  'Accept': 'application/json'
}

r = requests.get('/api/projects/{project_id}/feature_flags/', headers = headers)

print(r.json())

```

```php
<?php

require 'vendor/autoload.php';

$headers = array(
    'Accept' => 'application/json',
);

$client = new \GuzzleHttp\Client();

// Define array of request body.
$request_body = array();

try {
    $response = $client->request('GET','/api/projects/{project_id}/feature_flags/', array(
        'headers' => $headers,
        'json' => $request_body,
       )
    );
    print_r($response->getBody()->getContents());
 }
 catch (\GuzzleHttp\Exception\BadResponseException $e) {
    // handle exception or api errors.
    print_r($e->getMessage());
 }

 // ...

```

```java
URL obj = new URL("/api/projects/{project_id}/feature_flags/");
HttpURLConnection con = (HttpURLConnection) obj.openConnection();
con.setRequestMethod("GET");
int responseCode = con.getResponseCode();
BufferedReader in = new BufferedReader(
    new InputStreamReader(con.getInputStream()));
String inputLine;
StringBuffer response = new StringBuffer();
while ((inputLine = in.readLine()) != null) {
    response.append(inputLine);
}
in.close();
System.out.println(response.toString());

```

```go
package main

import (
       "bytes"
       "net/http"
)

func main() {

    headers := map[string][]string{
        "Accept": []string{"application/json"},
    }

    data := bytes.NewBuffer([]byte{jsonReq})
    req, err := http.NewRequest("GET", "/api/projects/{project_id}/feature_flags/", data)
    req.Header = headers

    client := &http.Client{}
    resp, err := client.Do(req)
    // ...
}

```

`GET /api/projects/{project_id}/feature_flags/`

Create, read, update and delete feature flags. [See docs](https://posthog.com/docs/user-guides/feature-flags) for more information on feature flags.

<h3 id="feature_flags_list-parameters">Parameters</h3>

|Name|In|Type|Required|Description|
|---|---|---|---|---|
|limit|query|integer|false|Number of results to return per page.|
|offset|query|integer|false|The initial index from which to return the results.|
|project_id|path|string|true|Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/.|

> Example responses

> 200 Response

```json
{
  "count": 123,
  "next": "http://api.example.org/accounts/?offset=400&limit=100",
  "previous": "http://api.example.org/accounts/?offset=200&limit=100",
  "results": [
    {
      "id": 0,
      "name": "string",
      "key": "string",
      "filters": {
        "property1": null,
        "property2": null
      },
      "deleted": true,
      "active": true,
      "created_by": {
        "id": 0,
        "uuid": "095be615-a8ad-4c33-8e9c-c7612fbf6c9f",
        "distinct_id": "string",
        "first_name": "string",
        "email": "user@example.com"
      },
      "created_at": "2019-08-24T14:15:22Z",
      "is_simple_flag": true,
      "rollout_percentage": 0
    }
  ]
}
```

<h3 id="feature_flags_list-responses">Responses</h3>

|Status|Meaning|Description|Schema|
|---|---|---|---|
|200|[OK](https://tools.ietf.org/html/rfc7231#section-6.3.1)|none|[PaginatedFeatureFlagList](#schemapaginatedfeatureflaglist)|

<aside class="success">
This operation does not require authentication
</aside>

## feature_flags_create

<a id="opIdfeature_flags_create"></a>

> Code samples

```shell
# You can also use wget
curl -X POST /api/projects/{project_id}/feature_flags/ \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json'

```

```http
POST /api/projects/{project_id}/feature_flags/ HTTP/1.1

Content-Type: application/json
Accept: application/json

```

```javascript
const inputBody = '{
  "name": "string",
  "key": "string",
  "filters": {
    "property1": null,
    "property2": null
  },
  "deleted": true,
  "active": true,
  "created_at": "2019-08-24T14:15:22Z"
}';
const headers = {
  'Content-Type':'application/json',
  'Accept':'application/json'
};

fetch('/api/projects/{project_id}/feature_flags/',
{
  method: 'POST',
  body: inputBody,
  headers: headers
})
.then(function(res) {
    return res.json();
}).then(function(body) {
    console.log(body);
});

```

```ruby
require 'rest-client'
require 'json'

headers = {
  'Content-Type' => 'application/json',
  'Accept' => 'application/json'
}

result = RestClient.post '/api/projects/{project_id}/feature_flags/',
  params: {
  }, headers: headers

p JSON.parse(result)

```

```python
import requests
headers = {
  'Content-Type': 'application/json',
  'Accept': 'application/json'
}

r = requests.post('/api/projects/{project_id}/feature_flags/', headers = headers)

print(r.json())

```

```php
<?php

require 'vendor/autoload.php';

$headers = array(
    'Content-Type' => 'application/json',
    'Accept' => 'application/json',
);

$client = new \GuzzleHttp\Client();

// Define array of request body.
$request_body = array();

try {
    $response = $client->request('POST','/api/projects/{project_id}/feature_flags/', array(
        'headers' => $headers,
        'json' => $request_body,
       )
    );
    print_r($response->getBody()->getContents());
 }
 catch (\GuzzleHttp\Exception\BadResponseException $e) {
    // handle exception or api errors.
    print_r($e->getMessage());
 }

 // ...

```

```java
URL obj = new URL("/api/projects/{project_id}/feature_flags/");
HttpURLConnection con = (HttpURLConnection) obj.openConnection();
con.setRequestMethod("POST");
int responseCode = con.getResponseCode();
BufferedReader in = new BufferedReader(
    new InputStreamReader(con.getInputStream()));
String inputLine;
StringBuffer response = new StringBuffer();
while ((inputLine = in.readLine()) != null) {
    response.append(inputLine);
}
in.close();
System.out.println(response.toString());

```

```go
package main

import (
       "bytes"
       "net/http"
)

func main() {

    headers := map[string][]string{
        "Content-Type": []string{"application/json"},
        "Accept": []string{"application/json"},
    }

    data := bytes.NewBuffer([]byte{jsonReq})
    req, err := http.NewRequest("POST", "/api/projects/{project_id}/feature_flags/", data)
    req.Header = headers

    client := &http.Client{}
    resp, err := client.Do(req)
    // ...
}

```

`POST /api/projects/{project_id}/feature_flags/`

Create, read, update and delete feature flags. [See docs](https://posthog.com/docs/user-guides/feature-flags) for more information on feature flags.

> Body parameter

```json
{
  "name": "string",
  "key": "string",
  "filters": {
    "property1": null,
    "property2": null
  },
  "deleted": true,
  "active": true,
  "created_at": "2019-08-24T14:15:22Z"
}
```

```yaml
name: string
key: string
filters:
  ? property1
  ? property2
deleted: true
active: true
created_at: 2019-08-24T14:15:22Z

```

<h3 id="feature_flags_create-parameters">Parameters</h3>

|Name|In|Type|Required|Description|
|---|---|---|---|---|
|project_id|path|string|true|Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/.|
|body|body|[FeatureFlag](#schemafeatureflag)|true|none|

> Example responses

> 201 Response

```json
{
  "id": 0,
  "name": "string",
  "key": "string",
  "filters": {
    "property1": null,
    "property2": null
  },
  "deleted": true,
  "active": true,
  "created_by": {
    "id": 0,
    "uuid": "095be615-a8ad-4c33-8e9c-c7612fbf6c9f",
    "distinct_id": "string",
    "first_name": "string",
    "email": "user@example.com"
  },
  "created_at": "2019-08-24T14:15:22Z",
  "is_simple_flag": true,
  "rollout_percentage": 0
}
```

<h3 id="feature_flags_create-responses">Responses</h3>

|Status|Meaning|Description|Schema|
|---|---|---|---|
|201|[Created](https://tools.ietf.org/html/rfc7231#section-6.3.2)|none|[FeatureFlag](#schemafeatureflag)|

<aside class="success">
This operation does not require authentication
</aside>

## feature_flags_retrieve

<a id="opIdfeature_flags_retrieve"></a>

> Code samples

```shell
# You can also use wget
curl -X GET /api/projects/{project_id}/feature_flags/{id}/ \
  -H 'Accept: application/json'

```

```http
GET /api/projects/{project_id}/feature_flags/{id}/ HTTP/1.1

Accept: application/json

```

```javascript

const headers = {
  'Accept':'application/json'
};

fetch('/api/projects/{project_id}/feature_flags/{id}/',
{
  method: 'GET',

  headers: headers
})
.then(function(res) {
    return res.json();
}).then(function(body) {
    console.log(body);
});

```

```ruby
require 'rest-client'
require 'json'

headers = {
  'Accept' => 'application/json'
}

result = RestClient.get '/api/projects/{project_id}/feature_flags/{id}/',
  params: {
  }, headers: headers

p JSON.parse(result)

```

```python
import requests
headers = {
  'Accept': 'application/json'
}

r = requests.get('/api/projects/{project_id}/feature_flags/{id}/', headers = headers)

print(r.json())

```

```php
<?php

require 'vendor/autoload.php';

$headers = array(
    'Accept' => 'application/json',
);

$client = new \GuzzleHttp\Client();

// Define array of request body.
$request_body = array();

try {
    $response = $client->request('GET','/api/projects/{project_id}/feature_flags/{id}/', array(
        'headers' => $headers,
        'json' => $request_body,
       )
    );
    print_r($response->getBody()->getContents());
 }
 catch (\GuzzleHttp\Exception\BadResponseException $e) {
    // handle exception or api errors.
    print_r($e->getMessage());
 }

 // ...

```

```java
URL obj = new URL("/api/projects/{project_id}/feature_flags/{id}/");
HttpURLConnection con = (HttpURLConnection) obj.openConnection();
con.setRequestMethod("GET");
int responseCode = con.getResponseCode();
BufferedReader in = new BufferedReader(
    new InputStreamReader(con.getInputStream()));
String inputLine;
StringBuffer response = new StringBuffer();
while ((inputLine = in.readLine()) != null) {
    response.append(inputLine);
}
in.close();
System.out.println(response.toString());

```

```go
package main

import (
       "bytes"
       "net/http"
)

func main() {

    headers := map[string][]string{
        "Accept": []string{"application/json"},
    }

    data := bytes.NewBuffer([]byte{jsonReq})
    req, err := http.NewRequest("GET", "/api/projects/{project_id}/feature_flags/{id}/", data)
    req.Header = headers

    client := &http.Client{}
    resp, err := client.Do(req)
    // ...
}

```

`GET /api/projects/{project_id}/feature_flags/{id}/`

Create, read, update and delete feature flags. [See docs](https://posthog.com/docs/user-guides/feature-flags) for more information on feature flags.

<h3 id="feature_flags_retrieve-parameters">Parameters</h3>

|Name|In|Type|Required|Description|
|---|---|---|---|---|
|id|path|integer|true|A unique integer value identifying this feature flag.|
|project_id|path|string|true|Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/.|

> Example responses

> 200 Response

```json
{
  "id": 0,
  "name": "string",
  "key": "string",
  "filters": {
    "property1": null,
    "property2": null
  },
  "deleted": true,
  "active": true,
  "created_by": {
    "id": 0,
    "uuid": "095be615-a8ad-4c33-8e9c-c7612fbf6c9f",
    "distinct_id": "string",
    "first_name": "string",
    "email": "user@example.com"
  },
  "created_at": "2019-08-24T14:15:22Z",
  "is_simple_flag": true,
  "rollout_percentage": 0
}
```

<h3 id="feature_flags_retrieve-responses">Responses</h3>

|Status|Meaning|Description|Schema|
|---|---|---|---|
|200|[OK](https://tools.ietf.org/html/rfc7231#section-6.3.1)|none|[FeatureFlag](#schemafeatureflag)|

<aside class="success">
This operation does not require authentication
</aside>

## feature_flags_update

<a id="opIdfeature_flags_update"></a>

> Code samples

```shell
# You can also use wget
curl -X PUT /api/projects/{project_id}/feature_flags/{id}/ \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json'

```

```http
PUT /api/projects/{project_id}/feature_flags/{id}/ HTTP/1.1

Content-Type: application/json
Accept: application/json

```

```javascript
const inputBody = '{
  "name": "string",
  "key": "string",
  "filters": {
    "property1": null,
    "property2": null
  },
  "deleted": true,
  "active": true,
  "created_at": "2019-08-24T14:15:22Z"
}';
const headers = {
  'Content-Type':'application/json',
  'Accept':'application/json'
};

fetch('/api/projects/{project_id}/feature_flags/{id}/',
{
  method: 'PUT',
  body: inputBody,
  headers: headers
})
.then(function(res) {
    return res.json();
}).then(function(body) {
    console.log(body);
});

```

```ruby
require 'rest-client'
require 'json'

headers = {
  'Content-Type' => 'application/json',
  'Accept' => 'application/json'
}

result = RestClient.put '/api/projects/{project_id}/feature_flags/{id}/',
  params: {
  }, headers: headers

p JSON.parse(result)

```

```python
import requests
headers = {
  'Content-Type': 'application/json',
  'Accept': 'application/json'
}

r = requests.put('/api/projects/{project_id}/feature_flags/{id}/', headers = headers)

print(r.json())

```

```php
<?php

require 'vendor/autoload.php';

$headers = array(
    'Content-Type' => 'application/json',
    'Accept' => 'application/json',
);

$client = new \GuzzleHttp\Client();

// Define array of request body.
$request_body = array();

try {
    $response = $client->request('PUT','/api/projects/{project_id}/feature_flags/{id}/', array(
        'headers' => $headers,
        'json' => $request_body,
       )
    );
    print_r($response->getBody()->getContents());
 }
 catch (\GuzzleHttp\Exception\BadResponseException $e) {
    // handle exception or api errors.
    print_r($e->getMessage());
 }

 // ...

```

```java
URL obj = new URL("/api/projects/{project_id}/feature_flags/{id}/");
HttpURLConnection con = (HttpURLConnection) obj.openConnection();
con.setRequestMethod("PUT");
int responseCode = con.getResponseCode();
BufferedReader in = new BufferedReader(
    new InputStreamReader(con.getInputStream()));
String inputLine;
StringBuffer response = new StringBuffer();
while ((inputLine = in.readLine()) != null) {
    response.append(inputLine);
}
in.close();
System.out.println(response.toString());

```

```go
package main

import (
       "bytes"
       "net/http"
)

func main() {

    headers := map[string][]string{
        "Content-Type": []string{"application/json"},
        "Accept": []string{"application/json"},
    }

    data := bytes.NewBuffer([]byte{jsonReq})
    req, err := http.NewRequest("PUT", "/api/projects/{project_id}/feature_flags/{id}/", data)
    req.Header = headers

    client := &http.Client{}
    resp, err := client.Do(req)
    // ...
}

```

`PUT /api/projects/{project_id}/feature_flags/{id}/`

Create, read, update and delete feature flags. [See docs](https://posthog.com/docs/user-guides/feature-flags) for more information on feature flags.

> Body parameter

```json
{
  "name": "string",
  "key": "string",
  "filters": {
    "property1": null,
    "property2": null
  },
  "deleted": true,
  "active": true,
  "created_at": "2019-08-24T14:15:22Z"
}
```

```yaml
name: string
key: string
filters:
  ? property1
  ? property2
deleted: true
active: true
created_at: 2019-08-24T14:15:22Z

```

<h3 id="feature_flags_update-parameters">Parameters</h3>

|Name|In|Type|Required|Description|
|---|---|---|---|---|
|id|path|integer|true|A unique integer value identifying this feature flag.|
|project_id|path|string|true|Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/.|
|body|body|[FeatureFlag](#schemafeatureflag)|true|none|

> Example responses

> 200 Response

```json
{
  "id": 0,
  "name": "string",
  "key": "string",
  "filters": {
    "property1": null,
    "property2": null
  },
  "deleted": true,
  "active": true,
  "created_by": {
    "id": 0,
    "uuid": "095be615-a8ad-4c33-8e9c-c7612fbf6c9f",
    "distinct_id": "string",
    "first_name": "string",
    "email": "user@example.com"
  },
  "created_at": "2019-08-24T14:15:22Z",
  "is_simple_flag": true,
  "rollout_percentage": 0
}
```

<h3 id="feature_flags_update-responses">Responses</h3>

|Status|Meaning|Description|Schema|
|---|---|---|---|
|200|[OK](https://tools.ietf.org/html/rfc7231#section-6.3.1)|none|[FeatureFlag](#schemafeatureflag)|

<aside class="success">
This operation does not require authentication
</aside>

## feature_flags_partial_update

<a id="opIdfeature_flags_partial_update"></a>

> Code samples

```shell
# You can also use wget
curl -X PATCH /api/projects/{project_id}/feature_flags/{id}/ \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json'

```

```http
PATCH /api/projects/{project_id}/feature_flags/{id}/ HTTP/1.1

Content-Type: application/json
Accept: application/json

```

```javascript
const inputBody = '{
  "name": "string",
  "key": "string",
  "filters": {
    "property1": null,
    "property2": null
  },
  "deleted": true,
  "active": true,
  "created_at": "2019-08-24T14:15:22Z"
}';
const headers = {
  'Content-Type':'application/json',
  'Accept':'application/json'
};

fetch('/api/projects/{project_id}/feature_flags/{id}/',
{
  method: 'PATCH',
  body: inputBody,
  headers: headers
})
.then(function(res) {
    return res.json();
}).then(function(body) {
    console.log(body);
});

```

```ruby
require 'rest-client'
require 'json'

headers = {
  'Content-Type' => 'application/json',
  'Accept' => 'application/json'
}

result = RestClient.patch '/api/projects/{project_id}/feature_flags/{id}/',
  params: {
  }, headers: headers

p JSON.parse(result)

```

```python
import requests
headers = {
  'Content-Type': 'application/json',
  'Accept': 'application/json'
}

r = requests.patch('/api/projects/{project_id}/feature_flags/{id}/', headers = headers)

print(r.json())

```

```php
<?php

require 'vendor/autoload.php';

$headers = array(
    'Content-Type' => 'application/json',
    'Accept' => 'application/json',
);

$client = new \GuzzleHttp\Client();

// Define array of request body.
$request_body = array();

try {
    $response = $client->request('PATCH','/api/projects/{project_id}/feature_flags/{id}/', array(
        'headers' => $headers,
        'json' => $request_body,
       )
    );
    print_r($response->getBody()->getContents());
 }
 catch (\GuzzleHttp\Exception\BadResponseException $e) {
    // handle exception or api errors.
    print_r($e->getMessage());
 }

 // ...

```

```java
URL obj = new URL("/api/projects/{project_id}/feature_flags/{id}/");
HttpURLConnection con = (HttpURLConnection) obj.openConnection();
con.setRequestMethod("PATCH");
int responseCode = con.getResponseCode();
BufferedReader in = new BufferedReader(
    new InputStreamReader(con.getInputStream()));
String inputLine;
StringBuffer response = new StringBuffer();
while ((inputLine = in.readLine()) != null) {
    response.append(inputLine);
}
in.close();
System.out.println(response.toString());

```

```go
package main

import (
       "bytes"
       "net/http"
)

func main() {

    headers := map[string][]string{
        "Content-Type": []string{"application/json"},
        "Accept": []string{"application/json"},
    }

    data := bytes.NewBuffer([]byte{jsonReq})
    req, err := http.NewRequest("PATCH", "/api/projects/{project_id}/feature_flags/{id}/", data)
    req.Header = headers

    client := &http.Client{}
    resp, err := client.Do(req)
    // ...
}

```

`PATCH /api/projects/{project_id}/feature_flags/{id}/`

Create, read, update and delete feature flags. [See docs](https://posthog.com/docs/user-guides/feature-flags) for more information on feature flags.

> Body parameter

```json
{
  "name": "string",
  "key": "string",
  "filters": {
    "property1": null,
    "property2": null
  },
  "deleted": true,
  "active": true,
  "created_at": "2019-08-24T14:15:22Z"
}
```

```yaml
name: string
key: string
filters:
  ? property1
  ? property2
deleted: true
active: true
created_at: 2019-08-24T14:15:22Z

```

<h3 id="feature_flags_partial_update-parameters">Parameters</h3>

|Name|In|Type|Required|Description|
|---|---|---|---|---|
|id|path|integer|true|A unique integer value identifying this feature flag.|
|project_id|path|string|true|Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/.|
|body|body|[PatchedFeatureFlag](#schemapatchedfeatureflag)|false|none|

> Example responses

> 200 Response

```json
{
  "id": 0,
  "name": "string",
  "key": "string",
  "filters": {
    "property1": null,
    "property2": null
  },
  "deleted": true,
  "active": true,
  "created_by": {
    "id": 0,
    "uuid": "095be615-a8ad-4c33-8e9c-c7612fbf6c9f",
    "distinct_id": "string",
    "first_name": "string",
    "email": "user@example.com"
  },
  "created_at": "2019-08-24T14:15:22Z",
  "is_simple_flag": true,
  "rollout_percentage": 0
}
```

<h3 id="feature_flags_partial_update-responses">Responses</h3>

|Status|Meaning|Description|Schema|
|---|---|---|---|
|200|[OK](https://tools.ietf.org/html/rfc7231#section-6.3.1)|none|[FeatureFlag](#schemafeatureflag)|

<aside class="success">
This operation does not require authentication
</aside>

## feature_flags_destroy

<a id="opIdfeature_flags_destroy"></a>

> Code samples

```shell
# You can also use wget
curl -X DELETE /api/projects/{project_id}/feature_flags/{id}/

```

```http
DELETE /api/projects/{project_id}/feature_flags/{id}/ HTTP/1.1

```

```javascript

fetch('/api/projects/{project_id}/feature_flags/{id}/',
{
  method: 'DELETE'

})
.then(function(res) {
    return res.json();
}).then(function(body) {
    console.log(body);
});

```

```ruby
require 'rest-client'
require 'json'

result = RestClient.delete '/api/projects/{project_id}/feature_flags/{id}/',
  params: {
  }

p JSON.parse(result)

```

```python
import requests

r = requests.delete('/api/projects/{project_id}/feature_flags/{id}/')

print(r.json())

```

```php
<?php

require 'vendor/autoload.php';

$client = new \GuzzleHttp\Client();

// Define array of request body.
$request_body = array();

try {
    $response = $client->request('DELETE','/api/projects/{project_id}/feature_flags/{id}/', array(
        'headers' => $headers,
        'json' => $request_body,
       )
    );
    print_r($response->getBody()->getContents());
 }
 catch (\GuzzleHttp\Exception\BadResponseException $e) {
    // handle exception or api errors.
    print_r($e->getMessage());
 }

 // ...

```

```java
URL obj = new URL("/api/projects/{project_id}/feature_flags/{id}/");
HttpURLConnection con = (HttpURLConnection) obj.openConnection();
con.setRequestMethod("DELETE");
int responseCode = con.getResponseCode();
BufferedReader in = new BufferedReader(
    new InputStreamReader(con.getInputStream()));
String inputLine;
StringBuffer response = new StringBuffer();
while ((inputLine = in.readLine()) != null) {
    response.append(inputLine);
}
in.close();
System.out.println(response.toString());

```

```go
package main

import (
       "bytes"
       "net/http"
)

func main() {

    data := bytes.NewBuffer([]byte{jsonReq})
    req, err := http.NewRequest("DELETE", "/api/projects/{project_id}/feature_flags/{id}/", data)
    req.Header = headers

    client := &http.Client{}
    resp, err := client.Do(req)
    // ...
}

```

`DELETE /api/projects/{project_id}/feature_flags/{id}/`

Create, read, update and delete feature flags. [See docs](https://posthog.com/docs/user-guides/feature-flags) for more information on feature flags.

<h3 id="feature_flags_destroy-parameters">Parameters</h3>

|Name|In|Type|Required|Description|
|---|---|---|---|---|
|id|path|integer|true|A unique integer value identifying this feature flag.|
|project_id|path|string|true|Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/.|

<h3 id="feature_flags_destroy-responses">Responses</h3>

|Status|Meaning|Description|Schema|
|---|---|---|---|
|204|[No Content](https://tools.ietf.org/html/rfc7231#section-6.3.5)|No response body|None|

<aside class="success">
This operation does not require authentication
</aside>

## feature_flags_my_flags_retrieve

<a id="opIdfeature_flags_my_flags_retrieve"></a>

> Code samples

```shell
# You can also use wget
curl -X GET /api/projects/{project_id}/feature_flags/my_flags/ \
  -H 'Accept: application/json'

```

```http
GET /api/projects/{project_id}/feature_flags/my_flags/ HTTP/1.1

Accept: application/json

```

```javascript

const headers = {
  'Accept':'application/json'
};

fetch('/api/projects/{project_id}/feature_flags/my_flags/',
{
  method: 'GET',

  headers: headers
})
.then(function(res) {
    return res.json();
}).then(function(body) {
    console.log(body);
});

```

```ruby
require 'rest-client'
require 'json'

headers = {
  'Accept' => 'application/json'
}

result = RestClient.get '/api/projects/{project_id}/feature_flags/my_flags/',
  params: {
  }, headers: headers

p JSON.parse(result)

```

```python
import requests
headers = {
  'Accept': 'application/json'
}

r = requests.get('/api/projects/{project_id}/feature_flags/my_flags/', headers = headers)

print(r.json())

```

```php
<?php

require 'vendor/autoload.php';

$headers = array(
    'Accept' => 'application/json',
);

$client = new \GuzzleHttp\Client();

// Define array of request body.
$request_body = array();

try {
    $response = $client->request('GET','/api/projects/{project_id}/feature_flags/my_flags/', array(
        'headers' => $headers,
        'json' => $request_body,
       )
    );
    print_r($response->getBody()->getContents());
 }
 catch (\GuzzleHttp\Exception\BadResponseException $e) {
    // handle exception or api errors.
    print_r($e->getMessage());
 }

 // ...

```

```java
URL obj = new URL("/api/projects/{project_id}/feature_flags/my_flags/");
HttpURLConnection con = (HttpURLConnection) obj.openConnection();
con.setRequestMethod("GET");
int responseCode = con.getResponseCode();
BufferedReader in = new BufferedReader(
    new InputStreamReader(con.getInputStream()));
String inputLine;
StringBuffer response = new StringBuffer();
while ((inputLine = in.readLine()) != null) {
    response.append(inputLine);
}
in.close();
System.out.println(response.toString());

```

```go
package main

import (
       "bytes"
       "net/http"
)

func main() {

    headers := map[string][]string{
        "Accept": []string{"application/json"},
    }

    data := bytes.NewBuffer([]byte{jsonReq})
    req, err := http.NewRequest("GET", "/api/projects/{project_id}/feature_flags/my_flags/", data)
    req.Header = headers

    client := &http.Client{}
    resp, err := client.Do(req)
    // ...
}

```

`GET /api/projects/{project_id}/feature_flags/my_flags/`

Create, read, update and delete feature flags. [See docs](https://posthog.com/docs/user-guides/feature-flags) for more information on feature flags.

<h3 id="feature_flags_my_flags_retrieve-parameters">Parameters</h3>

|Name|In|Type|Required|Description|
|---|---|---|---|---|
|project_id|path|string|true|Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/.|

> Example responses

> 200 Response

```json
{
  "id": 0,
  "name": "string",
  "key": "string",
  "filters": {
    "property1": null,
    "property2": null
  },
  "deleted": true,
  "active": true,
  "created_by": {
    "id": 0,
    "uuid": "095be615-a8ad-4c33-8e9c-c7612fbf6c9f",
    "distinct_id": "string",
    "first_name": "string",
    "email": "user@example.com"
  },
  "created_at": "2019-08-24T14:15:22Z",
  "is_simple_flag": true,
  "rollout_percentage": 0
}
```

<h3 id="feature_flags_my_flags_retrieve-responses">Responses</h3>

|Status|Meaning|Description|Schema|
|---|---|---|---|
|200|[OK](https://tools.ietf.org/html/rfc7231#section-6.3.1)|none|[FeatureFlag](#schemafeatureflag)|

<aside class="success">
This operation does not require authentication
</aside>

<h1 id="-groups">groups</h1>

## groups_list

<a id="opIdgroups_list"></a>

> Code samples

```shell
# You can also use wget
curl -X GET /api/projects/{project_id}/groups/ \
  -H 'Accept: application/json'

```

```http
GET /api/projects/{project_id}/groups/ HTTP/1.1

Accept: application/json

```

```javascript

const headers = {
  'Accept':'application/json'
};

fetch('/api/projects/{project_id}/groups/',
{
  method: 'GET',

  headers: headers
})
.then(function(res) {
    return res.json();
}).then(function(body) {
    console.log(body);
});

```

```ruby
require 'rest-client'
require 'json'

headers = {
  'Accept' => 'application/json'
}

result = RestClient.get '/api/projects/{project_id}/groups/',
  params: {
  }, headers: headers

p JSON.parse(result)

```

```python
import requests
headers = {
  'Accept': 'application/json'
}

r = requests.get('/api/projects/{project_id}/groups/', headers = headers)

print(r.json())

```

```php
<?php

require 'vendor/autoload.php';

$headers = array(
    'Accept' => 'application/json',
);

$client = new \GuzzleHttp\Client();

// Define array of request body.
$request_body = array();

try {
    $response = $client->request('GET','/api/projects/{project_id}/groups/', array(
        'headers' => $headers,
        'json' => $request_body,
       )
    );
    print_r($response->getBody()->getContents());
 }
 catch (\GuzzleHttp\Exception\BadResponseException $e) {
    // handle exception or api errors.
    print_r($e->getMessage());
 }

 // ...

```

```java
URL obj = new URL("/api/projects/{project_id}/groups/");
HttpURLConnection con = (HttpURLConnection) obj.openConnection();
con.setRequestMethod("GET");
int responseCode = con.getResponseCode();
BufferedReader in = new BufferedReader(
    new InputStreamReader(con.getInputStream()));
String inputLine;
StringBuffer response = new StringBuffer();
while ((inputLine = in.readLine()) != null) {
    response.append(inputLine);
}
in.close();
System.out.println(response.toString());

```

```go
package main

import (
       "bytes"
       "net/http"
)

func main() {

    headers := map[string][]string{
        "Accept": []string{"application/json"},
    }

    data := bytes.NewBuffer([]byte{jsonReq})
    req, err := http.NewRequest("GET", "/api/projects/{project_id}/groups/", data)
    req.Header = headers

    client := &http.Client{}
    resp, err := client.Do(req)
    // ...
}

```

`GET /api/projects/{project_id}/groups/`

<h3 id="groups_list-parameters">Parameters</h3>

|Name|In|Type|Required|Description|
|---|---|---|---|---|
|cursor|query|integer|false|The pagination cursor value.|
|project_id|path|string|true|Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/.|

> Example responses

> 200 Response

```json
{
  "next": "string",
  "previous": "string",
  "results": [
    {
      "group_type_index": -2147483648,
      "group_key": "string",
      "group_properties": {
        "property1": null,
        "property2": null
      },
      "created_at": "2019-08-24T14:15:22Z"
    }
  ]
}
```

<h3 id="groups_list-responses">Responses</h3>

|Status|Meaning|Description|Schema|
|---|---|---|---|
|200|[OK](https://tools.ietf.org/html/rfc7231#section-6.3.1)|none|[PaginatedGroupList](#schemapaginatedgrouplist)|

<aside class="success">
This operation does not require authentication
</aside>

## groups_find_retrieve

<a id="opIdgroups_find_retrieve"></a>

> Code samples

```shell
# You can also use wget
curl -X GET /api/projects/{project_id}/groups/find/ \
  -H 'Accept: application/json'

```

```http
GET /api/projects/{project_id}/groups/find/ HTTP/1.1

Accept: application/json

```

```javascript

const headers = {
  'Accept':'application/json'
};

fetch('/api/projects/{project_id}/groups/find/',
{
  method: 'GET',

  headers: headers
})
.then(function(res) {
    return res.json();
}).then(function(body) {
    console.log(body);
});

```

```ruby
require 'rest-client'
require 'json'

headers = {
  'Accept' => 'application/json'
}

result = RestClient.get '/api/projects/{project_id}/groups/find/',
  params: {
  }, headers: headers

p JSON.parse(result)

```

```python
import requests
headers = {
  'Accept': 'application/json'
}

r = requests.get('/api/projects/{project_id}/groups/find/', headers = headers)

print(r.json())

```

```php
<?php

require 'vendor/autoload.php';

$headers = array(
    'Accept' => 'application/json',
);

$client = new \GuzzleHttp\Client();

// Define array of request body.
$request_body = array();

try {
    $response = $client->request('GET','/api/projects/{project_id}/groups/find/', array(
        'headers' => $headers,
        'json' => $request_body,
       )
    );
    print_r($response->getBody()->getContents());
 }
 catch (\GuzzleHttp\Exception\BadResponseException $e) {
    // handle exception or api errors.
    print_r($e->getMessage());
 }

 // ...

```

```java
URL obj = new URL("/api/projects/{project_id}/groups/find/");
HttpURLConnection con = (HttpURLConnection) obj.openConnection();
con.setRequestMethod("GET");
int responseCode = con.getResponseCode();
BufferedReader in = new BufferedReader(
    new InputStreamReader(con.getInputStream()));
String inputLine;
StringBuffer response = new StringBuffer();
while ((inputLine = in.readLine()) != null) {
    response.append(inputLine);
}
in.close();
System.out.println(response.toString());

```

```go
package main

import (
       "bytes"
       "net/http"
)

func main() {

    headers := map[string][]string{
        "Accept": []string{"application/json"},
    }

    data := bytes.NewBuffer([]byte{jsonReq})
    req, err := http.NewRequest("GET", "/api/projects/{project_id}/groups/find/", data)
    req.Header = headers

    client := &http.Client{}
    resp, err := client.Do(req)
    // ...
}

```

`GET /api/projects/{project_id}/groups/find/`

<h3 id="groups_find_retrieve-parameters">Parameters</h3>

|Name|In|Type|Required|Description|
|---|---|---|---|---|
|project_id|path|string|true|Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/.|

> Example responses

> 200 Response

```json
{
  "group_type_index": -2147483648,
  "group_key": "string",
  "group_properties": {
    "property1": null,
    "property2": null
  },
  "created_at": "2019-08-24T14:15:22Z"
}
```

<h3 id="groups_find_retrieve-responses">Responses</h3>

|Status|Meaning|Description|Schema|
|---|---|---|---|
|200|[OK](https://tools.ietf.org/html/rfc7231#section-6.3.1)|none|[Group](#schemagroup)|

<aside class="success">
This operation does not require authentication
</aside>

## groups_property_definitions_retrieve

<a id="opIdgroups_property_definitions_retrieve"></a>

> Code samples

```shell
# You can also use wget
curl -X GET /api/projects/{project_id}/groups/property_definitions/ \
  -H 'Accept: application/json'

```

```http
GET /api/projects/{project_id}/groups/property_definitions/ HTTP/1.1

Accept: application/json

```

```javascript

const headers = {
  'Accept':'application/json'
};

fetch('/api/projects/{project_id}/groups/property_definitions/',
{
  method: 'GET',

  headers: headers
})
.then(function(res) {
    return res.json();
}).then(function(body) {
    console.log(body);
});

```

```ruby
require 'rest-client'
require 'json'

headers = {
  'Accept' => 'application/json'
}

result = RestClient.get '/api/projects/{project_id}/groups/property_definitions/',
  params: {
  }, headers: headers

p JSON.parse(result)

```

```python
import requests
headers = {
  'Accept': 'application/json'
}

r = requests.get('/api/projects/{project_id}/groups/property_definitions/', headers = headers)

print(r.json())

```

```php
<?php

require 'vendor/autoload.php';

$headers = array(
    'Accept' => 'application/json',
);

$client = new \GuzzleHttp\Client();

// Define array of request body.
$request_body = array();

try {
    $response = $client->request('GET','/api/projects/{project_id}/groups/property_definitions/', array(
        'headers' => $headers,
        'json' => $request_body,
       )
    );
    print_r($response->getBody()->getContents());
 }
 catch (\GuzzleHttp\Exception\BadResponseException $e) {
    // handle exception or api errors.
    print_r($e->getMessage());
 }

 // ...

```

```java
URL obj = new URL("/api/projects/{project_id}/groups/property_definitions/");
HttpURLConnection con = (HttpURLConnection) obj.openConnection();
con.setRequestMethod("GET");
int responseCode = con.getResponseCode();
BufferedReader in = new BufferedReader(
    new InputStreamReader(con.getInputStream()));
String inputLine;
StringBuffer response = new StringBuffer();
while ((inputLine = in.readLine()) != null) {
    response.append(inputLine);
}
in.close();
System.out.println(response.toString());

```

```go
package main

import (
       "bytes"
       "net/http"
)

func main() {

    headers := map[string][]string{
        "Accept": []string{"application/json"},
    }

    data := bytes.NewBuffer([]byte{jsonReq})
    req, err := http.NewRequest("GET", "/api/projects/{project_id}/groups/property_definitions/", data)
    req.Header = headers

    client := &http.Client{}
    resp, err := client.Do(req)
    // ...
}

```

`GET /api/projects/{project_id}/groups/property_definitions/`

<h3 id="groups_property_definitions_retrieve-parameters">Parameters</h3>

|Name|In|Type|Required|Description|
|---|---|---|---|---|
|project_id|path|string|true|Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/.|

> Example responses

> 200 Response

```json
{
  "group_type_index": -2147483648,
  "group_key": "string",
  "group_properties": {
    "property1": null,
    "property2": null
  },
  "created_at": "2019-08-24T14:15:22Z"
}
```

<h3 id="groups_property_definitions_retrieve-responses">Responses</h3>

|Status|Meaning|Description|Schema|
|---|---|---|---|
|200|[OK](https://tools.ietf.org/html/rfc7231#section-6.3.1)|none|[Group](#schemagroup)|

<aside class="success">
This operation does not require authentication
</aside>

## groups_property_values_retrieve

<a id="opIdgroups_property_values_retrieve"></a>

> Code samples

```shell
# You can also use wget
curl -X GET /api/projects/{project_id}/groups/property_values/ \
  -H 'Accept: application/json'

```

```http
GET /api/projects/{project_id}/groups/property_values/ HTTP/1.1

Accept: application/json

```

```javascript

const headers = {
  'Accept':'application/json'
};

fetch('/api/projects/{project_id}/groups/property_values/',
{
  method: 'GET',

  headers: headers
})
.then(function(res) {
    return res.json();
}).then(function(body) {
    console.log(body);
});

```

```ruby
require 'rest-client'
require 'json'

headers = {
  'Accept' => 'application/json'
}

result = RestClient.get '/api/projects/{project_id}/groups/property_values/',
  params: {
  }, headers: headers

p JSON.parse(result)

```

```python
import requests
headers = {
  'Accept': 'application/json'
}

r = requests.get('/api/projects/{project_id}/groups/property_values/', headers = headers)

print(r.json())

```

```php
<?php

require 'vendor/autoload.php';

$headers = array(
    'Accept' => 'application/json',
);

$client = new \GuzzleHttp\Client();

// Define array of request body.
$request_body = array();

try {
    $response = $client->request('GET','/api/projects/{project_id}/groups/property_values/', array(
        'headers' => $headers,
        'json' => $request_body,
       )
    );
    print_r($response->getBody()->getContents());
 }
 catch (\GuzzleHttp\Exception\BadResponseException $e) {
    // handle exception or api errors.
    print_r($e->getMessage());
 }

 // ...

```

```java
URL obj = new URL("/api/projects/{project_id}/groups/property_values/");
HttpURLConnection con = (HttpURLConnection) obj.openConnection();
con.setRequestMethod("GET");
int responseCode = con.getResponseCode();
BufferedReader in = new BufferedReader(
    new InputStreamReader(con.getInputStream()));
String inputLine;
StringBuffer response = new StringBuffer();
while ((inputLine = in.readLine()) != null) {
    response.append(inputLine);
}
in.close();
System.out.println(response.toString());

```

```go
package main

import (
       "bytes"
       "net/http"
)

func main() {

    headers := map[string][]string{
        "Accept": []string{"application/json"},
    }

    data := bytes.NewBuffer([]byte{jsonReq})
    req, err := http.NewRequest("GET", "/api/projects/{project_id}/groups/property_values/", data)
    req.Header = headers

    client := &http.Client{}
    resp, err := client.Do(req)
    // ...
}

```

`GET /api/projects/{project_id}/groups/property_values/`

<h3 id="groups_property_values_retrieve-parameters">Parameters</h3>

|Name|In|Type|Required|Description|
|---|---|---|---|---|
|project_id|path|string|true|Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/.|

> Example responses

> 200 Response

```json
{
  "group_type_index": -2147483648,
  "group_key": "string",
  "group_properties": {
    "property1": null,
    "property2": null
  },
  "created_at": "2019-08-24T14:15:22Z"
}
```

<h3 id="groups_property_values_retrieve-responses">Responses</h3>

|Status|Meaning|Description|Schema|
|---|---|---|---|
|200|[OK](https://tools.ietf.org/html/rfc7231#section-6.3.1)|none|[Group](#schemagroup)|

<aside class="success">
This operation does not require authentication
</aside>

## groups_related_retrieve

<a id="opIdgroups_related_retrieve"></a>

> Code samples

```shell
# You can also use wget
curl -X GET /api/projects/{project_id}/groups/related/ \
  -H 'Accept: application/json'

```

```http
GET /api/projects/{project_id}/groups/related/ HTTP/1.1

Accept: application/json

```

```javascript

const headers = {
  'Accept':'application/json'
};

fetch('/api/projects/{project_id}/groups/related/',
{
  method: 'GET',

  headers: headers
})
.then(function(res) {
    return res.json();
}).then(function(body) {
    console.log(body);
});

```

```ruby
require 'rest-client'
require 'json'

headers = {
  'Accept' => 'application/json'
}

result = RestClient.get '/api/projects/{project_id}/groups/related/',
  params: {
  }, headers: headers

p JSON.parse(result)

```

```python
import requests
headers = {
  'Accept': 'application/json'
}

r = requests.get('/api/projects/{project_id}/groups/related/', headers = headers)

print(r.json())

```

```php
<?php

require 'vendor/autoload.php';

$headers = array(
    'Accept' => 'application/json',
);

$client = new \GuzzleHttp\Client();

// Define array of request body.
$request_body = array();

try {
    $response = $client->request('GET','/api/projects/{project_id}/groups/related/', array(
        'headers' => $headers,
        'json' => $request_body,
       )
    );
    print_r($response->getBody()->getContents());
 }
 catch (\GuzzleHttp\Exception\BadResponseException $e) {
    // handle exception or api errors.
    print_r($e->getMessage());
 }

 // ...

```

```java
URL obj = new URL("/api/projects/{project_id}/groups/related/");
HttpURLConnection con = (HttpURLConnection) obj.openConnection();
con.setRequestMethod("GET");
int responseCode = con.getResponseCode();
BufferedReader in = new BufferedReader(
    new InputStreamReader(con.getInputStream()));
String inputLine;
StringBuffer response = new StringBuffer();
while ((inputLine = in.readLine()) != null) {
    response.append(inputLine);
}
in.close();
System.out.println(response.toString());

```

```go
package main

import (
       "bytes"
       "net/http"
)

func main() {

    headers := map[string][]string{
        "Accept": []string{"application/json"},
    }

    data := bytes.NewBuffer([]byte{jsonReq})
    req, err := http.NewRequest("GET", "/api/projects/{project_id}/groups/related/", data)
    req.Header = headers

    client := &http.Client{}
    resp, err := client.Do(req)
    // ...
}

```

`GET /api/projects/{project_id}/groups/related/`

<h3 id="groups_related_retrieve-parameters">Parameters</h3>

|Name|In|Type|Required|Description|
|---|---|---|---|---|
|project_id|path|string|true|Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/.|

> Example responses

> 200 Response

```json
{
  "group_type_index": -2147483648,
  "group_key": "string",
  "group_properties": {
    "property1": null,
    "property2": null
  },
  "created_at": "2019-08-24T14:15:22Z"
}
```

<h3 id="groups_related_retrieve-responses">Responses</h3>

|Status|Meaning|Description|Schema|
|---|---|---|---|
|200|[OK](https://tools.ietf.org/html/rfc7231#section-6.3.1)|none|[Group](#schemagroup)|

<aside class="success">
This operation does not require authentication
</aside>

<h1 id="-groups_types">groups_types</h1>

## groups_types_list

<a id="opIdgroups_types_list"></a>

> Code samples

```shell
# You can also use wget
curl -X GET /api/projects/{project_id}/groups_types/ \
  -H 'Accept: application/json'

```

```http
GET /api/projects/{project_id}/groups_types/ HTTP/1.1

Accept: application/json

```

```javascript

const headers = {
  'Accept':'application/json'
};

fetch('/api/projects/{project_id}/groups_types/',
{
  method: 'GET',

  headers: headers
})
.then(function(res) {
    return res.json();
}).then(function(body) {
    console.log(body);
});

```

```ruby
require 'rest-client'
require 'json'

headers = {
  'Accept' => 'application/json'
}

result = RestClient.get '/api/projects/{project_id}/groups_types/',
  params: {
  }, headers: headers

p JSON.parse(result)

```

```python
import requests
headers = {
  'Accept': 'application/json'
}

r = requests.get('/api/projects/{project_id}/groups_types/', headers = headers)

print(r.json())

```

```php
<?php

require 'vendor/autoload.php';

$headers = array(
    'Accept' => 'application/json',
);

$client = new \GuzzleHttp\Client();

// Define array of request body.
$request_body = array();

try {
    $response = $client->request('GET','/api/projects/{project_id}/groups_types/', array(
        'headers' => $headers,
        'json' => $request_body,
       )
    );
    print_r($response->getBody()->getContents());
 }
 catch (\GuzzleHttp\Exception\BadResponseException $e) {
    // handle exception or api errors.
    print_r($e->getMessage());
 }

 // ...

```

```java
URL obj = new URL("/api/projects/{project_id}/groups_types/");
HttpURLConnection con = (HttpURLConnection) obj.openConnection();
con.setRequestMethod("GET");
int responseCode = con.getResponseCode();
BufferedReader in = new BufferedReader(
    new InputStreamReader(con.getInputStream()));
String inputLine;
StringBuffer response = new StringBuffer();
while ((inputLine = in.readLine()) != null) {
    response.append(inputLine);
}
in.close();
System.out.println(response.toString());

```

```go
package main

import (
       "bytes"
       "net/http"
)

func main() {

    headers := map[string][]string{
        "Accept": []string{"application/json"},
    }

    data := bytes.NewBuffer([]byte{jsonReq})
    req, err := http.NewRequest("GET", "/api/projects/{project_id}/groups_types/", data)
    req.Header = headers

    client := &http.Client{}
    resp, err := client.Do(req)
    // ...
}

```

`GET /api/projects/{project_id}/groups_types/`

<h3 id="groups_types_list-parameters">Parameters</h3>

|Name|In|Type|Required|Description|
|---|---|---|---|---|
|project_id|path|string|true|Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/.|

> Example responses

> 200 Response

```json
[
  {
    "group_type": "string",
    "group_type_index": 0,
    "name_singular": "string",
    "name_plural": "string"
  }
]
```

<h3 id="groups_types_list-responses">Responses</h3>

|Status|Meaning|Description|Schema|
|---|---|---|---|
|200|[OK](https://tools.ietf.org/html/rfc7231#section-6.3.1)|none|Inline|

<h3 id="groups_types_list-responseschema">Response Schema</h3>

Status Code **200**

|Name|Type|Required|Restrictions|Description|
|---|---|---|---|---|
|*anonymous*|[[GroupType](#schemagrouptype)]|false|none|none|
|» group_type|string|true|read-only|none|
|» group_type_index|integer|true|read-only|none|
|» name_singular|string¦null|false|none|none|
|» name_plural|string¦null|false|none|none|

<aside class="success">
This operation does not require authentication
</aside>

## groups_types_update_metadata_partial_update

<a id="opIdgroups_types_update_metadata_partial_update"></a>

> Code samples

```shell
# You can also use wget
curl -X PATCH /api/projects/{project_id}/groups_types/update_metadata/ \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json'

```

```http
PATCH /api/projects/{project_id}/groups_types/update_metadata/ HTTP/1.1

Content-Type: application/json
Accept: application/json

```

```javascript
const inputBody = '{
  "name_singular": "string",
  "name_plural": "string"
}';
const headers = {
  'Content-Type':'application/json',
  'Accept':'application/json'
};

fetch('/api/projects/{project_id}/groups_types/update_metadata/',
{
  method: 'PATCH',
  body: inputBody,
  headers: headers
})
.then(function(res) {
    return res.json();
}).then(function(body) {
    console.log(body);
});

```

```ruby
require 'rest-client'
require 'json'

headers = {
  'Content-Type' => 'application/json',
  'Accept' => 'application/json'
}

result = RestClient.patch '/api/projects/{project_id}/groups_types/update_metadata/',
  params: {
  }, headers: headers

p JSON.parse(result)

```

```python
import requests
headers = {
  'Content-Type': 'application/json',
  'Accept': 'application/json'
}

r = requests.patch('/api/projects/{project_id}/groups_types/update_metadata/', headers = headers)

print(r.json())

```

```php
<?php

require 'vendor/autoload.php';

$headers = array(
    'Content-Type' => 'application/json',
    'Accept' => 'application/json',
);

$client = new \GuzzleHttp\Client();

// Define array of request body.
$request_body = array();

try {
    $response = $client->request('PATCH','/api/projects/{project_id}/groups_types/update_metadata/', array(
        'headers' => $headers,
        'json' => $request_body,
       )
    );
    print_r($response->getBody()->getContents());
 }
 catch (\GuzzleHttp\Exception\BadResponseException $e) {
    // handle exception or api errors.
    print_r($e->getMessage());
 }

 // ...

```

```java
URL obj = new URL("/api/projects/{project_id}/groups_types/update_metadata/");
HttpURLConnection con = (HttpURLConnection) obj.openConnection();
con.setRequestMethod("PATCH");
int responseCode = con.getResponseCode();
BufferedReader in = new BufferedReader(
    new InputStreamReader(con.getInputStream()));
String inputLine;
StringBuffer response = new StringBuffer();
while ((inputLine = in.readLine()) != null) {
    response.append(inputLine);
}
in.close();
System.out.println(response.toString());

```

```go
package main

import (
       "bytes"
       "net/http"
)

func main() {

    headers := map[string][]string{
        "Content-Type": []string{"application/json"},
        "Accept": []string{"application/json"},
    }

    data := bytes.NewBuffer([]byte{jsonReq})
    req, err := http.NewRequest("PATCH", "/api/projects/{project_id}/groups_types/update_metadata/", data)
    req.Header = headers

    client := &http.Client{}
    resp, err := client.Do(req)
    // ...
}

```

`PATCH /api/projects/{project_id}/groups_types/update_metadata/`

> Body parameter

```json
{
  "name_singular": "string",
  "name_plural": "string"
}
```

```yaml
name_singular: string
name_plural: string

```

<h3 id="groups_types_update_metadata_partial_update-parameters">Parameters</h3>

|Name|In|Type|Required|Description|
|---|---|---|---|---|
|project_id|path|string|true|Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/.|
|body|body|[PatchedGroupType](#schemapatchedgrouptype)|false|none|

> Example responses

> 200 Response

```json
{
  "group_type": "string",
  "group_type_index": 0,
  "name_singular": "string",
  "name_plural": "string"
}
```

<h3 id="groups_types_update_metadata_partial_update-responses">Responses</h3>

|Status|Meaning|Description|Schema|
|---|---|---|---|
|200|[OK](https://tools.ietf.org/html/rfc7231#section-6.3.1)|none|[GroupType](#schemagrouptype)|

<aside class="success">
This operation does not require authentication
</aside>

<h1 id="-hooks">hooks</h1>

## hooks_list

<a id="opIdhooks_list"></a>

> Code samples

```shell
# You can also use wget
curl -X GET /api/projects/{project_id}/hooks/ \
  -H 'Accept: application/json'

```

```http
GET /api/projects/{project_id}/hooks/ HTTP/1.1

Accept: application/json

```

```javascript

const headers = {
  'Accept':'application/json'
};

fetch('/api/projects/{project_id}/hooks/',
{
  method: 'GET',

  headers: headers
})
.then(function(res) {
    return res.json();
}).then(function(body) {
    console.log(body);
});

```

```ruby
require 'rest-client'
require 'json'

headers = {
  'Accept' => 'application/json'
}

result = RestClient.get '/api/projects/{project_id}/hooks/',
  params: {
  }, headers: headers

p JSON.parse(result)

```

```python
import requests
headers = {
  'Accept': 'application/json'
}

r = requests.get('/api/projects/{project_id}/hooks/', headers = headers)

print(r.json())

```

```php
<?php

require 'vendor/autoload.php';

$headers = array(
    'Accept' => 'application/json',
);

$client = new \GuzzleHttp\Client();

// Define array of request body.
$request_body = array();

try {
    $response = $client->request('GET','/api/projects/{project_id}/hooks/', array(
        'headers' => $headers,
        'json' => $request_body,
       )
    );
    print_r($response->getBody()->getContents());
 }
 catch (\GuzzleHttp\Exception\BadResponseException $e) {
    // handle exception or api errors.
    print_r($e->getMessage());
 }

 // ...

```

```java
URL obj = new URL("/api/projects/{project_id}/hooks/");
HttpURLConnection con = (HttpURLConnection) obj.openConnection();
con.setRequestMethod("GET");
int responseCode = con.getResponseCode();
BufferedReader in = new BufferedReader(
    new InputStreamReader(con.getInputStream()));
String inputLine;
StringBuffer response = new StringBuffer();
while ((inputLine = in.readLine()) != null) {
    response.append(inputLine);
}
in.close();
System.out.println(response.toString());

```

```go
package main

import (
       "bytes"
       "net/http"
)

func main() {

    headers := map[string][]string{
        "Accept": []string{"application/json"},
    }

    data := bytes.NewBuffer([]byte{jsonReq})
    req, err := http.NewRequest("GET", "/api/projects/{project_id}/hooks/", data)
    req.Header = headers

    client := &http.Client{}
    resp, err := client.Do(req)
    // ...
}

```

`GET /api/projects/{project_id}/hooks/`

Retrieve, create, update or destroy REST hooks.

<h3 id="hooks_list-parameters">Parameters</h3>

|Name|In|Type|Required|Description|
|---|---|---|---|---|
|limit|query|integer|false|Number of results to return per page.|
|offset|query|integer|false|The initial index from which to return the results.|
|project_id|path|string|true|Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/.|

> Example responses

> 200 Response

```json
{
  "count": 123,
  "next": "http://api.example.org/accounts/?offset=400&limit=100",
  "previous": "http://api.example.org/accounts/?offset=200&limit=100",
  "results": [
    {
      "id": "string",
      "created": "2019-08-24T14:15:22Z",
      "updated": "2019-08-24T14:15:22Z",
      "event": "string",
      "target": "http://example.com",
      "resource_id": -2147483648,
      "team": 0
    }
  ]
}
```

<h3 id="hooks_list-responses">Responses</h3>

|Status|Meaning|Description|Schema|
|---|---|---|---|
|200|[OK](https://tools.ietf.org/html/rfc7231#section-6.3.1)|none|[PaginatedHookList](#schemapaginatedhooklist)|

<aside class="success">
This operation does not require authentication
</aside>

## hooks_create

<a id="opIdhooks_create"></a>

> Code samples

```shell
# You can also use wget
curl -X POST /api/projects/{project_id}/hooks/ \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json'

```

```http
POST /api/projects/{project_id}/hooks/ HTTP/1.1

Content-Type: application/json
Accept: application/json

```

```javascript
const inputBody = '{
  "id": "string",
  "event": "string",
  "target": "http://example.com",
  "resource_id": -2147483648
}';
const headers = {
  'Content-Type':'application/json',
  'Accept':'application/json'
};

fetch('/api/projects/{project_id}/hooks/',
{
  method: 'POST',
  body: inputBody,
  headers: headers
})
.then(function(res) {
    return res.json();
}).then(function(body) {
    console.log(body);
});

```

```ruby
require 'rest-client'
require 'json'

headers = {
  'Content-Type' => 'application/json',
  'Accept' => 'application/json'
}

result = RestClient.post '/api/projects/{project_id}/hooks/',
  params: {
  }, headers: headers

p JSON.parse(result)

```

```python
import requests
headers = {
  'Content-Type': 'application/json',
  'Accept': 'application/json'
}

r = requests.post('/api/projects/{project_id}/hooks/', headers = headers)

print(r.json())

```

```php
<?php

require 'vendor/autoload.php';

$headers = array(
    'Content-Type' => 'application/json',
    'Accept' => 'application/json',
);

$client = new \GuzzleHttp\Client();

// Define array of request body.
$request_body = array();

try {
    $response = $client->request('POST','/api/projects/{project_id}/hooks/', array(
        'headers' => $headers,
        'json' => $request_body,
       )
    );
    print_r($response->getBody()->getContents());
 }
 catch (\GuzzleHttp\Exception\BadResponseException $e) {
    // handle exception or api errors.
    print_r($e->getMessage());
 }

 // ...

```

```java
URL obj = new URL("/api/projects/{project_id}/hooks/");
HttpURLConnection con = (HttpURLConnection) obj.openConnection();
con.setRequestMethod("POST");
int responseCode = con.getResponseCode();
BufferedReader in = new BufferedReader(
    new InputStreamReader(con.getInputStream()));
String inputLine;
StringBuffer response = new StringBuffer();
while ((inputLine = in.readLine()) != null) {
    response.append(inputLine);
}
in.close();
System.out.println(response.toString());

```

```go
package main

import (
       "bytes"
       "net/http"
)

func main() {

    headers := map[string][]string{
        "Content-Type": []string{"application/json"},
        "Accept": []string{"application/json"},
    }

    data := bytes.NewBuffer([]byte{jsonReq})
    req, err := http.NewRequest("POST", "/api/projects/{project_id}/hooks/", data)
    req.Header = headers

    client := &http.Client{}
    resp, err := client.Do(req)
    // ...
}

```

`POST /api/projects/{project_id}/hooks/`

Retrieve, create, update or destroy REST hooks.

> Body parameter

```json
{
  "id": "string",
  "event": "string",
  "target": "http://example.com",
  "resource_id": -2147483648
}
```

```yaml
id: string
event: string
target: http://example.com
resource_id: -2147483648

```

<h3 id="hooks_create-parameters">Parameters</h3>

|Name|In|Type|Required|Description|
|---|---|---|---|---|
|project_id|path|string|true|Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/.|
|body|body|[Hook](#schemahook)|true|none|

> Example responses

> 201 Response

```json
{
  "id": "string",
  "created": "2019-08-24T14:15:22Z",
  "updated": "2019-08-24T14:15:22Z",
  "event": "string",
  "target": "http://example.com",
  "resource_id": -2147483648,
  "team": 0
}
```

<h3 id="hooks_create-responses">Responses</h3>

|Status|Meaning|Description|Schema|
|---|---|---|---|
|201|[Created](https://tools.ietf.org/html/rfc7231#section-6.3.2)|none|[Hook](#schemahook)|

<aside class="success">
This operation does not require authentication
</aside>

## hooks_retrieve

<a id="opIdhooks_retrieve"></a>

> Code samples

```shell
# You can also use wget
curl -X GET /api/projects/{project_id}/hooks/{id}/ \
  -H 'Accept: application/json'

```

```http
GET /api/projects/{project_id}/hooks/{id}/ HTTP/1.1

Accept: application/json

```

```javascript

const headers = {
  'Accept':'application/json'
};

fetch('/api/projects/{project_id}/hooks/{id}/',
{
  method: 'GET',

  headers: headers
})
.then(function(res) {
    return res.json();
}).then(function(body) {
    console.log(body);
});

```

```ruby
require 'rest-client'
require 'json'

headers = {
  'Accept' => 'application/json'
}

result = RestClient.get '/api/projects/{project_id}/hooks/{id}/',
  params: {
  }, headers: headers

p JSON.parse(result)

```

```python
import requests
headers = {
  'Accept': 'application/json'
}

r = requests.get('/api/projects/{project_id}/hooks/{id}/', headers = headers)

print(r.json())

```

```php
<?php

require 'vendor/autoload.php';

$headers = array(
    'Accept' => 'application/json',
);

$client = new \GuzzleHttp\Client();

// Define array of request body.
$request_body = array();

try {
    $response = $client->request('GET','/api/projects/{project_id}/hooks/{id}/', array(
        'headers' => $headers,
        'json' => $request_body,
       )
    );
    print_r($response->getBody()->getContents());
 }
 catch (\GuzzleHttp\Exception\BadResponseException $e) {
    // handle exception or api errors.
    print_r($e->getMessage());
 }

 // ...

```

```java
URL obj = new URL("/api/projects/{project_id}/hooks/{id}/");
HttpURLConnection con = (HttpURLConnection) obj.openConnection();
con.setRequestMethod("GET");
int responseCode = con.getResponseCode();
BufferedReader in = new BufferedReader(
    new InputStreamReader(con.getInputStream()));
String inputLine;
StringBuffer response = new StringBuffer();
while ((inputLine = in.readLine()) != null) {
    response.append(inputLine);
}
in.close();
System.out.println(response.toString());

```

```go
package main

import (
       "bytes"
       "net/http"
)

func main() {

    headers := map[string][]string{
        "Accept": []string{"application/json"},
    }

    data := bytes.NewBuffer([]byte{jsonReq})
    req, err := http.NewRequest("GET", "/api/projects/{project_id}/hooks/{id}/", data)
    req.Header = headers

    client := &http.Client{}
    resp, err := client.Do(req)
    // ...
}

```

`GET /api/projects/{project_id}/hooks/{id}/`

Retrieve, create, update or destroy REST hooks.

<h3 id="hooks_retrieve-parameters">Parameters</h3>

|Name|In|Type|Required|Description|
|---|---|---|---|---|
|id|path|string|true|A unique value identifying this hook.|
|project_id|path|string|true|Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/.|

> Example responses

> 200 Response

```json
{
  "id": "string",
  "created": "2019-08-24T14:15:22Z",
  "updated": "2019-08-24T14:15:22Z",
  "event": "string",
  "target": "http://example.com",
  "resource_id": -2147483648,
  "team": 0
}
```

<h3 id="hooks_retrieve-responses">Responses</h3>

|Status|Meaning|Description|Schema|
|---|---|---|---|
|200|[OK](https://tools.ietf.org/html/rfc7231#section-6.3.1)|none|[Hook](#schemahook)|

<aside class="success">
This operation does not require authentication
</aside>

## hooks_update

<a id="opIdhooks_update"></a>

> Code samples

```shell
# You can also use wget
curl -X PUT /api/projects/{project_id}/hooks/{id}/ \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json'

```

```http
PUT /api/projects/{project_id}/hooks/{id}/ HTTP/1.1

Content-Type: application/json
Accept: application/json

```

```javascript
const inputBody = '{
  "id": "string",
  "event": "string",
  "target": "http://example.com",
  "resource_id": -2147483648
}';
const headers = {
  'Content-Type':'application/json',
  'Accept':'application/json'
};

fetch('/api/projects/{project_id}/hooks/{id}/',
{
  method: 'PUT',
  body: inputBody,
  headers: headers
})
.then(function(res) {
    return res.json();
}).then(function(body) {
    console.log(body);
});

```

```ruby
require 'rest-client'
require 'json'

headers = {
  'Content-Type' => 'application/json',
  'Accept' => 'application/json'
}

result = RestClient.put '/api/projects/{project_id}/hooks/{id}/',
  params: {
  }, headers: headers

p JSON.parse(result)

```

```python
import requests
headers = {
  'Content-Type': 'application/json',
  'Accept': 'application/json'
}

r = requests.put('/api/projects/{project_id}/hooks/{id}/', headers = headers)

print(r.json())

```

```php
<?php

require 'vendor/autoload.php';

$headers = array(
    'Content-Type' => 'application/json',
    'Accept' => 'application/json',
);

$client = new \GuzzleHttp\Client();

// Define array of request body.
$request_body = array();

try {
    $response = $client->request('PUT','/api/projects/{project_id}/hooks/{id}/', array(
        'headers' => $headers,
        'json' => $request_body,
       )
    );
    print_r($response->getBody()->getContents());
 }
 catch (\GuzzleHttp\Exception\BadResponseException $e) {
    // handle exception or api errors.
    print_r($e->getMessage());
 }

 // ...

```

```java
URL obj = new URL("/api/projects/{project_id}/hooks/{id}/");
HttpURLConnection con = (HttpURLConnection) obj.openConnection();
con.setRequestMethod("PUT");
int responseCode = con.getResponseCode();
BufferedReader in = new BufferedReader(
    new InputStreamReader(con.getInputStream()));
String inputLine;
StringBuffer response = new StringBuffer();
while ((inputLine = in.readLine()) != null) {
    response.append(inputLine);
}
in.close();
System.out.println(response.toString());

```

```go
package main

import (
       "bytes"
       "net/http"
)

func main() {

    headers := map[string][]string{
        "Content-Type": []string{"application/json"},
        "Accept": []string{"application/json"},
    }

    data := bytes.NewBuffer([]byte{jsonReq})
    req, err := http.NewRequest("PUT", "/api/projects/{project_id}/hooks/{id}/", data)
    req.Header = headers

    client := &http.Client{}
    resp, err := client.Do(req)
    // ...
}

```

`PUT /api/projects/{project_id}/hooks/{id}/`

Retrieve, create, update or destroy REST hooks.

> Body parameter

```json
{
  "id": "string",
  "event": "string",
  "target": "http://example.com",
  "resource_id": -2147483648
}
```

```yaml
id: string
event: string
target: http://example.com
resource_id: -2147483648

```

<h3 id="hooks_update-parameters">Parameters</h3>

|Name|In|Type|Required|Description|
|---|---|---|---|---|
|id|path|string|true|A unique value identifying this hook.|
|project_id|path|string|true|Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/.|
|body|body|[Hook](#schemahook)|true|none|

> Example responses

> 200 Response

```json
{
  "id": "string",
  "created": "2019-08-24T14:15:22Z",
  "updated": "2019-08-24T14:15:22Z",
  "event": "string",
  "target": "http://example.com",
  "resource_id": -2147483648,
  "team": 0
}
```

<h3 id="hooks_update-responses">Responses</h3>

|Status|Meaning|Description|Schema|
|---|---|---|---|
|200|[OK](https://tools.ietf.org/html/rfc7231#section-6.3.1)|none|[Hook](#schemahook)|

<aside class="success">
This operation does not require authentication
</aside>

## hooks_partial_update

<a id="opIdhooks_partial_update"></a>

> Code samples

```shell
# You can also use wget
curl -X PATCH /api/projects/{project_id}/hooks/{id}/ \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json'

```

```http
PATCH /api/projects/{project_id}/hooks/{id}/ HTTP/1.1

Content-Type: application/json
Accept: application/json

```

```javascript
const inputBody = '{
  "id": "string",
  "event": "string",
  "target": "http://example.com",
  "resource_id": -2147483648
}';
const headers = {
  'Content-Type':'application/json',
  'Accept':'application/json'
};

fetch('/api/projects/{project_id}/hooks/{id}/',
{
  method: 'PATCH',
  body: inputBody,
  headers: headers
})
.then(function(res) {
    return res.json();
}).then(function(body) {
    console.log(body);
});

```

```ruby
require 'rest-client'
require 'json'

headers = {
  'Content-Type' => 'application/json',
  'Accept' => 'application/json'
}

result = RestClient.patch '/api/projects/{project_id}/hooks/{id}/',
  params: {
  }, headers: headers

p JSON.parse(result)

```

```python
import requests
headers = {
  'Content-Type': 'application/json',
  'Accept': 'application/json'
}

r = requests.patch('/api/projects/{project_id}/hooks/{id}/', headers = headers)

print(r.json())

```

```php
<?php

require 'vendor/autoload.php';

$headers = array(
    'Content-Type' => 'application/json',
    'Accept' => 'application/json',
);

$client = new \GuzzleHttp\Client();

// Define array of request body.
$request_body = array();

try {
    $response = $client->request('PATCH','/api/projects/{project_id}/hooks/{id}/', array(
        'headers' => $headers,
        'json' => $request_body,
       )
    );
    print_r($response->getBody()->getContents());
 }
 catch (\GuzzleHttp\Exception\BadResponseException $e) {
    // handle exception or api errors.
    print_r($e->getMessage());
 }

 // ...

```

```java
URL obj = new URL("/api/projects/{project_id}/hooks/{id}/");
HttpURLConnection con = (HttpURLConnection) obj.openConnection();
con.setRequestMethod("PATCH");
int responseCode = con.getResponseCode();
BufferedReader in = new BufferedReader(
    new InputStreamReader(con.getInputStream()));
String inputLine;
StringBuffer response = new StringBuffer();
while ((inputLine = in.readLine()) != null) {
    response.append(inputLine);
}
in.close();
System.out.println(response.toString());

```

```go
package main

import (
       "bytes"
       "net/http"
)

func main() {

    headers := map[string][]string{
        "Content-Type": []string{"application/json"},
        "Accept": []string{"application/json"},
    }

    data := bytes.NewBuffer([]byte{jsonReq})
    req, err := http.NewRequest("PATCH", "/api/projects/{project_id}/hooks/{id}/", data)
    req.Header = headers

    client := &http.Client{}
    resp, err := client.Do(req)
    // ...
}

```

`PATCH /api/projects/{project_id}/hooks/{id}/`

Retrieve, create, update or destroy REST hooks.

> Body parameter

```json
{
  "id": "string",
  "event": "string",
  "target": "http://example.com",
  "resource_id": -2147483648
}
```

```yaml
id: string
event: string
target: http://example.com
resource_id: -2147483648

```

<h3 id="hooks_partial_update-parameters">Parameters</h3>

|Name|In|Type|Required|Description|
|---|---|---|---|---|
|id|path|string|true|A unique value identifying this hook.|
|project_id|path|string|true|Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/.|
|body|body|[PatchedHook](#schemapatchedhook)|false|none|

> Example responses

> 200 Response

```json
{
  "id": "string",
  "created": "2019-08-24T14:15:22Z",
  "updated": "2019-08-24T14:15:22Z",
  "event": "string",
  "target": "http://example.com",
  "resource_id": -2147483648,
  "team": 0
}
```

<h3 id="hooks_partial_update-responses">Responses</h3>

|Status|Meaning|Description|Schema|
|---|---|---|---|
|200|[OK](https://tools.ietf.org/html/rfc7231#section-6.3.1)|none|[Hook](#schemahook)|

<aside class="success">
This operation does not require authentication
</aside>

## hooks_destroy

<a id="opIdhooks_destroy"></a>

> Code samples

```shell
# You can also use wget
curl -X DELETE /api/projects/{project_id}/hooks/{id}/

```

```http
DELETE /api/projects/{project_id}/hooks/{id}/ HTTP/1.1

```

```javascript

fetch('/api/projects/{project_id}/hooks/{id}/',
{
  method: 'DELETE'

})
.then(function(res) {
    return res.json();
}).then(function(body) {
    console.log(body);
});

```

```ruby
require 'rest-client'
require 'json'

result = RestClient.delete '/api/projects/{project_id}/hooks/{id}/',
  params: {
  }

p JSON.parse(result)

```

```python
import requests

r = requests.delete('/api/projects/{project_id}/hooks/{id}/')

print(r.json())

```

```php
<?php

require 'vendor/autoload.php';

$client = new \GuzzleHttp\Client();

// Define array of request body.
$request_body = array();

try {
    $response = $client->request('DELETE','/api/projects/{project_id}/hooks/{id}/', array(
        'headers' => $headers,
        'json' => $request_body,
       )
    );
    print_r($response->getBody()->getContents());
 }
 catch (\GuzzleHttp\Exception\BadResponseException $e) {
    // handle exception or api errors.
    print_r($e->getMessage());
 }

 // ...

```

```java
URL obj = new URL("/api/projects/{project_id}/hooks/{id}/");
HttpURLConnection con = (HttpURLConnection) obj.openConnection();
con.setRequestMethod("DELETE");
int responseCode = con.getResponseCode();
BufferedReader in = new BufferedReader(
    new InputStreamReader(con.getInputStream()));
String inputLine;
StringBuffer response = new StringBuffer();
while ((inputLine = in.readLine()) != null) {
    response.append(inputLine);
}
in.close();
System.out.println(response.toString());

```

```go
package main

import (
       "bytes"
       "net/http"
)

func main() {

    data := bytes.NewBuffer([]byte{jsonReq})
    req, err := http.NewRequest("DELETE", "/api/projects/{project_id}/hooks/{id}/", data)
    req.Header = headers

    client := &http.Client{}
    resp, err := client.Do(req)
    // ...
}

```

`DELETE /api/projects/{project_id}/hooks/{id}/`

Retrieve, create, update or destroy REST hooks.

<h3 id="hooks_destroy-parameters">Parameters</h3>

|Name|In|Type|Required|Description|
|---|---|---|---|---|
|id|path|string|true|A unique value identifying this hook.|
|project_id|path|string|true|Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/.|

<h3 id="hooks_destroy-responses">Responses</h3>

|Status|Meaning|Description|Schema|
|---|---|---|---|
|204|[No Content](https://tools.ietf.org/html/rfc7231#section-6.3.5)|No response body|None|

<aside class="success">
This operation does not require authentication
</aside>

<h1 id="-insights">insights</h1>

## insights_list

<a id="opIdinsights_list"></a>

> Code samples

```shell
# You can also use wget
curl -X GET /api/projects/{project_id}/insights/ \
  -H 'Accept: application/json'

```

```http
GET /api/projects/{project_id}/insights/ HTTP/1.1

Accept: application/json

```

```javascript

const headers = {
  'Accept':'application/json'
};

fetch('/api/projects/{project_id}/insights/',
{
  method: 'GET',

  headers: headers
})
.then(function(res) {
    return res.json();
}).then(function(body) {
    console.log(body);
});

```

```ruby
require 'rest-client'
require 'json'

headers = {
  'Accept' => 'application/json'
}

result = RestClient.get '/api/projects/{project_id}/insights/',
  params: {
  }, headers: headers

p JSON.parse(result)

```

```python
import requests
headers = {
  'Accept': 'application/json'
}

r = requests.get('/api/projects/{project_id}/insights/', headers = headers)

print(r.json())

```

```php
<?php

require 'vendor/autoload.php';

$headers = array(
    'Accept' => 'application/json',
);

$client = new \GuzzleHttp\Client();

// Define array of request body.
$request_body = array();

try {
    $response = $client->request('GET','/api/projects/{project_id}/insights/', array(
        'headers' => $headers,
        'json' => $request_body,
       )
    );
    print_r($response->getBody()->getContents());
 }
 catch (\GuzzleHttp\Exception\BadResponseException $e) {
    // handle exception or api errors.
    print_r($e->getMessage());
 }

 // ...

```

```java
URL obj = new URL("/api/projects/{project_id}/insights/");
HttpURLConnection con = (HttpURLConnection) obj.openConnection();
con.setRequestMethod("GET");
int responseCode = con.getResponseCode();
BufferedReader in = new BufferedReader(
    new InputStreamReader(con.getInputStream()));
String inputLine;
StringBuffer response = new StringBuffer();
while ((inputLine = in.readLine()) != null) {
    response.append(inputLine);
}
in.close();
System.out.println(response.toString());

```

```go
package main

import (
       "bytes"
       "net/http"
)

func main() {

    headers := map[string][]string{
        "Accept": []string{"application/json"},
    }

    data := bytes.NewBuffer([]byte{jsonReq})
    req, err := http.NewRequest("GET", "/api/projects/{project_id}/insights/", data)
    req.Header = headers

    client := &http.Client{}
    resp, err := client.Do(req)
    // ...
}

```

`GET /api/projects/{project_id}/insights/`

<h3 id="insights_list-parameters">Parameters</h3>

|Name|In|Type|Required|Description|
|---|---|---|---|---|
|created_by|query|integer|false|none|
|limit|query|integer|false|Number of results to return per page.|
|offset|query|integer|false|The initial index from which to return the results.|
|project_id|path|string|true|Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/.|
|short_id|query|string|false|none|

> Example responses

> 200 Response

```json
{
  "count": 123,
  "next": "http://api.example.org/accounts/?offset=400&limit=100",
  "previous": "http://api.example.org/accounts/?offset=200&limit=100",
  "results": [
    {
      "id": 0,
      "short_id": "string",
      "name": "string",
      "filters": {
        "property1": null,
        "property2": null
      },
      "filters_hash": "string",
      "order": -2147483648,
      "deleted": true,
      "dashboard": 0,
      "dive_dashboard": 0,
      "layouts": {
        "property1": null,
        "property2": null
      },
      "color": "string",
      "last_refresh": "string",
      "refreshing": true,
      "result": "string",
      "created_at": "2019-08-24T14:15:22Z",
      "description": "string",
      "updated_at": "2019-08-24T14:15:22Z",
      "tags": [
        "string"
      ],
      "favorited": true,
      "saved": true,
      "created_by": {
        "id": 0,
        "uuid": "095be615-a8ad-4c33-8e9c-c7612fbf6c9f",
        "distinct_id": "string",
        "first_name": "string",
        "email": "user@example.com"
      },
      "is_sample": true
    }
  ]
}
```

<h3 id="insights_list-responses">Responses</h3>

|Status|Meaning|Description|Schema|
|---|---|---|---|
|200|[OK](https://tools.ietf.org/html/rfc7231#section-6.3.1)|none|[PaginatedInsightList](#schemapaginatedinsightlist)|

<aside class="success">
This operation does not require authentication
</aside>

## insights_create

<a id="opIdinsights_create"></a>

> Code samples

```shell
# You can also use wget
curl -X POST /api/projects/{project_id}/insights/ \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json'

```

```http
POST /api/projects/{project_id}/insights/ HTTP/1.1

Content-Type: application/json
Accept: application/json

```

```javascript
const inputBody = '{
  "name": "string",
  "filters": {
    "property1": null,
    "property2": null
  },
  "filters_hash": "string",
  "order": -2147483648,
  "deleted": true,
  "dashboard": 0,
  "dive_dashboard": 0,
  "layouts": {
    "property1": null,
    "property2": null
  },
  "color": "string",
  "refreshing": true,
  "description": "string",
  "tags": [
    "string"
  ],
  "favorited": true,
  "saved": true
}';
const headers = {
  'Content-Type':'application/json',
  'Accept':'application/json'
};

fetch('/api/projects/{project_id}/insights/',
{
  method: 'POST',
  body: inputBody,
  headers: headers
})
.then(function(res) {
    return res.json();
}).then(function(body) {
    console.log(body);
});

```

```ruby
require 'rest-client'
require 'json'

headers = {
  'Content-Type' => 'application/json',
  'Accept' => 'application/json'
}

result = RestClient.post '/api/projects/{project_id}/insights/',
  params: {
  }, headers: headers

p JSON.parse(result)

```

```python
import requests
headers = {
  'Content-Type': 'application/json',
  'Accept': 'application/json'
}

r = requests.post('/api/projects/{project_id}/insights/', headers = headers)

print(r.json())

```

```php
<?php

require 'vendor/autoload.php';

$headers = array(
    'Content-Type' => 'application/json',
    'Accept' => 'application/json',
);

$client = new \GuzzleHttp\Client();

// Define array of request body.
$request_body = array();

try {
    $response = $client->request('POST','/api/projects/{project_id}/insights/', array(
        'headers' => $headers,
        'json' => $request_body,
       )
    );
    print_r($response->getBody()->getContents());
 }
 catch (\GuzzleHttp\Exception\BadResponseException $e) {
    // handle exception or api errors.
    print_r($e->getMessage());
 }

 // ...

```

```java
URL obj = new URL("/api/projects/{project_id}/insights/");
HttpURLConnection con = (HttpURLConnection) obj.openConnection();
con.setRequestMethod("POST");
int responseCode = con.getResponseCode();
BufferedReader in = new BufferedReader(
    new InputStreamReader(con.getInputStream()));
String inputLine;
StringBuffer response = new StringBuffer();
while ((inputLine = in.readLine()) != null) {
    response.append(inputLine);
}
in.close();
System.out.println(response.toString());

```

```go
package main

import (
       "bytes"
       "net/http"
)

func main() {

    headers := map[string][]string{
        "Content-Type": []string{"application/json"},
        "Accept": []string{"application/json"},
    }

    data := bytes.NewBuffer([]byte{jsonReq})
    req, err := http.NewRequest("POST", "/api/projects/{project_id}/insights/", data)
    req.Header = headers

    client := &http.Client{}
    resp, err := client.Do(req)
    // ...
}

```

`POST /api/projects/{project_id}/insights/`

> Body parameter

```json
{
  "name": "string",
  "filters": {
    "property1": null,
    "property2": null
  },
  "filters_hash": "string",
  "order": -2147483648,
  "deleted": true,
  "dashboard": 0,
  "dive_dashboard": 0,
  "layouts": {
    "property1": null,
    "property2": null
  },
  "color": "string",
  "refreshing": true,
  "description": "string",
  "tags": [
    "string"
  ],
  "favorited": true,
  "saved": true
}
```

```yaml
name: string
filters:
  ? property1
  ? property2
filters_hash: string
order: -2147483648
deleted: true
dashboard: 0
dive_dashboard: 0
layouts:
  ? property1
  ? property2
color: string
refreshing: true
description: string
tags:
  - string
favorited: true
saved: true

```

<h3 id="insights_create-parameters">Parameters</h3>

|Name|In|Type|Required|Description|
|---|---|---|---|---|
|project_id|path|string|true|Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/.|
|body|body|[Insight](#schemainsight)|false|none|

> Example responses

> 201 Response

```json
{
  "id": 0,
  "short_id": "string",
  "name": "string",
  "filters": {
    "property1": null,
    "property2": null
  },
  "filters_hash": "string",
  "order": -2147483648,
  "deleted": true,
  "dashboard": 0,
  "dive_dashboard": 0,
  "layouts": {
    "property1": null,
    "property2": null
  },
  "color": "string",
  "last_refresh": "string",
  "refreshing": true,
  "result": "string",
  "created_at": "2019-08-24T14:15:22Z",
  "description": "string",
  "updated_at": "2019-08-24T14:15:22Z",
  "tags": [
    "string"
  ],
  "favorited": true,
  "saved": true,
  "created_by": {
    "id": 0,
    "uuid": "095be615-a8ad-4c33-8e9c-c7612fbf6c9f",
    "distinct_id": "string",
    "first_name": "string",
    "email": "user@example.com"
  },
  "is_sample": true
}
```

<h3 id="insights_create-responses">Responses</h3>

|Status|Meaning|Description|Schema|
|---|---|---|---|
|201|[Created](https://tools.ietf.org/html/rfc7231#section-6.3.2)|none|[Insight](#schemainsight)|

<aside class="success">
This operation does not require authentication
</aside>

## insights_retrieve

<a id="opIdinsights_retrieve"></a>

> Code samples

```shell
# You can also use wget
curl -X GET /api/projects/{project_id}/insights/{id}/ \
  -H 'Accept: application/json'

```

```http
GET /api/projects/{project_id}/insights/{id}/ HTTP/1.1

Accept: application/json

```

```javascript

const headers = {
  'Accept':'application/json'
};

fetch('/api/projects/{project_id}/insights/{id}/',
{
  method: 'GET',

  headers: headers
})
.then(function(res) {
    return res.json();
}).then(function(body) {
    console.log(body);
});

```

```ruby
require 'rest-client'
require 'json'

headers = {
  'Accept' => 'application/json'
}

result = RestClient.get '/api/projects/{project_id}/insights/{id}/',
  params: {
  }, headers: headers

p JSON.parse(result)

```

```python
import requests
headers = {
  'Accept': 'application/json'
}

r = requests.get('/api/projects/{project_id}/insights/{id}/', headers = headers)

print(r.json())

```

```php
<?php

require 'vendor/autoload.php';

$headers = array(
    'Accept' => 'application/json',
);

$client = new \GuzzleHttp\Client();

// Define array of request body.
$request_body = array();

try {
    $response = $client->request('GET','/api/projects/{project_id}/insights/{id}/', array(
        'headers' => $headers,
        'json' => $request_body,
       )
    );
    print_r($response->getBody()->getContents());
 }
 catch (\GuzzleHttp\Exception\BadResponseException $e) {
    // handle exception or api errors.
    print_r($e->getMessage());
 }

 // ...

```

```java
URL obj = new URL("/api/projects/{project_id}/insights/{id}/");
HttpURLConnection con = (HttpURLConnection) obj.openConnection();
con.setRequestMethod("GET");
int responseCode = con.getResponseCode();
BufferedReader in = new BufferedReader(
    new InputStreamReader(con.getInputStream()));
String inputLine;
StringBuffer response = new StringBuffer();
while ((inputLine = in.readLine()) != null) {
    response.append(inputLine);
}
in.close();
System.out.println(response.toString());

```

```go
package main

import (
       "bytes"
       "net/http"
)

func main() {

    headers := map[string][]string{
        "Accept": []string{"application/json"},
    }

    data := bytes.NewBuffer([]byte{jsonReq})
    req, err := http.NewRequest("GET", "/api/projects/{project_id}/insights/{id}/", data)
    req.Header = headers

    client := &http.Client{}
    resp, err := client.Do(req)
    // ...
}

```

`GET /api/projects/{project_id}/insights/{id}/`

<h3 id="insights_retrieve-parameters">Parameters</h3>

|Name|In|Type|Required|Description|
|---|---|---|---|---|
|id|path|integer|true|A unique integer value identifying this insight.|
|project_id|path|string|true|Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/.|

> Example responses

> 200 Response

```json
{
  "id": 0,
  "short_id": "string",
  "name": "string",
  "filters": {
    "property1": null,
    "property2": null
  },
  "filters_hash": "string",
  "order": -2147483648,
  "deleted": true,
  "dashboard": 0,
  "dive_dashboard": 0,
  "layouts": {
    "property1": null,
    "property2": null
  },
  "color": "string",
  "last_refresh": "string",
  "refreshing": true,
  "result": "string",
  "created_at": "2019-08-24T14:15:22Z",
  "description": "string",
  "updated_at": "2019-08-24T14:15:22Z",
  "tags": [
    "string"
  ],
  "favorited": true,
  "saved": true,
  "created_by": {
    "id": 0,
    "uuid": "095be615-a8ad-4c33-8e9c-c7612fbf6c9f",
    "distinct_id": "string",
    "first_name": "string",
    "email": "user@example.com"
  },
  "is_sample": true
}
```

<h3 id="insights_retrieve-responses">Responses</h3>

|Status|Meaning|Description|Schema|
|---|---|---|---|
|200|[OK](https://tools.ietf.org/html/rfc7231#section-6.3.1)|none|[Insight](#schemainsight)|

<aside class="success">
This operation does not require authentication
</aside>

## insights_update

<a id="opIdinsights_update"></a>

> Code samples

```shell
# You can also use wget
curl -X PUT /api/projects/{project_id}/insights/{id}/ \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json'

```

```http
PUT /api/projects/{project_id}/insights/{id}/ HTTP/1.1

Content-Type: application/json
Accept: application/json

```

```javascript
const inputBody = '{
  "name": "string",
  "filters": {
    "property1": null,
    "property2": null
  },
  "filters_hash": "string",
  "order": -2147483648,
  "deleted": true,
  "dashboard": 0,
  "dive_dashboard": 0,
  "layouts": {
    "property1": null,
    "property2": null
  },
  "color": "string",
  "refreshing": true,
  "description": "string",
  "tags": [
    "string"
  ],
  "favorited": true,
  "saved": true
}';
const headers = {
  'Content-Type':'application/json',
  'Accept':'application/json'
};

fetch('/api/projects/{project_id}/insights/{id}/',
{
  method: 'PUT',
  body: inputBody,
  headers: headers
})
.then(function(res) {
    return res.json();
}).then(function(body) {
    console.log(body);
});

```

```ruby
require 'rest-client'
require 'json'

headers = {
  'Content-Type' => 'application/json',
  'Accept' => 'application/json'
}

result = RestClient.put '/api/projects/{project_id}/insights/{id}/',
  params: {
  }, headers: headers

p JSON.parse(result)

```

```python
import requests
headers = {
  'Content-Type': 'application/json',
  'Accept': 'application/json'
}

r = requests.put('/api/projects/{project_id}/insights/{id}/', headers = headers)

print(r.json())

```

```php
<?php

require 'vendor/autoload.php';

$headers = array(
    'Content-Type' => 'application/json',
    'Accept' => 'application/json',
);

$client = new \GuzzleHttp\Client();

// Define array of request body.
$request_body = array();

try {
    $response = $client->request('PUT','/api/projects/{project_id}/insights/{id}/', array(
        'headers' => $headers,
        'json' => $request_body,
       )
    );
    print_r($response->getBody()->getContents());
 }
 catch (\GuzzleHttp\Exception\BadResponseException $e) {
    // handle exception or api errors.
    print_r($e->getMessage());
 }

 // ...

```

```java
URL obj = new URL("/api/projects/{project_id}/insights/{id}/");
HttpURLConnection con = (HttpURLConnection) obj.openConnection();
con.setRequestMethod("PUT");
int responseCode = con.getResponseCode();
BufferedReader in = new BufferedReader(
    new InputStreamReader(con.getInputStream()));
String inputLine;
StringBuffer response = new StringBuffer();
while ((inputLine = in.readLine()) != null) {
    response.append(inputLine);
}
in.close();
System.out.println(response.toString());

```

```go
package main

import (
       "bytes"
       "net/http"
)

func main() {

    headers := map[string][]string{
        "Content-Type": []string{"application/json"},
        "Accept": []string{"application/json"},
    }

    data := bytes.NewBuffer([]byte{jsonReq})
    req, err := http.NewRequest("PUT", "/api/projects/{project_id}/insights/{id}/", data)
    req.Header = headers

    client := &http.Client{}
    resp, err := client.Do(req)
    // ...
}

```

`PUT /api/projects/{project_id}/insights/{id}/`

> Body parameter

```json
{
  "name": "string",
  "filters": {
    "property1": null,
    "property2": null
  },
  "filters_hash": "string",
  "order": -2147483648,
  "deleted": true,
  "dashboard": 0,
  "dive_dashboard": 0,
  "layouts": {
    "property1": null,
    "property2": null
  },
  "color": "string",
  "refreshing": true,
  "description": "string",
  "tags": [
    "string"
  ],
  "favorited": true,
  "saved": true
}
```

```yaml
name: string
filters:
  ? property1
  ? property2
filters_hash: string
order: -2147483648
deleted: true
dashboard: 0
dive_dashboard: 0
layouts:
  ? property1
  ? property2
color: string
refreshing: true
description: string
tags:
  - string
favorited: true
saved: true

```

<h3 id="insights_update-parameters">Parameters</h3>

|Name|In|Type|Required|Description|
|---|---|---|---|---|
|id|path|integer|true|A unique integer value identifying this insight.|
|project_id|path|string|true|Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/.|
|body|body|[Insight](#schemainsight)|false|none|

> Example responses

> 200 Response

```json
{
  "id": 0,
  "short_id": "string",
  "name": "string",
  "filters": {
    "property1": null,
    "property2": null
  },
  "filters_hash": "string",
  "order": -2147483648,
  "deleted": true,
  "dashboard": 0,
  "dive_dashboard": 0,
  "layouts": {
    "property1": null,
    "property2": null
  },
  "color": "string",
  "last_refresh": "string",
  "refreshing": true,
  "result": "string",
  "created_at": "2019-08-24T14:15:22Z",
  "description": "string",
  "updated_at": "2019-08-24T14:15:22Z",
  "tags": [
    "string"
  ],
  "favorited": true,
  "saved": true,
  "created_by": {
    "id": 0,
    "uuid": "095be615-a8ad-4c33-8e9c-c7612fbf6c9f",
    "distinct_id": "string",
    "first_name": "string",
    "email": "user@example.com"
  },
  "is_sample": true
}
```

<h3 id="insights_update-responses">Responses</h3>

|Status|Meaning|Description|Schema|
|---|---|---|---|
|200|[OK](https://tools.ietf.org/html/rfc7231#section-6.3.1)|none|[Insight](#schemainsight)|

<aside class="success">
This operation does not require authentication
</aside>

## insights_partial_update

<a id="opIdinsights_partial_update"></a>

> Code samples

```shell
# You can also use wget
curl -X PATCH /api/projects/{project_id}/insights/{id}/ \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json'

```

```http
PATCH /api/projects/{project_id}/insights/{id}/ HTTP/1.1

Content-Type: application/json
Accept: application/json

```

```javascript
const inputBody = '{
  "name": "string",
  "filters": {
    "property1": null,
    "property2": null
  },
  "filters_hash": "string",
  "order": -2147483648,
  "deleted": true,
  "dashboard": 0,
  "dive_dashboard": 0,
  "layouts": {
    "property1": null,
    "property2": null
  },
  "color": "string",
  "refreshing": true,
  "description": "string",
  "tags": [
    "string"
  ],
  "favorited": true,
  "saved": true
}';
const headers = {
  'Content-Type':'application/json',
  'Accept':'application/json'
};

fetch('/api/projects/{project_id}/insights/{id}/',
{
  method: 'PATCH',
  body: inputBody,
  headers: headers
})
.then(function(res) {
    return res.json();
}).then(function(body) {
    console.log(body);
});

```

```ruby
require 'rest-client'
require 'json'

headers = {
  'Content-Type' => 'application/json',
  'Accept' => 'application/json'
}

result = RestClient.patch '/api/projects/{project_id}/insights/{id}/',
  params: {
  }, headers: headers

p JSON.parse(result)

```

```python
import requests
headers = {
  'Content-Type': 'application/json',
  'Accept': 'application/json'
}

r = requests.patch('/api/projects/{project_id}/insights/{id}/', headers = headers)

print(r.json())

```

```php
<?php

require 'vendor/autoload.php';

$headers = array(
    'Content-Type' => 'application/json',
    'Accept' => 'application/json',
);

$client = new \GuzzleHttp\Client();

// Define array of request body.
$request_body = array();

try {
    $response = $client->request('PATCH','/api/projects/{project_id}/insights/{id}/', array(
        'headers' => $headers,
        'json' => $request_body,
       )
    );
    print_r($response->getBody()->getContents());
 }
 catch (\GuzzleHttp\Exception\BadResponseException $e) {
    // handle exception or api errors.
    print_r($e->getMessage());
 }

 // ...

```

```java
URL obj = new URL("/api/projects/{project_id}/insights/{id}/");
HttpURLConnection con = (HttpURLConnection) obj.openConnection();
con.setRequestMethod("PATCH");
int responseCode = con.getResponseCode();
BufferedReader in = new BufferedReader(
    new InputStreamReader(con.getInputStream()));
String inputLine;
StringBuffer response = new StringBuffer();
while ((inputLine = in.readLine()) != null) {
    response.append(inputLine);
}
in.close();
System.out.println(response.toString());

```

```go
package main

import (
       "bytes"
       "net/http"
)

func main() {

    headers := map[string][]string{
        "Content-Type": []string{"application/json"},
        "Accept": []string{"application/json"},
    }

    data := bytes.NewBuffer([]byte{jsonReq})
    req, err := http.NewRequest("PATCH", "/api/projects/{project_id}/insights/{id}/", data)
    req.Header = headers

    client := &http.Client{}
    resp, err := client.Do(req)
    // ...
}

```

`PATCH /api/projects/{project_id}/insights/{id}/`

> Body parameter

```json
{
  "name": "string",
  "filters": {
    "property1": null,
    "property2": null
  },
  "filters_hash": "string",
  "order": -2147483648,
  "deleted": true,
  "dashboard": 0,
  "dive_dashboard": 0,
  "layouts": {
    "property1": null,
    "property2": null
  },
  "color": "string",
  "refreshing": true,
  "description": "string",
  "tags": [
    "string"
  ],
  "favorited": true,
  "saved": true
}
```

```yaml
name: string
filters:
  ? property1
  ? property2
filters_hash: string
order: -2147483648
deleted: true
dashboard: 0
dive_dashboard: 0
layouts:
  ? property1
  ? property2
color: string
refreshing: true
description: string
tags:
  - string
favorited: true
saved: true

```

<h3 id="insights_partial_update-parameters">Parameters</h3>

|Name|In|Type|Required|Description|
|---|---|---|---|---|
|id|path|integer|true|A unique integer value identifying this insight.|
|project_id|path|string|true|Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/.|
|body|body|[PatchedInsight](#schemapatchedinsight)|false|none|

> Example responses

> 200 Response

```json
{
  "id": 0,
  "short_id": "string",
  "name": "string",
  "filters": {
    "property1": null,
    "property2": null
  },
  "filters_hash": "string",
  "order": -2147483648,
  "deleted": true,
  "dashboard": 0,
  "dive_dashboard": 0,
  "layouts": {
    "property1": null,
    "property2": null
  },
  "color": "string",
  "last_refresh": "string",
  "refreshing": true,
  "result": "string",
  "created_at": "2019-08-24T14:15:22Z",
  "description": "string",
  "updated_at": "2019-08-24T14:15:22Z",
  "tags": [
    "string"
  ],
  "favorited": true,
  "saved": true,
  "created_by": {
    "id": 0,
    "uuid": "095be615-a8ad-4c33-8e9c-c7612fbf6c9f",
    "distinct_id": "string",
    "first_name": "string",
    "email": "user@example.com"
  },
  "is_sample": true
}
```

<h3 id="insights_partial_update-responses">Responses</h3>

|Status|Meaning|Description|Schema|
|---|---|---|---|
|200|[OK](https://tools.ietf.org/html/rfc7231#section-6.3.1)|none|[Insight](#schemainsight)|

<aside class="success">
This operation does not require authentication
</aside>

## insights_destroy

<a id="opIdinsights_destroy"></a>

> Code samples

```shell
# You can also use wget
curl -X DELETE /api/projects/{project_id}/insights/{id}/

```

```http
DELETE /api/projects/{project_id}/insights/{id}/ HTTP/1.1

```

```javascript

fetch('/api/projects/{project_id}/insights/{id}/',
{
  method: 'DELETE'

})
.then(function(res) {
    return res.json();
}).then(function(body) {
    console.log(body);
});

```

```ruby
require 'rest-client'
require 'json'

result = RestClient.delete '/api/projects/{project_id}/insights/{id}/',
  params: {
  }

p JSON.parse(result)

```

```python
import requests

r = requests.delete('/api/projects/{project_id}/insights/{id}/')

print(r.json())

```

```php
<?php

require 'vendor/autoload.php';

$client = new \GuzzleHttp\Client();

// Define array of request body.
$request_body = array();

try {
    $response = $client->request('DELETE','/api/projects/{project_id}/insights/{id}/', array(
        'headers' => $headers,
        'json' => $request_body,
       )
    );
    print_r($response->getBody()->getContents());
 }
 catch (\GuzzleHttp\Exception\BadResponseException $e) {
    // handle exception or api errors.
    print_r($e->getMessage());
 }

 // ...

```

```java
URL obj = new URL("/api/projects/{project_id}/insights/{id}/");
HttpURLConnection con = (HttpURLConnection) obj.openConnection();
con.setRequestMethod("DELETE");
int responseCode = con.getResponseCode();
BufferedReader in = new BufferedReader(
    new InputStreamReader(con.getInputStream()));
String inputLine;
StringBuffer response = new StringBuffer();
while ((inputLine = in.readLine()) != null) {
    response.append(inputLine);
}
in.close();
System.out.println(response.toString());

```

```go
package main

import (
       "bytes"
       "net/http"
)

func main() {

    data := bytes.NewBuffer([]byte{jsonReq})
    req, err := http.NewRequest("DELETE", "/api/projects/{project_id}/insights/{id}/", data)
    req.Header = headers

    client := &http.Client{}
    resp, err := client.Do(req)
    // ...
}

```

`DELETE /api/projects/{project_id}/insights/{id}/`

<h3 id="insights_destroy-parameters">Parameters</h3>

|Name|In|Type|Required|Description|
|---|---|---|---|---|
|id|path|integer|true|A unique integer value identifying this insight.|
|project_id|path|string|true|Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/.|

<h3 id="insights_destroy-responses">Responses</h3>

|Status|Meaning|Description|Schema|
|---|---|---|---|
|204|[No Content](https://tools.ietf.org/html/rfc7231#section-6.3.5)|No response body|None|

<aside class="success">
This operation does not require authentication
</aside>

## insights_funnel_retrieve

<a id="opIdinsights_funnel_retrieve"></a>

> Code samples

```shell
# You can also use wget
curl -X GET /api/projects/{project_id}/insights/funnel/ \
  -H 'Accept: application/json'

```

```http
GET /api/projects/{project_id}/insights/funnel/ HTTP/1.1

Accept: application/json

```

```javascript

const headers = {
  'Accept':'application/json'
};

fetch('/api/projects/{project_id}/insights/funnel/',
{
  method: 'GET',

  headers: headers
})
.then(function(res) {
    return res.json();
}).then(function(body) {
    console.log(body);
});

```

```ruby
require 'rest-client'
require 'json'

headers = {
  'Accept' => 'application/json'
}

result = RestClient.get '/api/projects/{project_id}/insights/funnel/',
  params: {
  }, headers: headers

p JSON.parse(result)

```

```python
import requests
headers = {
  'Accept': 'application/json'
}

r = requests.get('/api/projects/{project_id}/insights/funnel/', headers = headers)

print(r.json())

```

```php
<?php

require 'vendor/autoload.php';

$headers = array(
    'Accept' => 'application/json',
);

$client = new \GuzzleHttp\Client();

// Define array of request body.
$request_body = array();

try {
    $response = $client->request('GET','/api/projects/{project_id}/insights/funnel/', array(
        'headers' => $headers,
        'json' => $request_body,
       )
    );
    print_r($response->getBody()->getContents());
 }
 catch (\GuzzleHttp\Exception\BadResponseException $e) {
    // handle exception or api errors.
    print_r($e->getMessage());
 }

 // ...

```

```java
URL obj = new URL("/api/projects/{project_id}/insights/funnel/");
HttpURLConnection con = (HttpURLConnection) obj.openConnection();
con.setRequestMethod("GET");
int responseCode = con.getResponseCode();
BufferedReader in = new BufferedReader(
    new InputStreamReader(con.getInputStream()));
String inputLine;
StringBuffer response = new StringBuffer();
while ((inputLine = in.readLine()) != null) {
    response.append(inputLine);
}
in.close();
System.out.println(response.toString());

```

```go
package main

import (
       "bytes"
       "net/http"
)

func main() {

    headers := map[string][]string{
        "Accept": []string{"application/json"},
    }

    data := bytes.NewBuffer([]byte{jsonReq})
    req, err := http.NewRequest("GET", "/api/projects/{project_id}/insights/funnel/", data)
    req.Header = headers

    client := &http.Client{}
    resp, err := client.Do(req)
    // ...
}

```

`GET /api/projects/{project_id}/insights/funnel/`

<h3 id="insights_funnel_retrieve-parameters">Parameters</h3>

|Name|In|Type|Required|Description|
|---|---|---|---|---|
|project_id|path|string|true|Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/.|

> Example responses

> 200 Response

```json
{
  "id": 0,
  "short_id": "string",
  "name": "string",
  "filters": {
    "property1": null,
    "property2": null
  },
  "filters_hash": "string",
  "order": -2147483648,
  "deleted": true,
  "dashboard": 0,
  "dive_dashboard": 0,
  "layouts": {
    "property1": null,
    "property2": null
  },
  "color": "string",
  "last_refresh": "string",
  "refreshing": true,
  "result": "string",
  "created_at": "2019-08-24T14:15:22Z",
  "description": "string",
  "updated_at": "2019-08-24T14:15:22Z",
  "tags": [
    "string"
  ],
  "favorited": true,
  "saved": true,
  "created_by": {
    "id": 0,
    "uuid": "095be615-a8ad-4c33-8e9c-c7612fbf6c9f",
    "distinct_id": "string",
    "first_name": "string",
    "email": "user@example.com"
  },
  "is_sample": true
}
```

<h3 id="insights_funnel_retrieve-responses">Responses</h3>

|Status|Meaning|Description|Schema|
|---|---|---|---|
|200|[OK](https://tools.ietf.org/html/rfc7231#section-6.3.1)|none|[Insight](#schemainsight)|

<aside class="success">
This operation does not require authentication
</aside>

## insights_funnel_correlation_retrieve

<a id="opIdinsights_funnel_correlation_retrieve"></a>

> Code samples

```shell
# You can also use wget
curl -X GET /api/projects/{project_id}/insights/funnel/correlation/ \
  -H 'Accept: application/json'

```

```http
GET /api/projects/{project_id}/insights/funnel/correlation/ HTTP/1.1

Accept: application/json

```

```javascript

const headers = {
  'Accept':'application/json'
};

fetch('/api/projects/{project_id}/insights/funnel/correlation/',
{
  method: 'GET',

  headers: headers
})
.then(function(res) {
    return res.json();
}).then(function(body) {
    console.log(body);
});

```

```ruby
require 'rest-client'
require 'json'

headers = {
  'Accept' => 'application/json'
}

result = RestClient.get '/api/projects/{project_id}/insights/funnel/correlation/',
  params: {
  }, headers: headers

p JSON.parse(result)

```

```python
import requests
headers = {
  'Accept': 'application/json'
}

r = requests.get('/api/projects/{project_id}/insights/funnel/correlation/', headers = headers)

print(r.json())

```

```php
<?php

require 'vendor/autoload.php';

$headers = array(
    'Accept' => 'application/json',
);

$client = new \GuzzleHttp\Client();

// Define array of request body.
$request_body = array();

try {
    $response = $client->request('GET','/api/projects/{project_id}/insights/funnel/correlation/', array(
        'headers' => $headers,
        'json' => $request_body,
       )
    );
    print_r($response->getBody()->getContents());
 }
 catch (\GuzzleHttp\Exception\BadResponseException $e) {
    // handle exception or api errors.
    print_r($e->getMessage());
 }

 // ...

```

```java
URL obj = new URL("/api/projects/{project_id}/insights/funnel/correlation/");
HttpURLConnection con = (HttpURLConnection) obj.openConnection();
con.setRequestMethod("GET");
int responseCode = con.getResponseCode();
BufferedReader in = new BufferedReader(
    new InputStreamReader(con.getInputStream()));
String inputLine;
StringBuffer response = new StringBuffer();
while ((inputLine = in.readLine()) != null) {
    response.append(inputLine);
}
in.close();
System.out.println(response.toString());

```

```go
package main

import (
       "bytes"
       "net/http"
)

func main() {

    headers := map[string][]string{
        "Accept": []string{"application/json"},
    }

    data := bytes.NewBuffer([]byte{jsonReq})
    req, err := http.NewRequest("GET", "/api/projects/{project_id}/insights/funnel/correlation/", data)
    req.Header = headers

    client := &http.Client{}
    resp, err := client.Do(req)
    // ...
}

```

`GET /api/projects/{project_id}/insights/funnel/correlation/`

<h3 id="insights_funnel_correlation_retrieve-parameters">Parameters</h3>

|Name|In|Type|Required|Description|
|---|---|---|---|---|
|project_id|path|string|true|Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/.|

> Example responses

> 200 Response

```json
{
  "id": 0,
  "short_id": "string",
  "name": "string",
  "filters": {
    "property1": null,
    "property2": null
  },
  "filters_hash": "string",
  "order": -2147483648,
  "deleted": true,
  "dashboard": 0,
  "dive_dashboard": 0,
  "layouts": {
    "property1": null,
    "property2": null
  },
  "color": "string",
  "last_refresh": "string",
  "refreshing": true,
  "result": "string",
  "created_at": "2019-08-24T14:15:22Z",
  "description": "string",
  "updated_at": "2019-08-24T14:15:22Z",
  "tags": [
    "string"
  ],
  "favorited": true,
  "saved": true,
  "created_by": {
    "id": 0,
    "uuid": "095be615-a8ad-4c33-8e9c-c7612fbf6c9f",
    "distinct_id": "string",
    "first_name": "string",
    "email": "user@example.com"
  },
  "is_sample": true
}
```

<h3 id="insights_funnel_correlation_retrieve-responses">Responses</h3>

|Status|Meaning|Description|Schema|
|---|---|---|---|
|200|[OK](https://tools.ietf.org/html/rfc7231#section-6.3.1)|none|[Insight](#schemainsight)|

<aside class="success">
This operation does not require authentication
</aside>

## insights_funnel_correlation_create

<a id="opIdinsights_funnel_correlation_create"></a>

> Code samples

```shell
# You can also use wget
curl -X POST /api/projects/{project_id}/insights/funnel/correlation/ \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json'

```

```http
POST /api/projects/{project_id}/insights/funnel/correlation/ HTTP/1.1

Content-Type: application/json
Accept: application/json

```

```javascript
const inputBody = '{
  "name": "string",
  "filters": {
    "property1": null,
    "property2": null
  },
  "filters_hash": "string",
  "order": -2147483648,
  "deleted": true,
  "dashboard": 0,
  "dive_dashboard": 0,
  "layouts": {
    "property1": null,
    "property2": null
  },
  "color": "string",
  "refreshing": true,
  "description": "string",
  "tags": [
    "string"
  ],
  "favorited": true,
  "saved": true
}';
const headers = {
  'Content-Type':'application/json',
  'Accept':'application/json'
};

fetch('/api/projects/{project_id}/insights/funnel/correlation/',
{
  method: 'POST',
  body: inputBody,
  headers: headers
})
.then(function(res) {
    return res.json();
}).then(function(body) {
    console.log(body);
});

```

```ruby
require 'rest-client'
require 'json'

headers = {
  'Content-Type' => 'application/json',
  'Accept' => 'application/json'
}

result = RestClient.post '/api/projects/{project_id}/insights/funnel/correlation/',
  params: {
  }, headers: headers

p JSON.parse(result)

```

```python
import requests
headers = {
  'Content-Type': 'application/json',
  'Accept': 'application/json'
}

r = requests.post('/api/projects/{project_id}/insights/funnel/correlation/', headers = headers)

print(r.json())

```

```php
<?php

require 'vendor/autoload.php';

$headers = array(
    'Content-Type' => 'application/json',
    'Accept' => 'application/json',
);

$client = new \GuzzleHttp\Client();

// Define array of request body.
$request_body = array();

try {
    $response = $client->request('POST','/api/projects/{project_id}/insights/funnel/correlation/', array(
        'headers' => $headers,
        'json' => $request_body,
       )
    );
    print_r($response->getBody()->getContents());
 }
 catch (\GuzzleHttp\Exception\BadResponseException $e) {
    // handle exception or api errors.
    print_r($e->getMessage());
 }

 // ...

```

```java
URL obj = new URL("/api/projects/{project_id}/insights/funnel/correlation/");
HttpURLConnection con = (HttpURLConnection) obj.openConnection();
con.setRequestMethod("POST");
int responseCode = con.getResponseCode();
BufferedReader in = new BufferedReader(
    new InputStreamReader(con.getInputStream()));
String inputLine;
StringBuffer response = new StringBuffer();
while ((inputLine = in.readLine()) != null) {
    response.append(inputLine);
}
in.close();
System.out.println(response.toString());

```

```go
package main

import (
       "bytes"
       "net/http"
)

func main() {

    headers := map[string][]string{
        "Content-Type": []string{"application/json"},
        "Accept": []string{"application/json"},
    }

    data := bytes.NewBuffer([]byte{jsonReq})
    req, err := http.NewRequest("POST", "/api/projects/{project_id}/insights/funnel/correlation/", data)
    req.Header = headers

    client := &http.Client{}
    resp, err := client.Do(req)
    // ...
}

```

`POST /api/projects/{project_id}/insights/funnel/correlation/`

> Body parameter

```json
{
  "name": "string",
  "filters": {
    "property1": null,
    "property2": null
  },
  "filters_hash": "string",
  "order": -2147483648,
  "deleted": true,
  "dashboard": 0,
  "dive_dashboard": 0,
  "layouts": {
    "property1": null,
    "property2": null
  },
  "color": "string",
  "refreshing": true,
  "description": "string",
  "tags": [
    "string"
  ],
  "favorited": true,
  "saved": true
}
```

```yaml
name: string
filters:
  ? property1
  ? property2
filters_hash: string
order: -2147483648
deleted: true
dashboard: 0
dive_dashboard: 0
layouts:
  ? property1
  ? property2
color: string
refreshing: true
description: string
tags:
  - string
favorited: true
saved: true

```

<h3 id="insights_funnel_correlation_create-parameters">Parameters</h3>

|Name|In|Type|Required|Description|
|---|---|---|---|---|
|project_id|path|string|true|Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/.|
|body|body|[Insight](#schemainsight)|false|none|

> Example responses

> 200 Response

```json
{
  "id": 0,
  "short_id": "string",
  "name": "string",
  "filters": {
    "property1": null,
    "property2": null
  },
  "filters_hash": "string",
  "order": -2147483648,
  "deleted": true,
  "dashboard": 0,
  "dive_dashboard": 0,
  "layouts": {
    "property1": null,
    "property2": null
  },
  "color": "string",
  "last_refresh": "string",
  "refreshing": true,
  "result": "string",
  "created_at": "2019-08-24T14:15:22Z",
  "description": "string",
  "updated_at": "2019-08-24T14:15:22Z",
  "tags": [
    "string"
  ],
  "favorited": true,
  "saved": true,
  "created_by": {
    "id": 0,
    "uuid": "095be615-a8ad-4c33-8e9c-c7612fbf6c9f",
    "distinct_id": "string",
    "first_name": "string",
    "email": "user@example.com"
  },
  "is_sample": true
}
```

<h3 id="insights_funnel_correlation_create-responses">Responses</h3>

|Status|Meaning|Description|Schema|
|---|---|---|---|
|200|[OK](https://tools.ietf.org/html/rfc7231#section-6.3.1)|none|[Insight](#schemainsight)|

<aside class="success">
This operation does not require authentication
</aside>

## insights_layouts_partial_update

<a id="opIdinsights_layouts_partial_update"></a>

> Code samples

```shell
# You can also use wget
curl -X PATCH /api/projects/{project_id}/insights/layouts/ \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json'

```

```http
PATCH /api/projects/{project_id}/insights/layouts/ HTTP/1.1

Content-Type: application/json
Accept: application/json

```

```javascript
const inputBody = '{
  "name": "string",
  "filters": {
    "property1": null,
    "property2": null
  },
  "filters_hash": "string",
  "order": -2147483648,
  "deleted": true,
  "dashboard": 0,
  "dive_dashboard": 0,
  "layouts": {
    "property1": null,
    "property2": null
  },
  "color": "string",
  "refreshing": true,
  "description": "string",
  "tags": [
    "string"
  ],
  "favorited": true,
  "saved": true
}';
const headers = {
  'Content-Type':'application/json',
  'Accept':'application/json'
};

fetch('/api/projects/{project_id}/insights/layouts/',
{
  method: 'PATCH',
  body: inputBody,
  headers: headers
})
.then(function(res) {
    return res.json();
}).then(function(body) {
    console.log(body);
});

```

```ruby
require 'rest-client'
require 'json'

headers = {
  'Content-Type' => 'application/json',
  'Accept' => 'application/json'
}

result = RestClient.patch '/api/projects/{project_id}/insights/layouts/',
  params: {
  }, headers: headers

p JSON.parse(result)

```

```python
import requests
headers = {
  'Content-Type': 'application/json',
  'Accept': 'application/json'
}

r = requests.patch('/api/projects/{project_id}/insights/layouts/', headers = headers)

print(r.json())

```

```php
<?php

require 'vendor/autoload.php';

$headers = array(
    'Content-Type' => 'application/json',
    'Accept' => 'application/json',
);

$client = new \GuzzleHttp\Client();

// Define array of request body.
$request_body = array();

try {
    $response = $client->request('PATCH','/api/projects/{project_id}/insights/layouts/', array(
        'headers' => $headers,
        'json' => $request_body,
       )
    );
    print_r($response->getBody()->getContents());
 }
 catch (\GuzzleHttp\Exception\BadResponseException $e) {
    // handle exception or api errors.
    print_r($e->getMessage());
 }

 // ...

```

```java
URL obj = new URL("/api/projects/{project_id}/insights/layouts/");
HttpURLConnection con = (HttpURLConnection) obj.openConnection();
con.setRequestMethod("PATCH");
int responseCode = con.getResponseCode();
BufferedReader in = new BufferedReader(
    new InputStreamReader(con.getInputStream()));
String inputLine;
StringBuffer response = new StringBuffer();
while ((inputLine = in.readLine()) != null) {
    response.append(inputLine);
}
in.close();
System.out.println(response.toString());

```

```go
package main

import (
       "bytes"
       "net/http"
)

func main() {

    headers := map[string][]string{
        "Content-Type": []string{"application/json"},
        "Accept": []string{"application/json"},
    }

    data := bytes.NewBuffer([]byte{jsonReq})
    req, err := http.NewRequest("PATCH", "/api/projects/{project_id}/insights/layouts/", data)
    req.Header = headers

    client := &http.Client{}
    resp, err := client.Do(req)
    // ...
}

```

`PATCH /api/projects/{project_id}/insights/layouts/`

Dashboard item layouts.

> Body parameter

```json
{
  "name": "string",
  "filters": {
    "property1": null,
    "property2": null
  },
  "filters_hash": "string",
  "order": -2147483648,
  "deleted": true,
  "dashboard": 0,
  "dive_dashboard": 0,
  "layouts": {
    "property1": null,
    "property2": null
  },
  "color": "string",
  "refreshing": true,
  "description": "string",
  "tags": [
    "string"
  ],
  "favorited": true,
  "saved": true
}
```

```yaml
name: string
filters:
  ? property1
  ? property2
filters_hash: string
order: -2147483648
deleted: true
dashboard: 0
dive_dashboard: 0
layouts:
  ? property1
  ? property2
color: string
refreshing: true
description: string
tags:
  - string
favorited: true
saved: true

```

<h3 id="insights_layouts_partial_update-parameters">Parameters</h3>

|Name|In|Type|Required|Description|
|---|---|---|---|---|
|project_id|path|string|true|Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/.|
|body|body|[PatchedInsight](#schemapatchedinsight)|false|none|

> Example responses

> 200 Response

```json
{
  "id": 0,
  "short_id": "string",
  "name": "string",
  "filters": {
    "property1": null,
    "property2": null
  },
  "filters_hash": "string",
  "order": -2147483648,
  "deleted": true,
  "dashboard": 0,
  "dive_dashboard": 0,
  "layouts": {
    "property1": null,
    "property2": null
  },
  "color": "string",
  "last_refresh": "string",
  "refreshing": true,
  "result": "string",
  "created_at": "2019-08-24T14:15:22Z",
  "description": "string",
  "updated_at": "2019-08-24T14:15:22Z",
  "tags": [
    "string"
  ],
  "favorited": true,
  "saved": true,
  "created_by": {
    "id": 0,
    "uuid": "095be615-a8ad-4c33-8e9c-c7612fbf6c9f",
    "distinct_id": "string",
    "first_name": "string",
    "email": "user@example.com"
  },
  "is_sample": true
}
```

<h3 id="insights_layouts_partial_update-responses">Responses</h3>

|Status|Meaning|Description|Schema|
|---|---|---|---|
|200|[OK](https://tools.ietf.org/html/rfc7231#section-6.3.1)|none|[Insight](#schemainsight)|

<aside class="success">
This operation does not require authentication
</aside>

## insights_path_retrieve

<a id="opIdinsights_path_retrieve"></a>

> Code samples

```shell
# You can also use wget
curl -X GET /api/projects/{project_id}/insights/path/ \
  -H 'Accept: application/json'

```

```http
GET /api/projects/{project_id}/insights/path/ HTTP/1.1

Accept: application/json

```

```javascript

const headers = {
  'Accept':'application/json'
};

fetch('/api/projects/{project_id}/insights/path/',
{
  method: 'GET',

  headers: headers
})
.then(function(res) {
    return res.json();
}).then(function(body) {
    console.log(body);
});

```

```ruby
require 'rest-client'
require 'json'

headers = {
  'Accept' => 'application/json'
}

result = RestClient.get '/api/projects/{project_id}/insights/path/',
  params: {
  }, headers: headers

p JSON.parse(result)

```

```python
import requests
headers = {
  'Accept': 'application/json'
}

r = requests.get('/api/projects/{project_id}/insights/path/', headers = headers)

print(r.json())

```

```php
<?php

require 'vendor/autoload.php';

$headers = array(
    'Accept' => 'application/json',
);

$client = new \GuzzleHttp\Client();

// Define array of request body.
$request_body = array();

try {
    $response = $client->request('GET','/api/projects/{project_id}/insights/path/', array(
        'headers' => $headers,
        'json' => $request_body,
       )
    );
    print_r($response->getBody()->getContents());
 }
 catch (\GuzzleHttp\Exception\BadResponseException $e) {
    // handle exception or api errors.
    print_r($e->getMessage());
 }

 // ...

```

```java
URL obj = new URL("/api/projects/{project_id}/insights/path/");
HttpURLConnection con = (HttpURLConnection) obj.openConnection();
con.setRequestMethod("GET");
int responseCode = con.getResponseCode();
BufferedReader in = new BufferedReader(
    new InputStreamReader(con.getInputStream()));
String inputLine;
StringBuffer response = new StringBuffer();
while ((inputLine = in.readLine()) != null) {
    response.append(inputLine);
}
in.close();
System.out.println(response.toString());

```

```go
package main

import (
       "bytes"
       "net/http"
)

func main() {

    headers := map[string][]string{
        "Accept": []string{"application/json"},
    }

    data := bytes.NewBuffer([]byte{jsonReq})
    req, err := http.NewRequest("GET", "/api/projects/{project_id}/insights/path/", data)
    req.Header = headers

    client := &http.Client{}
    resp, err := client.Do(req)
    // ...
}

```

`GET /api/projects/{project_id}/insights/path/`

<h3 id="insights_path_retrieve-parameters">Parameters</h3>

|Name|In|Type|Required|Description|
|---|---|---|---|---|
|project_id|path|string|true|Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/.|

> Example responses

> 200 Response

```json
{
  "id": 0,
  "short_id": "string",
  "name": "string",
  "filters": {
    "property1": null,
    "property2": null
  },
  "filters_hash": "string",
  "order": -2147483648,
  "deleted": true,
  "dashboard": 0,
  "dive_dashboard": 0,
  "layouts": {
    "property1": null,
    "property2": null
  },
  "color": "string",
  "last_refresh": "string",
  "refreshing": true,
  "result": "string",
  "created_at": "2019-08-24T14:15:22Z",
  "description": "string",
  "updated_at": "2019-08-24T14:15:22Z",
  "tags": [
    "string"
  ],
  "favorited": true,
  "saved": true,
  "created_by": {
    "id": 0,
    "uuid": "095be615-a8ad-4c33-8e9c-c7612fbf6c9f",
    "distinct_id": "string",
    "first_name": "string",
    "email": "user@example.com"
  },
  "is_sample": true
}
```

<h3 id="insights_path_retrieve-responses">Responses</h3>

|Status|Meaning|Description|Schema|
|---|---|---|---|
|200|[OK](https://tools.ietf.org/html/rfc7231#section-6.3.1)|none|[Insight](#schemainsight)|

<aside class="success">
This operation does not require authentication
</aside>

## insights_path_create

<a id="opIdinsights_path_create"></a>

> Code samples

```shell
# You can also use wget
curl -X POST /api/projects/{project_id}/insights/path/ \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json'

```

```http
POST /api/projects/{project_id}/insights/path/ HTTP/1.1

Content-Type: application/json
Accept: application/json

```

```javascript
const inputBody = '{
  "name": "string",
  "filters": {
    "property1": null,
    "property2": null
  },
  "filters_hash": "string",
  "order": -2147483648,
  "deleted": true,
  "dashboard": 0,
  "dive_dashboard": 0,
  "layouts": {
    "property1": null,
    "property2": null
  },
  "color": "string",
  "refreshing": true,
  "description": "string",
  "tags": [
    "string"
  ],
  "favorited": true,
  "saved": true
}';
const headers = {
  'Content-Type':'application/json',
  'Accept':'application/json'
};

fetch('/api/projects/{project_id}/insights/path/',
{
  method: 'POST',
  body: inputBody,
  headers: headers
})
.then(function(res) {
    return res.json();
}).then(function(body) {
    console.log(body);
});

```

```ruby
require 'rest-client'
require 'json'

headers = {
  'Content-Type' => 'application/json',
  'Accept' => 'application/json'
}

result = RestClient.post '/api/projects/{project_id}/insights/path/',
  params: {
  }, headers: headers

p JSON.parse(result)

```

```python
import requests
headers = {
  'Content-Type': 'application/json',
  'Accept': 'application/json'
}

r = requests.post('/api/projects/{project_id}/insights/path/', headers = headers)

print(r.json())

```

```php
<?php

require 'vendor/autoload.php';

$headers = array(
    'Content-Type' => 'application/json',
    'Accept' => 'application/json',
);

$client = new \GuzzleHttp\Client();

// Define array of request body.
$request_body = array();

try {
    $response = $client->request('POST','/api/projects/{project_id}/insights/path/', array(
        'headers' => $headers,
        'json' => $request_body,
       )
    );
    print_r($response->getBody()->getContents());
 }
 catch (\GuzzleHttp\Exception\BadResponseException $e) {
    // handle exception or api errors.
    print_r($e->getMessage());
 }

 // ...

```

```java
URL obj = new URL("/api/projects/{project_id}/insights/path/");
HttpURLConnection con = (HttpURLConnection) obj.openConnection();
con.setRequestMethod("POST");
int responseCode = con.getResponseCode();
BufferedReader in = new BufferedReader(
    new InputStreamReader(con.getInputStream()));
String inputLine;
StringBuffer response = new StringBuffer();
while ((inputLine = in.readLine()) != null) {
    response.append(inputLine);
}
in.close();
System.out.println(response.toString());

```

```go
package main

import (
       "bytes"
       "net/http"
)

func main() {

    headers := map[string][]string{
        "Content-Type": []string{"application/json"},
        "Accept": []string{"application/json"},
    }

    data := bytes.NewBuffer([]byte{jsonReq})
    req, err := http.NewRequest("POST", "/api/projects/{project_id}/insights/path/", data)
    req.Header = headers

    client := &http.Client{}
    resp, err := client.Do(req)
    // ...
}

```

`POST /api/projects/{project_id}/insights/path/`

> Body parameter

```json
{
  "name": "string",
  "filters": {
    "property1": null,
    "property2": null
  },
  "filters_hash": "string",
  "order": -2147483648,
  "deleted": true,
  "dashboard": 0,
  "dive_dashboard": 0,
  "layouts": {
    "property1": null,
    "property2": null
  },
  "color": "string",
  "refreshing": true,
  "description": "string",
  "tags": [
    "string"
  ],
  "favorited": true,
  "saved": true
}
```

```yaml
name: string
filters:
  ? property1
  ? property2
filters_hash: string
order: -2147483648
deleted: true
dashboard: 0
dive_dashboard: 0
layouts:
  ? property1
  ? property2
color: string
refreshing: true
description: string
tags:
  - string
favorited: true
saved: true

```

<h3 id="insights_path_create-parameters">Parameters</h3>

|Name|In|Type|Required|Description|
|---|---|---|---|---|
|project_id|path|string|true|Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/.|
|body|body|[Insight](#schemainsight)|false|none|

> Example responses

> 200 Response

```json
{
  "id": 0,
  "short_id": "string",
  "name": "string",
  "filters": {
    "property1": null,
    "property2": null
  },
  "filters_hash": "string",
  "order": -2147483648,
  "deleted": true,
  "dashboard": 0,
  "dive_dashboard": 0,
  "layouts": {
    "property1": null,
    "property2": null
  },
  "color": "string",
  "last_refresh": "string",
  "refreshing": true,
  "result": "string",
  "created_at": "2019-08-24T14:15:22Z",
  "description": "string",
  "updated_at": "2019-08-24T14:15:22Z",
  "tags": [
    "string"
  ],
  "favorited": true,
  "saved": true,
  "created_by": {
    "id": 0,
    "uuid": "095be615-a8ad-4c33-8e9c-c7612fbf6c9f",
    "distinct_id": "string",
    "first_name": "string",
    "email": "user@example.com"
  },
  "is_sample": true
}
```

<h3 id="insights_path_create-responses">Responses</h3>

|Status|Meaning|Description|Schema|
|---|---|---|---|
|200|[OK](https://tools.ietf.org/html/rfc7231#section-6.3.1)|none|[Insight](#schemainsight)|

<aside class="success">
This operation does not require authentication
</aside>

## insights_retention_retrieve

<a id="opIdinsights_retention_retrieve"></a>

> Code samples

```shell
# You can also use wget
curl -X GET /api/projects/{project_id}/insights/retention/ \
  -H 'Accept: application/json'

```

```http
GET /api/projects/{project_id}/insights/retention/ HTTP/1.1

Accept: application/json

```

```javascript

const headers = {
  'Accept':'application/json'
};

fetch('/api/projects/{project_id}/insights/retention/',
{
  method: 'GET',

  headers: headers
})
.then(function(res) {
    return res.json();
}).then(function(body) {
    console.log(body);
});

```

```ruby
require 'rest-client'
require 'json'

headers = {
  'Accept' => 'application/json'
}

result = RestClient.get '/api/projects/{project_id}/insights/retention/',
  params: {
  }, headers: headers

p JSON.parse(result)

```

```python
import requests
headers = {
  'Accept': 'application/json'
}

r = requests.get('/api/projects/{project_id}/insights/retention/', headers = headers)

print(r.json())

```

```php
<?php

require 'vendor/autoload.php';

$headers = array(
    'Accept' => 'application/json',
);

$client = new \GuzzleHttp\Client();

// Define array of request body.
$request_body = array();

try {
    $response = $client->request('GET','/api/projects/{project_id}/insights/retention/', array(
        'headers' => $headers,
        'json' => $request_body,
       )
    );
    print_r($response->getBody()->getContents());
 }
 catch (\GuzzleHttp\Exception\BadResponseException $e) {
    // handle exception or api errors.
    print_r($e->getMessage());
 }

 // ...

```

```java
URL obj = new URL("/api/projects/{project_id}/insights/retention/");
HttpURLConnection con = (HttpURLConnection) obj.openConnection();
con.setRequestMethod("GET");
int responseCode = con.getResponseCode();
BufferedReader in = new BufferedReader(
    new InputStreamReader(con.getInputStream()));
String inputLine;
StringBuffer response = new StringBuffer();
while ((inputLine = in.readLine()) != null) {
    response.append(inputLine);
}
in.close();
System.out.println(response.toString());

```

```go
package main

import (
       "bytes"
       "net/http"
)

func main() {

    headers := map[string][]string{
        "Accept": []string{"application/json"},
    }

    data := bytes.NewBuffer([]byte{jsonReq})
    req, err := http.NewRequest("GET", "/api/projects/{project_id}/insights/retention/", data)
    req.Header = headers

    client := &http.Client{}
    resp, err := client.Do(req)
    // ...
}

```

`GET /api/projects/{project_id}/insights/retention/`

<h3 id="insights_retention_retrieve-parameters">Parameters</h3>

|Name|In|Type|Required|Description|
|---|---|---|---|---|
|project_id|path|string|true|Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/.|

> Example responses

> 200 Response

```json
{
  "id": 0,
  "short_id": "string",
  "name": "string",
  "filters": {
    "property1": null,
    "property2": null
  },
  "filters_hash": "string",
  "order": -2147483648,
  "deleted": true,
  "dashboard": 0,
  "dive_dashboard": 0,
  "layouts": {
    "property1": null,
    "property2": null
  },
  "color": "string",
  "last_refresh": "string",
  "refreshing": true,
  "result": "string",
  "created_at": "2019-08-24T14:15:22Z",
  "description": "string",
  "updated_at": "2019-08-24T14:15:22Z",
  "tags": [
    "string"
  ],
  "favorited": true,
  "saved": true,
  "created_by": {
    "id": 0,
    "uuid": "095be615-a8ad-4c33-8e9c-c7612fbf6c9f",
    "distinct_id": "string",
    "first_name": "string",
    "email": "user@example.com"
  },
  "is_sample": true
}
```

<h3 id="insights_retention_retrieve-responses">Responses</h3>

|Status|Meaning|Description|Schema|
|---|---|---|---|
|200|[OK](https://tools.ietf.org/html/rfc7231#section-6.3.1)|none|[Insight](#schemainsight)|

<aside class="success">
This operation does not require authentication
</aside>

## insights_trend_retrieve

<a id="opIdinsights_trend_retrieve"></a>

> Code samples

```shell
# You can also use wget
curl -X GET /api/projects/{project_id}/insights/trend/ \
  -H 'Accept: application/json'

```

```http
GET /api/projects/{project_id}/insights/trend/ HTTP/1.1

Accept: application/json

```

```javascript

const headers = {
  'Accept':'application/json'
};

fetch('/api/projects/{project_id}/insights/trend/',
{
  method: 'GET',

  headers: headers
})
.then(function(res) {
    return res.json();
}).then(function(body) {
    console.log(body);
});

```

```ruby
require 'rest-client'
require 'json'

headers = {
  'Accept' => 'application/json'
}

result = RestClient.get '/api/projects/{project_id}/insights/trend/',
  params: {
  }, headers: headers

p JSON.parse(result)

```

```python
import requests
headers = {
  'Accept': 'application/json'
}

r = requests.get('/api/projects/{project_id}/insights/trend/', headers = headers)

print(r.json())

```

```php
<?php

require 'vendor/autoload.php';

$headers = array(
    'Accept' => 'application/json',
);

$client = new \GuzzleHttp\Client();

// Define array of request body.
$request_body = array();

try {
    $response = $client->request('GET','/api/projects/{project_id}/insights/trend/', array(
        'headers' => $headers,
        'json' => $request_body,
       )
    );
    print_r($response->getBody()->getContents());
 }
 catch (\GuzzleHttp\Exception\BadResponseException $e) {
    // handle exception or api errors.
    print_r($e->getMessage());
 }

 // ...

```

```java
URL obj = new URL("/api/projects/{project_id}/insights/trend/");
HttpURLConnection con = (HttpURLConnection) obj.openConnection();
con.setRequestMethod("GET");
int responseCode = con.getResponseCode();
BufferedReader in = new BufferedReader(
    new InputStreamReader(con.getInputStream()));
String inputLine;
StringBuffer response = new StringBuffer();
while ((inputLine = in.readLine()) != null) {
    response.append(inputLine);
}
in.close();
System.out.println(response.toString());

```

```go
package main

import (
       "bytes"
       "net/http"
)

func main() {

    headers := map[string][]string{
        "Accept": []string{"application/json"},
    }

    data := bytes.NewBuffer([]byte{jsonReq})
    req, err := http.NewRequest("GET", "/api/projects/{project_id}/insights/trend/", data)
    req.Header = headers

    client := &http.Client{}
    resp, err := client.Do(req)
    // ...
}

```

`GET /api/projects/{project_id}/insights/trend/`

<h3 id="insights_trend_retrieve-parameters">Parameters</h3>

|Name|In|Type|Required|Description|
|---|---|---|---|---|
|project_id|path|string|true|Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/.|

> Example responses

> 200 Response

```json
{
  "id": 0,
  "short_id": "string",
  "name": "string",
  "filters": {
    "property1": null,
    "property2": null
  },
  "filters_hash": "string",
  "order": -2147483648,
  "deleted": true,
  "dashboard": 0,
  "dive_dashboard": 0,
  "layouts": {
    "property1": null,
    "property2": null
  },
  "color": "string",
  "last_refresh": "string",
  "refreshing": true,
  "result": "string",
  "created_at": "2019-08-24T14:15:22Z",
  "description": "string",
  "updated_at": "2019-08-24T14:15:22Z",
  "tags": [
    "string"
  ],
  "favorited": true,
  "saved": true,
  "created_by": {
    "id": 0,
    "uuid": "095be615-a8ad-4c33-8e9c-c7612fbf6c9f",
    "distinct_id": "string",
    "first_name": "string",
    "email": "user@example.com"
  },
  "is_sample": true
}
```

<h3 id="insights_trend_retrieve-responses">Responses</h3>

|Status|Meaning|Description|Schema|
|---|---|---|---|
|200|[OK](https://tools.ietf.org/html/rfc7231#section-6.3.1)|none|[Insight](#schemainsight)|

<aside class="success">
This operation does not require authentication
</aside>

<h1 id="-analytics">analytics</h1>

## Funnels

<a id="opIdFunnels"></a>

> Code samples

```shell
# You can also use wget
curl -X POST /api/projects/{project_id}/insights/funnel/ \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json'

```

```http
POST /api/projects/{project_id}/insights/funnel/ HTTP/1.1

Content-Type: application/json
Accept: application/json

```

```javascript
const inputBody = '{
  "events": [
    {
      "id": "string",
      "properties": [
        {
          "key": "string",
          "value": "string",
          "operator": "exact",
          "type": "event"
        }
      ]
    }
  ],
  "actions": [
    {
      "id": "string",
      "properties": [
        {
          "key": "string",
          "value": "string",
          "operator": "exact",
          "type": "event"
        }
      ]
    }
  ],
  "properties": [
    {
      "key": "string",
      "value": "string",
      "operator": "exact",
      "type": "event"
    }
  ],
  "filter_test_accounts": false,
  "date_from": "-7d",
  "date_to": "-7d",
  "breakdown": "string",
  "breakdown_type": "event",
  "funnel_window_interval": 14,
  "funnel_window_interval_type": "DAY",
  "funnel_viz_type": "trends",
  "funnel_order_type": "strict",
  "exclusions": [
    {
      "id": "string",
      "properties": [
        {
          "key": "string",
          "value": "string",
          "operator": "exact",
          "type": "event"
        }
      ],
      "funnel_from_step": 0,
      "funnel_to_step": 1
    }
  ],
  "aggregation_group_type_index": 0,
  "breakdown_limit": 10,
  "funnel_window_days": 14
}';
const headers = {
  'Content-Type':'application/json',
  'Accept':'application/json'
};

fetch('/api/projects/{project_id}/insights/funnel/',
{
  method: 'POST',
  body: inputBody,
  headers: headers
})
.then(function(res) {
    return res.json();
}).then(function(body) {
    console.log(body);
});

```

```ruby
require 'rest-client'
require 'json'

headers = {
  'Content-Type' => 'application/json',
  'Accept' => 'application/json'
}

result = RestClient.post '/api/projects/{project_id}/insights/funnel/',
  params: {
  }, headers: headers

p JSON.parse(result)

```

```python
import requests
headers = {
  'Content-Type': 'application/json',
  'Accept': 'application/json'
}

r = requests.post('/api/projects/{project_id}/insights/funnel/', headers = headers)

print(r.json())

```

```php
<?php

require 'vendor/autoload.php';

$headers = array(
    'Content-Type' => 'application/json',
    'Accept' => 'application/json',
);

$client = new \GuzzleHttp\Client();

// Define array of request body.
$request_body = array();

try {
    $response = $client->request('POST','/api/projects/{project_id}/insights/funnel/', array(
        'headers' => $headers,
        'json' => $request_body,
       )
    );
    print_r($response->getBody()->getContents());
 }
 catch (\GuzzleHttp\Exception\BadResponseException $e) {
    // handle exception or api errors.
    print_r($e->getMessage());
 }

 // ...

```

```java
URL obj = new URL("/api/projects/{project_id}/insights/funnel/");
HttpURLConnection con = (HttpURLConnection) obj.openConnection();
con.setRequestMethod("POST");
int responseCode = con.getResponseCode();
BufferedReader in = new BufferedReader(
    new InputStreamReader(con.getInputStream()));
String inputLine;
StringBuffer response = new StringBuffer();
while ((inputLine = in.readLine()) != null) {
    response.append(inputLine);
}
in.close();
System.out.println(response.toString());

```

```go
package main

import (
       "bytes"
       "net/http"
)

func main() {

    headers := map[string][]string{
        "Content-Type": []string{"application/json"},
        "Accept": []string{"application/json"},
    }

    data := bytes.NewBuffer([]byte{jsonReq})
    req, err := http.NewRequest("POST", "/api/projects/{project_id}/insights/funnel/", data)
    req.Header = headers

    client := &http.Client{}
    resp, err := client.Do(req)
    // ...
}

```

`POST /api/projects/{project_id}/insights/funnel/`

> Body parameter

```json
{
  "events": [
    {
      "id": "string",
      "properties": [
        {
          "key": "string",
          "value": "string",
          "operator": "exact",
          "type": "event"
        }
      ]
    }
  ],
  "actions": [
    {
      "id": "string",
      "properties": [
        {
          "key": "string",
          "value": "string",
          "operator": "exact",
          "type": "event"
        }
      ]
    }
  ],
  "properties": [
    {
      "key": "string",
      "value": "string",
      "operator": "exact",
      "type": "event"
    }
  ],
  "filter_test_accounts": false,
  "date_from": "-7d",
  "date_to": "-7d",
  "breakdown": "string",
  "breakdown_type": "event",
  "funnel_window_interval": 14,
  "funnel_window_interval_type": "DAY",
  "funnel_viz_type": "trends",
  "funnel_order_type": "strict",
  "exclusions": [
    {
      "id": "string",
      "properties": [
        {
          "key": "string",
          "value": "string",
          "operator": "exact",
          "type": "event"
        }
      ],
      "funnel_from_step": 0,
      "funnel_to_step": 1
    }
  ],
  "aggregation_group_type_index": 0,
  "breakdown_limit": 10,
  "funnel_window_days": 14
}
```

```yaml
events:
  - id: string
    properties:
      - key: string
        value: string
        operator: exact
        type: event
actions:
  - id: string
    properties:
      - key: string
        value: string
        operator: exact
        type: event
properties:
  - key: string
    value: string
    operator: exact
    type: event
filter_test_accounts: false
date_from: -7d
date_to: -7d
breakdown: string
breakdown_type: event
funnel_window_interval: 14
funnel_window_interval_type: DAY
funnel_viz_type: trends
funnel_order_type: strict
exclusions:
  - id: string
    properties:
      - key: string
        value: string
        operator: exact
        type: event
    funnel_from_step: 0
    funnel_to_step: 1
aggregation_group_type_index: 0
breakdown_limit: 10
funnel_window_days: 14

```

<h3 id="funnels-parameters">Parameters</h3>

|Name|In|Type|Required|Description|
|---|---|---|---|---|
|project_id|path|string|true|Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/.|
|body|body|[Funnel](#schemafunnel)|false|none|

> Example responses

> 200 Response

```json
{
  "is_cached": true,
  "last_refresh": "2019-08-24T14:15:22Z",
  "result": [
    {
      "count": 0,
      "action_id": "string",
      "average_conversion_time": 0,
      "median_conversion_time": 0,
      "converted_people_url": "string",
      "dropped_people_url": "string",
      "order": "string"
    }
  ]
}
```

<h3 id="funnels-responses">Responses</h3>

|Status|Meaning|Description|Schema|
|---|---|---|---|
|200|[OK](https://tools.ietf.org/html/rfc7231#section-6.3.1)|Note, if funnel_viz_type is set the response will be different.|[FunnelStepsResults](#schemafunnelstepsresults)|

<aside class="success">
This operation does not require authentication
</aside>

## Trends

<a id="opIdTrends"></a>

> Code samples

```shell
# You can also use wget
curl -X POST /api/projects/{project_id}/insights/trend/ \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json'

```

```http
POST /api/projects/{project_id}/insights/trend/ HTTP/1.1

Content-Type: application/json
Accept: application/json

```

```javascript
const inputBody = '{
  "events": [
    {
      "id": "string",
      "properties": [
        {
          "key": "string",
          "value": "string",
          "operator": "exact",
          "type": "event"
        }
      ]
    }
  ],
  "actions": [
    {
      "id": "string",
      "properties": [
        {
          "key": "string",
          "value": "string",
          "operator": "exact",
          "type": "event"
        }
      ]
    }
  ],
  "properties": [
    {
      "key": "string",
      "value": "string",
      "operator": "exact",
      "type": "event"
    }
  ],
  "filter_test_accounts": false,
  "date_from": "-7d",
  "date_to": "-7d",
  "breakdown": "string",
  "breakdown_type": "event",
  "display": "ActionsLineGraphLinear",
  "formula": "string",
  "compare": true
}';
const headers = {
  'Content-Type':'application/json',
  'Accept':'application/json'
};

fetch('/api/projects/{project_id}/insights/trend/',
{
  method: 'POST',
  body: inputBody,
  headers: headers
})
.then(function(res) {
    return res.json();
}).then(function(body) {
    console.log(body);
});

```

```ruby
require 'rest-client'
require 'json'

headers = {
  'Content-Type' => 'application/json',
  'Accept' => 'application/json'
}

result = RestClient.post '/api/projects/{project_id}/insights/trend/',
  params: {
  }, headers: headers

p JSON.parse(result)

```

```python
import requests
headers = {
  'Content-Type': 'application/json',
  'Accept': 'application/json'
}

r = requests.post('/api/projects/{project_id}/insights/trend/', headers = headers)

print(r.json())

```

```php
<?php

require 'vendor/autoload.php';

$headers = array(
    'Content-Type' => 'application/json',
    'Accept' => 'application/json',
);

$client = new \GuzzleHttp\Client();

// Define array of request body.
$request_body = array();

try {
    $response = $client->request('POST','/api/projects/{project_id}/insights/trend/', array(
        'headers' => $headers,
        'json' => $request_body,
       )
    );
    print_r($response->getBody()->getContents());
 }
 catch (\GuzzleHttp\Exception\BadResponseException $e) {
    // handle exception or api errors.
    print_r($e->getMessage());
 }

 // ...

```

```java
URL obj = new URL("/api/projects/{project_id}/insights/trend/");
HttpURLConnection con = (HttpURLConnection) obj.openConnection();
con.setRequestMethod("POST");
int responseCode = con.getResponseCode();
BufferedReader in = new BufferedReader(
    new InputStreamReader(con.getInputStream()));
String inputLine;
StringBuffer response = new StringBuffer();
while ((inputLine = in.readLine()) != null) {
    response.append(inputLine);
}
in.close();
System.out.println(response.toString());

```

```go
package main

import (
       "bytes"
       "net/http"
)

func main() {

    headers := map[string][]string{
        "Content-Type": []string{"application/json"},
        "Accept": []string{"application/json"},
    }

    data := bytes.NewBuffer([]byte{jsonReq})
    req, err := http.NewRequest("POST", "/api/projects/{project_id}/insights/trend/", data)
    req.Header = headers

    client := &http.Client{}
    resp, err := client.Do(req)
    // ...
}

```

`POST /api/projects/{project_id}/insights/trend/`

> Body parameter

```json
{
  "events": [
    {
      "id": "string",
      "properties": [
        {
          "key": "string",
          "value": "string",
          "operator": "exact",
          "type": "event"
        }
      ]
    }
  ],
  "actions": [
    {
      "id": "string",
      "properties": [
        {
          "key": "string",
          "value": "string",
          "operator": "exact",
          "type": "event"
        }
      ]
    }
  ],
  "properties": [
    {
      "key": "string",
      "value": "string",
      "operator": "exact",
      "type": "event"
    }
  ],
  "filter_test_accounts": false,
  "date_from": "-7d",
  "date_to": "-7d",
  "breakdown": "string",
  "breakdown_type": "event",
  "display": "ActionsLineGraphLinear",
  "formula": "string",
  "compare": true
}
```

```yaml
events:
  - id: string
    properties:
      - key: string
        value: string
        operator: exact
        type: event
actions:
  - id: string
    properties:
      - key: string
        value: string
        operator: exact
        type: event
properties:
  - key: string
    value: string
    operator: exact
    type: event
filter_test_accounts: false
date_from: -7d
date_to: -7d
breakdown: string
breakdown_type: event
display: ActionsLineGraphLinear
formula: string
compare: true

```

<h3 id="trends-parameters">Parameters</h3>

|Name|In|Type|Required|Description|
|---|---|---|---|---|
|project_id|path|string|true|Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/.|
|body|body|[Trend](#schematrend)|false|none|

> Example responses

> 200 Response

```json
{
  "is_cached": true,
  "last_refresh": "2019-08-24T14:15:22Z",
  "result": [
    {
      "data": [
        0
      ],
      "days": [
        "2019-08-24"
      ],
      "labels": [
        "string"
      ],
      "filter": {
        "events": [
          {
            "id": "string",
            "properties": [
              {
                "key": "string",
                "value": "string",
                "operator": "exact",
                "type": "event"
              }
            ]
          }
        ],
        "actions": [
          {
            "id": "string",
            "properties": [
              {
                "key": "string",
                "value": "string",
                "operator": "exact",
                "type": "event"
              }
            ]
          }
        ],
        "properties": [
          {
            "key": "string",
            "value": "string",
            "operator": "exact",
            "type": "event"
          }
        ],
        "filter_test_accounts": false,
        "date_from": "-7d",
        "date_to": "-7d"
      },
      "label": "string"
    }
  ]
}
```

<h3 id="trends-responses">Responses</h3>

|Status|Meaning|Description|Schema|
|---|---|---|---|
|200|[OK](https://tools.ietf.org/html/rfc7231#section-6.3.1)|none|[TrendResults](#schematrendresults)|

<aside class="success">
This operation does not require authentication
</aside>

<h1 id="-paths">paths</h1>

## paths_retrieve

<a id="opIdpaths_retrieve"></a>

> Code samples

```shell
# You can also use wget
curl -X GET /api/projects/{project_id}/paths/

```

```http
GET /api/projects/{project_id}/paths/ HTTP/1.1

```

```javascript

fetch('/api/projects/{project_id}/paths/',
{
  method: 'GET'

})
.then(function(res) {
    return res.json();
}).then(function(body) {
    console.log(body);
});

```

```ruby
require 'rest-client'
require 'json'

result = RestClient.get '/api/projects/{project_id}/paths/',
  params: {
  }

p JSON.parse(result)

```

```python
import requests

r = requests.get('/api/projects/{project_id}/paths/')

print(r.json())

```

```php
<?php

require 'vendor/autoload.php';

$client = new \GuzzleHttp\Client();

// Define array of request body.
$request_body = array();

try {
    $response = $client->request('GET','/api/projects/{project_id}/paths/', array(
        'headers' => $headers,
        'json' => $request_body,
       )
    );
    print_r($response->getBody()->getContents());
 }
 catch (\GuzzleHttp\Exception\BadResponseException $e) {
    // handle exception or api errors.
    print_r($e->getMessage());
 }

 // ...

```

```java
URL obj = new URL("/api/projects/{project_id}/paths/");
HttpURLConnection con = (HttpURLConnection) obj.openConnection();
con.setRequestMethod("GET");
int responseCode = con.getResponseCode();
BufferedReader in = new BufferedReader(
    new InputStreamReader(con.getInputStream()));
String inputLine;
StringBuffer response = new StringBuffer();
while ((inputLine = in.readLine()) != null) {
    response.append(inputLine);
}
in.close();
System.out.println(response.toString());

```

```go
package main

import (
       "bytes"
       "net/http"
)

func main() {

    data := bytes.NewBuffer([]byte{jsonReq})
    req, err := http.NewRequest("GET", "/api/projects/{project_id}/paths/", data)
    req.Header = headers

    client := &http.Client{}
    resp, err := client.Do(req)
    // ...
}

```

`GET /api/projects/{project_id}/paths/`

<h3 id="paths_retrieve-parameters">Parameters</h3>

|Name|In|Type|Required|Description|
|---|---|---|---|---|
|project_id|path|string|true|Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/.|

<h3 id="paths_retrieve-responses">Responses</h3>

|Status|Meaning|Description|Schema|
|---|---|---|---|
|200|[OK](https://tools.ietf.org/html/rfc7231#section-6.3.1)|No response body|None|

<aside class="success">
This operation does not require authentication
</aside>

## paths_elements_retrieve

<a id="opIdpaths_elements_retrieve"></a>

> Code samples

```shell
# You can also use wget
curl -X GET /api/projects/{project_id}/paths/elements/

```

```http
GET /api/projects/{project_id}/paths/elements/ HTTP/1.1

```

```javascript

fetch('/api/projects/{project_id}/paths/elements/',
{
  method: 'GET'

})
.then(function(res) {
    return res.json();
}).then(function(body) {
    console.log(body);
});

```

```ruby
require 'rest-client'
require 'json'

result = RestClient.get '/api/projects/{project_id}/paths/elements/',
  params: {
  }

p JSON.parse(result)

```

```python
import requests

r = requests.get('/api/projects/{project_id}/paths/elements/')

print(r.json())

```

```php
<?php

require 'vendor/autoload.php';

$client = new \GuzzleHttp\Client();

// Define array of request body.
$request_body = array();

try {
    $response = $client->request('GET','/api/projects/{project_id}/paths/elements/', array(
        'headers' => $headers,
        'json' => $request_body,
       )
    );
    print_r($response->getBody()->getContents());
 }
 catch (\GuzzleHttp\Exception\BadResponseException $e) {
    // handle exception or api errors.
    print_r($e->getMessage());
 }

 // ...

```

```java
URL obj = new URL("/api/projects/{project_id}/paths/elements/");
HttpURLConnection con = (HttpURLConnection) obj.openConnection();
con.setRequestMethod("GET");
int responseCode = con.getResponseCode();
BufferedReader in = new BufferedReader(
    new InputStreamReader(con.getInputStream()));
String inputLine;
StringBuffer response = new StringBuffer();
while ((inputLine = in.readLine()) != null) {
    response.append(inputLine);
}
in.close();
System.out.println(response.toString());

```

```go
package main

import (
       "bytes"
       "net/http"
)

func main() {

    data := bytes.NewBuffer([]byte{jsonReq})
    req, err := http.NewRequest("GET", "/api/projects/{project_id}/paths/elements/", data)
    req.Header = headers

    client := &http.Client{}
    resp, err := client.Do(req)
    // ...
}

```

`GET /api/projects/{project_id}/paths/elements/`

<h3 id="paths_elements_retrieve-parameters">Parameters</h3>

|Name|In|Type|Required|Description|
|---|---|---|---|---|
|project_id|path|string|true|Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/.|

<h3 id="paths_elements_retrieve-responses">Responses</h3>

|Status|Meaning|Description|Schema|
|---|---|---|---|
|200|[OK](https://tools.ietf.org/html/rfc7231#section-6.3.1)|No response body|None|

<aside class="success">
This operation does not require authentication
</aside>

<h1 id="-persons">persons</h1>

## persons_list

<a id="opIdpersons_list"></a>

> Code samples

```shell
# You can also use wget
curl -X GET /api/projects/{project_id}/persons/ \
  -H 'Accept: application/json'

```

```http
GET /api/projects/{project_id}/persons/ HTTP/1.1

Accept: application/json

```

```javascript

const headers = {
  'Accept':'application/json'
};

fetch('/api/projects/{project_id}/persons/',
{
  method: 'GET',

  headers: headers
})
.then(function(res) {
    return res.json();
}).then(function(body) {
    console.log(body);
});

```

```ruby
require 'rest-client'
require 'json'

headers = {
  'Accept' => 'application/json'
}

result = RestClient.get '/api/projects/{project_id}/persons/',
  params: {
  }, headers: headers

p JSON.parse(result)

```

```python
import requests
headers = {
  'Accept': 'application/json'
}

r = requests.get('/api/projects/{project_id}/persons/', headers = headers)

print(r.json())

```

```php
<?php

require 'vendor/autoload.php';

$headers = array(
    'Accept' => 'application/json',
);

$client = new \GuzzleHttp\Client();

// Define array of request body.
$request_body = array();

try {
    $response = $client->request('GET','/api/projects/{project_id}/persons/', array(
        'headers' => $headers,
        'json' => $request_body,
       )
    );
    print_r($response->getBody()->getContents());
 }
 catch (\GuzzleHttp\Exception\BadResponseException $e) {
    // handle exception or api errors.
    print_r($e->getMessage());
 }

 // ...

```

```java
URL obj = new URL("/api/projects/{project_id}/persons/");
HttpURLConnection con = (HttpURLConnection) obj.openConnection();
con.setRequestMethod("GET");
int responseCode = con.getResponseCode();
BufferedReader in = new BufferedReader(
    new InputStreamReader(con.getInputStream()));
String inputLine;
StringBuffer response = new StringBuffer();
while ((inputLine = in.readLine()) != null) {
    response.append(inputLine);
}
in.close();
System.out.println(response.toString());

```

```go
package main

import (
       "bytes"
       "net/http"
)

func main() {

    headers := map[string][]string{
        "Accept": []string{"application/json"},
    }

    data := bytes.NewBuffer([]byte{jsonReq})
    req, err := http.NewRequest("GET", "/api/projects/{project_id}/persons/", data)
    req.Header = headers

    client := &http.Client{}
    resp, err := client.Do(req)
    // ...
}

```

`GET /api/projects/{project_id}/persons/`

<h3 id="persons_list-parameters">Parameters</h3>

|Name|In|Type|Required|Description|
|---|---|---|---|---|
|cursor|query|integer|false|The pagination cursor value.|
|distinct_id|query|string|false|none|
|email|query|string|false|none|
|format|query|string|false|none|
|key_identifier|query|string|false|none|
|project_id|path|string|true|Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/.|

#### Enumerated Values

|Parameter|Value|
|---|---|
|format|csv|
|format|json|

> Example responses

> 200 Response

```json
{
  "next": "string",
  "previous": "string",
  "results": [
    {
      "id": 0,
      "name": "string",
      "distinct_ids": [
        "string"
      ],
      "properties": {
        "property1": null,
        "property2": null
      },
      "created_at": "2019-08-24T14:15:22Z",
      "uuid": "095be615-a8ad-4c33-8e9c-c7612fbf6c9f"
    }
  ]
}
```

<h3 id="persons_list-responses">Responses</h3>

|Status|Meaning|Description|Schema|
|---|---|---|---|
|200|[OK](https://tools.ietf.org/html/rfc7231#section-6.3.1)|none|[PaginatedPersonList](#schemapaginatedpersonlist)|

<aside class="success">
This operation does not require authentication
</aside>

## persons_create

<a id="opIdpersons_create"></a>

> Code samples

```shell
# You can also use wget
curl -X POST /api/projects/{project_id}/persons/ \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json'

```

```http
POST /api/projects/{project_id}/persons/ HTTP/1.1

Content-Type: application/json
Accept: application/json

```

```javascript
const inputBody = '{
  "properties": {
    "property1": null,
    "property2": null
  }
}';
const headers = {
  'Content-Type':'application/json',
  'Accept':'application/json'
};

fetch('/api/projects/{project_id}/persons/',
{
  method: 'POST',
  body: inputBody,
  headers: headers
})
.then(function(res) {
    return res.json();
}).then(function(body) {
    console.log(body);
});

```

```ruby
require 'rest-client'
require 'json'

headers = {
  'Content-Type' => 'application/json',
  'Accept' => 'application/json'
}

result = RestClient.post '/api/projects/{project_id}/persons/',
  params: {
  }, headers: headers

p JSON.parse(result)

```

```python
import requests
headers = {
  'Content-Type': 'application/json',
  'Accept': 'application/json'
}

r = requests.post('/api/projects/{project_id}/persons/', headers = headers)

print(r.json())

```

```php
<?php

require 'vendor/autoload.php';

$headers = array(
    'Content-Type' => 'application/json',
    'Accept' => 'application/json',
);

$client = new \GuzzleHttp\Client();

// Define array of request body.
$request_body = array();

try {
    $response = $client->request('POST','/api/projects/{project_id}/persons/', array(
        'headers' => $headers,
        'json' => $request_body,
       )
    );
    print_r($response->getBody()->getContents());
 }
 catch (\GuzzleHttp\Exception\BadResponseException $e) {
    // handle exception or api errors.
    print_r($e->getMessage());
 }

 // ...

```

```java
URL obj = new URL("/api/projects/{project_id}/persons/");
HttpURLConnection con = (HttpURLConnection) obj.openConnection();
con.setRequestMethod("POST");
int responseCode = con.getResponseCode();
BufferedReader in = new BufferedReader(
    new InputStreamReader(con.getInputStream()));
String inputLine;
StringBuffer response = new StringBuffer();
while ((inputLine = in.readLine()) != null) {
    response.append(inputLine);
}
in.close();
System.out.println(response.toString());

```

```go
package main

import (
       "bytes"
       "net/http"
)

func main() {

    headers := map[string][]string{
        "Content-Type": []string{"application/json"},
        "Accept": []string{"application/json"},
    }

    data := bytes.NewBuffer([]byte{jsonReq})
    req, err := http.NewRequest("POST", "/api/projects/{project_id}/persons/", data)
    req.Header = headers

    client := &http.Client{}
    resp, err := client.Do(req)
    // ...
}

```

`POST /api/projects/{project_id}/persons/`

> Body parameter

```json
{
  "properties": {
    "property1": null,
    "property2": null
  }
}
```

```yaml
properties:
  ? property1
  ? property2

```

<h3 id="persons_create-parameters">Parameters</h3>

|Name|In|Type|Required|Description|
|---|---|---|---|---|
|format|query|string|false|none|
|project_id|path|string|true|Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/.|
|body|body|[Person](#schemaperson)|false|none|

#### Enumerated Values

|Parameter|Value|
|---|---|
|format|csv|
|format|json|

> Example responses

> 201 Response

```json
{
  "id": 0,
  "name": "string",
  "distinct_ids": [
    "string"
  ],
  "properties": {
    "property1": null,
    "property2": null
  },
  "created_at": "2019-08-24T14:15:22Z",
  "uuid": "095be615-a8ad-4c33-8e9c-c7612fbf6c9f"
}
```

<h3 id="persons_create-responses">Responses</h3>

|Status|Meaning|Description|Schema|
|---|---|---|---|
|201|[Created](https://tools.ietf.org/html/rfc7231#section-6.3.2)|none|[Person](#schemaperson)|

<aside class="success">
This operation does not require authentication
</aside>

## persons_retrieve

<a id="opIdpersons_retrieve"></a>

> Code samples

```shell
# You can also use wget
curl -X GET /api/projects/{project_id}/persons/{id}/ \
  -H 'Accept: application/json'

```

```http
GET /api/projects/{project_id}/persons/{id}/ HTTP/1.1

Accept: application/json

```

```javascript

const headers = {
  'Accept':'application/json'
};

fetch('/api/projects/{project_id}/persons/{id}/',
{
  method: 'GET',

  headers: headers
})
.then(function(res) {
    return res.json();
}).then(function(body) {
    console.log(body);
});

```

```ruby
require 'rest-client'
require 'json'

headers = {
  'Accept' => 'application/json'
}

result = RestClient.get '/api/projects/{project_id}/persons/{id}/',
  params: {
  }, headers: headers

p JSON.parse(result)

```

```python
import requests
headers = {
  'Accept': 'application/json'
}

r = requests.get('/api/projects/{project_id}/persons/{id}/', headers = headers)

print(r.json())

```

```php
<?php

require 'vendor/autoload.php';

$headers = array(
    'Accept' => 'application/json',
);

$client = new \GuzzleHttp\Client();

// Define array of request body.
$request_body = array();

try {
    $response = $client->request('GET','/api/projects/{project_id}/persons/{id}/', array(
        'headers' => $headers,
        'json' => $request_body,
       )
    );
    print_r($response->getBody()->getContents());
 }
 catch (\GuzzleHttp\Exception\BadResponseException $e) {
    // handle exception or api errors.
    print_r($e->getMessage());
 }

 // ...

```

```java
URL obj = new URL("/api/projects/{project_id}/persons/{id}/");
HttpURLConnection con = (HttpURLConnection) obj.openConnection();
con.setRequestMethod("GET");
int responseCode = con.getResponseCode();
BufferedReader in = new BufferedReader(
    new InputStreamReader(con.getInputStream()));
String inputLine;
StringBuffer response = new StringBuffer();
while ((inputLine = in.readLine()) != null) {
    response.append(inputLine);
}
in.close();
System.out.println(response.toString());

```

```go
package main

import (
       "bytes"
       "net/http"
)

func main() {

    headers := map[string][]string{
        "Accept": []string{"application/json"},
    }

    data := bytes.NewBuffer([]byte{jsonReq})
    req, err := http.NewRequest("GET", "/api/projects/{project_id}/persons/{id}/", data)
    req.Header = headers

    client := &http.Client{}
    resp, err := client.Do(req)
    // ...
}

```

`GET /api/projects/{project_id}/persons/{id}/`

<h3 id="persons_retrieve-parameters">Parameters</h3>

|Name|In|Type|Required|Description|
|---|---|---|---|---|
|format|query|string|false|none|
|id|path|integer|true|A unique integer value identifying this person.|
|project_id|path|string|true|Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/.|

#### Enumerated Values

|Parameter|Value|
|---|---|
|format|csv|
|format|json|

> Example responses

> 200 Response

```json
{
  "id": 0,
  "name": "string",
  "distinct_ids": [
    "string"
  ],
  "properties": {
    "property1": null,
    "property2": null
  },
  "created_at": "2019-08-24T14:15:22Z",
  "uuid": "095be615-a8ad-4c33-8e9c-c7612fbf6c9f"
}
```

<h3 id="persons_retrieve-responses">Responses</h3>

|Status|Meaning|Description|Schema|
|---|---|---|---|
|200|[OK](https://tools.ietf.org/html/rfc7231#section-6.3.1)|none|[Person](#schemaperson)|

<aside class="success">
This operation does not require authentication
</aside>

## persons_update

<a id="opIdpersons_update"></a>

> Code samples

```shell
# You can also use wget
curl -X PUT /api/projects/{project_id}/persons/{id}/ \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json'

```

```http
PUT /api/projects/{project_id}/persons/{id}/ HTTP/1.1

Content-Type: application/json
Accept: application/json

```

```javascript
const inputBody = '{
  "properties": {
    "property1": null,
    "property2": null
  }
}';
const headers = {
  'Content-Type':'application/json',
  'Accept':'application/json'
};

fetch('/api/projects/{project_id}/persons/{id}/',
{
  method: 'PUT',
  body: inputBody,
  headers: headers
})
.then(function(res) {
    return res.json();
}).then(function(body) {
    console.log(body);
});

```

```ruby
require 'rest-client'
require 'json'

headers = {
  'Content-Type' => 'application/json',
  'Accept' => 'application/json'
}

result = RestClient.put '/api/projects/{project_id}/persons/{id}/',
  params: {
  }, headers: headers

p JSON.parse(result)

```

```python
import requests
headers = {
  'Content-Type': 'application/json',
  'Accept': 'application/json'
}

r = requests.put('/api/projects/{project_id}/persons/{id}/', headers = headers)

print(r.json())

```

```php
<?php

require 'vendor/autoload.php';

$headers = array(
    'Content-Type' => 'application/json',
    'Accept' => 'application/json',
);

$client = new \GuzzleHttp\Client();

// Define array of request body.
$request_body = array();

try {
    $response = $client->request('PUT','/api/projects/{project_id}/persons/{id}/', array(
        'headers' => $headers,
        'json' => $request_body,
       )
    );
    print_r($response->getBody()->getContents());
 }
 catch (\GuzzleHttp\Exception\BadResponseException $e) {
    // handle exception or api errors.
    print_r($e->getMessage());
 }

 // ...

```

```java
URL obj = new URL("/api/projects/{project_id}/persons/{id}/");
HttpURLConnection con = (HttpURLConnection) obj.openConnection();
con.setRequestMethod("PUT");
int responseCode = con.getResponseCode();
BufferedReader in = new BufferedReader(
    new InputStreamReader(con.getInputStream()));
String inputLine;
StringBuffer response = new StringBuffer();
while ((inputLine = in.readLine()) != null) {
    response.append(inputLine);
}
in.close();
System.out.println(response.toString());

```

```go
package main

import (
       "bytes"
       "net/http"
)

func main() {

    headers := map[string][]string{
        "Content-Type": []string{"application/json"},
        "Accept": []string{"application/json"},
    }

    data := bytes.NewBuffer([]byte{jsonReq})
    req, err := http.NewRequest("PUT", "/api/projects/{project_id}/persons/{id}/", data)
    req.Header = headers

    client := &http.Client{}
    resp, err := client.Do(req)
    // ...
}

```

`PUT /api/projects/{project_id}/persons/{id}/`

> Body parameter

```json
{
  "properties": {
    "property1": null,
    "property2": null
  }
}
```

```yaml
properties:
  ? property1
  ? property2

```

<h3 id="persons_update-parameters">Parameters</h3>

|Name|In|Type|Required|Description|
|---|---|---|---|---|
|format|query|string|false|none|
|id|path|integer|true|A unique integer value identifying this person.|
|project_id|path|string|true|Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/.|
|body|body|[Person](#schemaperson)|false|none|

#### Enumerated Values

|Parameter|Value|
|---|---|
|format|csv|
|format|json|

> Example responses

> 200 Response

```json
{
  "id": 0,
  "name": "string",
  "distinct_ids": [
    "string"
  ],
  "properties": {
    "property1": null,
    "property2": null
  },
  "created_at": "2019-08-24T14:15:22Z",
  "uuid": "095be615-a8ad-4c33-8e9c-c7612fbf6c9f"
}
```

<h3 id="persons_update-responses">Responses</h3>

|Status|Meaning|Description|Schema|
|---|---|---|---|
|200|[OK](https://tools.ietf.org/html/rfc7231#section-6.3.1)|none|[Person](#schemaperson)|

<aside class="success">
This operation does not require authentication
</aside>

## persons_partial_update

<a id="opIdpersons_partial_update"></a>

> Code samples

```shell
# You can also use wget
curl -X PATCH /api/projects/{project_id}/persons/{id}/ \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json'

```

```http
PATCH /api/projects/{project_id}/persons/{id}/ HTTP/1.1

Content-Type: application/json
Accept: application/json

```

```javascript
const inputBody = '{
  "properties": {
    "property1": null,
    "property2": null
  }
}';
const headers = {
  'Content-Type':'application/json',
  'Accept':'application/json'
};

fetch('/api/projects/{project_id}/persons/{id}/',
{
  method: 'PATCH',
  body: inputBody,
  headers: headers
})
.then(function(res) {
    return res.json();
}).then(function(body) {
    console.log(body);
});

```

```ruby
require 'rest-client'
require 'json'

headers = {
  'Content-Type' => 'application/json',
  'Accept' => 'application/json'
}

result = RestClient.patch '/api/projects/{project_id}/persons/{id}/',
  params: {
  }, headers: headers

p JSON.parse(result)

```

```python
import requests
headers = {
  'Content-Type': 'application/json',
  'Accept': 'application/json'
}

r = requests.patch('/api/projects/{project_id}/persons/{id}/', headers = headers)

print(r.json())

```

```php
<?php

require 'vendor/autoload.php';

$headers = array(
    'Content-Type' => 'application/json',
    'Accept' => 'application/json',
);

$client = new \GuzzleHttp\Client();

// Define array of request body.
$request_body = array();

try {
    $response = $client->request('PATCH','/api/projects/{project_id}/persons/{id}/', array(
        'headers' => $headers,
        'json' => $request_body,
       )
    );
    print_r($response->getBody()->getContents());
 }
 catch (\GuzzleHttp\Exception\BadResponseException $e) {
    // handle exception or api errors.
    print_r($e->getMessage());
 }

 // ...

```

```java
URL obj = new URL("/api/projects/{project_id}/persons/{id}/");
HttpURLConnection con = (HttpURLConnection) obj.openConnection();
con.setRequestMethod("PATCH");
int responseCode = con.getResponseCode();
BufferedReader in = new BufferedReader(
    new InputStreamReader(con.getInputStream()));
String inputLine;
StringBuffer response = new StringBuffer();
while ((inputLine = in.readLine()) != null) {
    response.append(inputLine);
}
in.close();
System.out.println(response.toString());

```

```go
package main

import (
       "bytes"
       "net/http"
)

func main() {

    headers := map[string][]string{
        "Content-Type": []string{"application/json"},
        "Accept": []string{"application/json"},
    }

    data := bytes.NewBuffer([]byte{jsonReq})
    req, err := http.NewRequest("PATCH", "/api/projects/{project_id}/persons/{id}/", data)
    req.Header = headers

    client := &http.Client{}
    resp, err := client.Do(req)
    // ...
}

```

`PATCH /api/projects/{project_id}/persons/{id}/`

> Body parameter

```json
{
  "properties": {
    "property1": null,
    "property2": null
  }
}
```

```yaml
properties:
  ? property1
  ? property2

```

<h3 id="persons_partial_update-parameters">Parameters</h3>

|Name|In|Type|Required|Description|
|---|---|---|---|---|
|format|query|string|false|none|
|id|path|integer|true|A unique integer value identifying this person.|
|project_id|path|string|true|Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/.|
|body|body|[PatchedPerson](#schemapatchedperson)|false|none|

#### Enumerated Values

|Parameter|Value|
|---|---|
|format|csv|
|format|json|

> Example responses

> 200 Response

```json
{
  "id": 0,
  "name": "string",
  "distinct_ids": [
    "string"
  ],
  "properties": {
    "property1": null,
    "property2": null
  },
  "created_at": "2019-08-24T14:15:22Z",
  "uuid": "095be615-a8ad-4c33-8e9c-c7612fbf6c9f"
}
```

<h3 id="persons_partial_update-responses">Responses</h3>

|Status|Meaning|Description|Schema|
|---|---|---|---|
|200|[OK](https://tools.ietf.org/html/rfc7231#section-6.3.1)|none|[Person](#schemaperson)|

<aside class="success">
This operation does not require authentication
</aside>

## persons_destroy

<a id="opIdpersons_destroy"></a>

> Code samples

```shell
# You can also use wget
curl -X DELETE /api/projects/{project_id}/persons/{id}/

```

```http
DELETE /api/projects/{project_id}/persons/{id}/ HTTP/1.1

```

```javascript

fetch('/api/projects/{project_id}/persons/{id}/',
{
  method: 'DELETE'

})
.then(function(res) {
    return res.json();
}).then(function(body) {
    console.log(body);
});

```

```ruby
require 'rest-client'
require 'json'

result = RestClient.delete '/api/projects/{project_id}/persons/{id}/',
  params: {
  }

p JSON.parse(result)

```

```python
import requests

r = requests.delete('/api/projects/{project_id}/persons/{id}/')

print(r.json())

```

```php
<?php

require 'vendor/autoload.php';

$client = new \GuzzleHttp\Client();

// Define array of request body.
$request_body = array();

try {
    $response = $client->request('DELETE','/api/projects/{project_id}/persons/{id}/', array(
        'headers' => $headers,
        'json' => $request_body,
       )
    );
    print_r($response->getBody()->getContents());
 }
 catch (\GuzzleHttp\Exception\BadResponseException $e) {
    // handle exception or api errors.
    print_r($e->getMessage());
 }

 // ...

```

```java
URL obj = new URL("/api/projects/{project_id}/persons/{id}/");
HttpURLConnection con = (HttpURLConnection) obj.openConnection();
con.setRequestMethod("DELETE");
int responseCode = con.getResponseCode();
BufferedReader in = new BufferedReader(
    new InputStreamReader(con.getInputStream()));
String inputLine;
StringBuffer response = new StringBuffer();
while ((inputLine = in.readLine()) != null) {
    response.append(inputLine);
}
in.close();
System.out.println(response.toString());

```

```go
package main

import (
       "bytes"
       "net/http"
)

func main() {

    data := bytes.NewBuffer([]byte{jsonReq})
    req, err := http.NewRequest("DELETE", "/api/projects/{project_id}/persons/{id}/", data)
    req.Header = headers

    client := &http.Client{}
    resp, err := client.Do(req)
    // ...
}

```

`DELETE /api/projects/{project_id}/persons/{id}/`

<h3 id="persons_destroy-parameters">Parameters</h3>

|Name|In|Type|Required|Description|
|---|---|---|---|---|
|format|query|string|false|none|
|id|path|integer|true|A unique integer value identifying this person.|
|project_id|path|string|true|Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/.|

#### Enumerated Values

|Parameter|Value|
|---|---|
|format|csv|
|format|json|

<h3 id="persons_destroy-responses">Responses</h3>

|Status|Meaning|Description|Schema|
|---|---|---|---|
|204|[No Content](https://tools.ietf.org/html/rfc7231#section-6.3.5)|No response body|None|

<aside class="success">
This operation does not require authentication
</aside>

## persons_merge_create

<a id="opIdpersons_merge_create"></a>

> Code samples

```shell
# You can also use wget
curl -X POST /api/projects/{project_id}/persons/{id}/merge/ \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json'

```

```http
POST /api/projects/{project_id}/persons/{id}/merge/ HTTP/1.1

Content-Type: application/json
Accept: application/json

```

```javascript
const inputBody = '{
  "properties": {
    "property1": null,
    "property2": null
  }
}';
const headers = {
  'Content-Type':'application/json',
  'Accept':'application/json'
};

fetch('/api/projects/{project_id}/persons/{id}/merge/',
{
  method: 'POST',
  body: inputBody,
  headers: headers
})
.then(function(res) {
    return res.json();
}).then(function(body) {
    console.log(body);
});

```

```ruby
require 'rest-client'
require 'json'

headers = {
  'Content-Type' => 'application/json',
  'Accept' => 'application/json'
}

result = RestClient.post '/api/projects/{project_id}/persons/{id}/merge/',
  params: {
  }, headers: headers

p JSON.parse(result)

```

```python
import requests
headers = {
  'Content-Type': 'application/json',
  'Accept': 'application/json'
}

r = requests.post('/api/projects/{project_id}/persons/{id}/merge/', headers = headers)

print(r.json())

```

```php
<?php

require 'vendor/autoload.php';

$headers = array(
    'Content-Type' => 'application/json',
    'Accept' => 'application/json',
);

$client = new \GuzzleHttp\Client();

// Define array of request body.
$request_body = array();

try {
    $response = $client->request('POST','/api/projects/{project_id}/persons/{id}/merge/', array(
        'headers' => $headers,
        'json' => $request_body,
       )
    );
    print_r($response->getBody()->getContents());
 }
 catch (\GuzzleHttp\Exception\BadResponseException $e) {
    // handle exception or api errors.
    print_r($e->getMessage());
 }

 // ...

```

```java
URL obj = new URL("/api/projects/{project_id}/persons/{id}/merge/");
HttpURLConnection con = (HttpURLConnection) obj.openConnection();
con.setRequestMethod("POST");
int responseCode = con.getResponseCode();
BufferedReader in = new BufferedReader(
    new InputStreamReader(con.getInputStream()));
String inputLine;
StringBuffer response = new StringBuffer();
while ((inputLine = in.readLine()) != null) {
    response.append(inputLine);
}
in.close();
System.out.println(response.toString());

```

```go
package main

import (
       "bytes"
       "net/http"
)

func main() {

    headers := map[string][]string{
        "Content-Type": []string{"application/json"},
        "Accept": []string{"application/json"},
    }

    data := bytes.NewBuffer([]byte{jsonReq})
    req, err := http.NewRequest("POST", "/api/projects/{project_id}/persons/{id}/merge/", data)
    req.Header = headers

    client := &http.Client{}
    resp, err := client.Do(req)
    // ...
}

```

`POST /api/projects/{project_id}/persons/{id}/merge/`

> Body parameter

```json
{
  "properties": {
    "property1": null,
    "property2": null
  }
}
```

```yaml
properties:
  ? property1
  ? property2

```

<h3 id="persons_merge_create-parameters">Parameters</h3>

|Name|In|Type|Required|Description|
|---|---|---|---|---|
|format|query|string|false|none|
|id|path|integer|true|A unique integer value identifying this person.|
|project_id|path|string|true|Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/.|
|body|body|[Person](#schemaperson)|false|none|

#### Enumerated Values

|Parameter|Value|
|---|---|
|format|csv|
|format|json|

> Example responses

> 200 Response

```json
{
  "id": 0,
  "name": "string",
  "distinct_ids": [
    "string"
  ],
  "properties": {
    "property1": null,
    "property2": null
  },
  "created_at": "2019-08-24T14:15:22Z",
  "uuid": "095be615-a8ad-4c33-8e9c-c7612fbf6c9f"
}
```

<h3 id="persons_merge_create-responses">Responses</h3>

|Status|Meaning|Description|Schema|
|---|---|---|---|
|200|[OK](https://tools.ietf.org/html/rfc7231#section-6.3.1)|none|[Person](#schemaperson)|

<aside class="success">
This operation does not require authentication
</aside>

## persons_split_create

<a id="opIdpersons_split_create"></a>

> Code samples

```shell
# You can also use wget
curl -X POST /api/projects/{project_id}/persons/{id}/split/ \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json'

```

```http
POST /api/projects/{project_id}/persons/{id}/split/ HTTP/1.1

Content-Type: application/json
Accept: application/json

```

```javascript
const inputBody = '{
  "properties": {
    "property1": null,
    "property2": null
  }
}';
const headers = {
  'Content-Type':'application/json',
  'Accept':'application/json'
};

fetch('/api/projects/{project_id}/persons/{id}/split/',
{
  method: 'POST',
  body: inputBody,
  headers: headers
})
.then(function(res) {
    return res.json();
}).then(function(body) {
    console.log(body);
});

```

```ruby
require 'rest-client'
require 'json'

headers = {
  'Content-Type' => 'application/json',
  'Accept' => 'application/json'
}

result = RestClient.post '/api/projects/{project_id}/persons/{id}/split/',
  params: {
  }, headers: headers

p JSON.parse(result)

```

```python
import requests
headers = {
  'Content-Type': 'application/json',
  'Accept': 'application/json'
}

r = requests.post('/api/projects/{project_id}/persons/{id}/split/', headers = headers)

print(r.json())

```

```php
<?php

require 'vendor/autoload.php';

$headers = array(
    'Content-Type' => 'application/json',
    'Accept' => 'application/json',
);

$client = new \GuzzleHttp\Client();

// Define array of request body.
$request_body = array();

try {
    $response = $client->request('POST','/api/projects/{project_id}/persons/{id}/split/', array(
        'headers' => $headers,
        'json' => $request_body,
       )
    );
    print_r($response->getBody()->getContents());
 }
 catch (\GuzzleHttp\Exception\BadResponseException $e) {
    // handle exception or api errors.
    print_r($e->getMessage());
 }

 // ...

```

```java
URL obj = new URL("/api/projects/{project_id}/persons/{id}/split/");
HttpURLConnection con = (HttpURLConnection) obj.openConnection();
con.setRequestMethod("POST");
int responseCode = con.getResponseCode();
BufferedReader in = new BufferedReader(
    new InputStreamReader(con.getInputStream()));
String inputLine;
StringBuffer response = new StringBuffer();
while ((inputLine = in.readLine()) != null) {
    response.append(inputLine);
}
in.close();
System.out.println(response.toString());

```

```go
package main

import (
       "bytes"
       "net/http"
)

func main() {

    headers := map[string][]string{
        "Content-Type": []string{"application/json"},
        "Accept": []string{"application/json"},
    }

    data := bytes.NewBuffer([]byte{jsonReq})
    req, err := http.NewRequest("POST", "/api/projects/{project_id}/persons/{id}/split/", data)
    req.Header = headers

    client := &http.Client{}
    resp, err := client.Do(req)
    // ...
}

```

`POST /api/projects/{project_id}/persons/{id}/split/`

> Body parameter

```json
{
  "properties": {
    "property1": null,
    "property2": null
  }
}
```

```yaml
properties:
  ? property1
  ? property2

```

<h3 id="persons_split_create-parameters">Parameters</h3>

|Name|In|Type|Required|Description|
|---|---|---|---|---|
|format|query|string|false|none|
|id|path|integer|true|A unique integer value identifying this person.|
|project_id|path|string|true|Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/.|
|body|body|[Person](#schemaperson)|false|none|

#### Enumerated Values

|Parameter|Value|
|---|---|
|format|csv|
|format|json|

> Example responses

> 200 Response

```json
{
  "id": 0,
  "name": "string",
  "distinct_ids": [
    "string"
  ],
  "properties": {
    "property1": null,
    "property2": null
  },
  "created_at": "2019-08-24T14:15:22Z",
  "uuid": "095be615-a8ad-4c33-8e9c-c7612fbf6c9f"
}
```

<h3 id="persons_split_create-responses">Responses</h3>

|Status|Meaning|Description|Schema|
|---|---|---|---|
|200|[OK](https://tools.ietf.org/html/rfc7231#section-6.3.1)|none|[Person](#schemaperson)|

<aside class="success">
This operation does not require authentication
</aside>

## persons_cohorts_retrieve

<a id="opIdpersons_cohorts_retrieve"></a>

> Code samples

```shell
# You can also use wget
curl -X GET /api/projects/{project_id}/persons/cohorts/ \
  -H 'Accept: application/json'

```

```http
GET /api/projects/{project_id}/persons/cohorts/ HTTP/1.1

Accept: application/json

```

```javascript

const headers = {
  'Accept':'application/json'
};

fetch('/api/projects/{project_id}/persons/cohorts/',
{
  method: 'GET',

  headers: headers
})
.then(function(res) {
    return res.json();
}).then(function(body) {
    console.log(body);
});

```

```ruby
require 'rest-client'
require 'json'

headers = {
  'Accept' => 'application/json'
}

result = RestClient.get '/api/projects/{project_id}/persons/cohorts/',
  params: {
  }, headers: headers

p JSON.parse(result)

```

```python
import requests
headers = {
  'Accept': 'application/json'
}

r = requests.get('/api/projects/{project_id}/persons/cohorts/', headers = headers)

print(r.json())

```

```php
<?php

require 'vendor/autoload.php';

$headers = array(
    'Accept' => 'application/json',
);

$client = new \GuzzleHttp\Client();

// Define array of request body.
$request_body = array();

try {
    $response = $client->request('GET','/api/projects/{project_id}/persons/cohorts/', array(
        'headers' => $headers,
        'json' => $request_body,
       )
    );
    print_r($response->getBody()->getContents());
 }
 catch (\GuzzleHttp\Exception\BadResponseException $e) {
    // handle exception or api errors.
    print_r($e->getMessage());
 }

 // ...

```

```java
URL obj = new URL("/api/projects/{project_id}/persons/cohorts/");
HttpURLConnection con = (HttpURLConnection) obj.openConnection();
con.setRequestMethod("GET");
int responseCode = con.getResponseCode();
BufferedReader in = new BufferedReader(
    new InputStreamReader(con.getInputStream()));
String inputLine;
StringBuffer response = new StringBuffer();
while ((inputLine = in.readLine()) != null) {
    response.append(inputLine);
}
in.close();
System.out.println(response.toString());

```

```go
package main

import (
       "bytes"
       "net/http"
)

func main() {

    headers := map[string][]string{
        "Accept": []string{"application/json"},
    }

    data := bytes.NewBuffer([]byte{jsonReq})
    req, err := http.NewRequest("GET", "/api/projects/{project_id}/persons/cohorts/", data)
    req.Header = headers

    client := &http.Client{}
    resp, err := client.Do(req)
    // ...
}

```

`GET /api/projects/{project_id}/persons/cohorts/`

<h3 id="persons_cohorts_retrieve-parameters">Parameters</h3>

|Name|In|Type|Required|Description|
|---|---|---|---|---|
|format|query|string|false|none|
|project_id|path|string|true|Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/.|

#### Enumerated Values

|Parameter|Value|
|---|---|
|format|csv|
|format|json|

> Example responses

> 200 Response

```json
{
  "id": 0,
  "name": "string",
  "distinct_ids": [
    "string"
  ],
  "properties": {
    "property1": null,
    "property2": null
  },
  "created_at": "2019-08-24T14:15:22Z",
  "uuid": "095be615-a8ad-4c33-8e9c-c7612fbf6c9f"
}
```

<h3 id="persons_cohorts_retrieve-responses">Responses</h3>

|Status|Meaning|Description|Schema|
|---|---|---|---|
|200|[OK](https://tools.ietf.org/html/rfc7231#section-6.3.1)|none|[Person](#schemaperson)|

<aside class="success">
This operation does not require authentication
</aside>

## persons_funnel_retrieve

<a id="opIdpersons_funnel_retrieve"></a>

> Code samples

```shell
# You can also use wget
curl -X GET /api/projects/{project_id}/persons/funnel/ \
  -H 'Accept: application/json'

```

```http
GET /api/projects/{project_id}/persons/funnel/ HTTP/1.1

Accept: application/json

```

```javascript

const headers = {
  'Accept':'application/json'
};

fetch('/api/projects/{project_id}/persons/funnel/',
{
  method: 'GET',

  headers: headers
})
.then(function(res) {
    return res.json();
}).then(function(body) {
    console.log(body);
});

```

```ruby
require 'rest-client'
require 'json'

headers = {
  'Accept' => 'application/json'
}

result = RestClient.get '/api/projects/{project_id}/persons/funnel/',
  params: {
  }, headers: headers

p JSON.parse(result)

```

```python
import requests
headers = {
  'Accept': 'application/json'
}

r = requests.get('/api/projects/{project_id}/persons/funnel/', headers = headers)

print(r.json())

```

```php
<?php

require 'vendor/autoload.php';

$headers = array(
    'Accept' => 'application/json',
);

$client = new \GuzzleHttp\Client();

// Define array of request body.
$request_body = array();

try {
    $response = $client->request('GET','/api/projects/{project_id}/persons/funnel/', array(
        'headers' => $headers,
        'json' => $request_body,
       )
    );
    print_r($response->getBody()->getContents());
 }
 catch (\GuzzleHttp\Exception\BadResponseException $e) {
    // handle exception or api errors.
    print_r($e->getMessage());
 }

 // ...

```

```java
URL obj = new URL("/api/projects/{project_id}/persons/funnel/");
HttpURLConnection con = (HttpURLConnection) obj.openConnection();
con.setRequestMethod("GET");
int responseCode = con.getResponseCode();
BufferedReader in = new BufferedReader(
    new InputStreamReader(con.getInputStream()));
String inputLine;
StringBuffer response = new StringBuffer();
while ((inputLine = in.readLine()) != null) {
    response.append(inputLine);
}
in.close();
System.out.println(response.toString());

```

```go
package main

import (
       "bytes"
       "net/http"
)

func main() {

    headers := map[string][]string{
        "Accept": []string{"application/json"},
    }

    data := bytes.NewBuffer([]byte{jsonReq})
    req, err := http.NewRequest("GET", "/api/projects/{project_id}/persons/funnel/", data)
    req.Header = headers

    client := &http.Client{}
    resp, err := client.Do(req)
    // ...
}

```

`GET /api/projects/{project_id}/persons/funnel/`

<h3 id="persons_funnel_retrieve-parameters">Parameters</h3>

|Name|In|Type|Required|Description|
|---|---|---|---|---|
|format|query|string|false|none|
|project_id|path|string|true|Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/.|

#### Enumerated Values

|Parameter|Value|
|---|---|
|format|csv|
|format|json|

> Example responses

> 200 Response

```json
{
  "id": 0,
  "name": "string",
  "distinct_ids": [
    "string"
  ],
  "properties": {
    "property1": null,
    "property2": null
  },
  "created_at": "2019-08-24T14:15:22Z",
  "uuid": "095be615-a8ad-4c33-8e9c-c7612fbf6c9f"
}
```

<h3 id="persons_funnel_retrieve-responses">Responses</h3>

|Status|Meaning|Description|Schema|
|---|---|---|---|
|200|[OK](https://tools.ietf.org/html/rfc7231#section-6.3.1)|none|[Person](#schemaperson)|

<aside class="success">
This operation does not require authentication
</aside>

## persons_funnel_create

<a id="opIdpersons_funnel_create"></a>

> Code samples

```shell
# You can also use wget
curl -X POST /api/projects/{project_id}/persons/funnel/ \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json'

```

```http
POST /api/projects/{project_id}/persons/funnel/ HTTP/1.1

Content-Type: application/json
Accept: application/json

```

```javascript
const inputBody = '{
  "properties": {
    "property1": null,
    "property2": null
  }
}';
const headers = {
  'Content-Type':'application/json',
  'Accept':'application/json'
};

fetch('/api/projects/{project_id}/persons/funnel/',
{
  method: 'POST',
  body: inputBody,
  headers: headers
})
.then(function(res) {
    return res.json();
}).then(function(body) {
    console.log(body);
});

```

```ruby
require 'rest-client'
require 'json'

headers = {
  'Content-Type' => 'application/json',
  'Accept' => 'application/json'
}

result = RestClient.post '/api/projects/{project_id}/persons/funnel/',
  params: {
  }, headers: headers

p JSON.parse(result)

```

```python
import requests
headers = {
  'Content-Type': 'application/json',
  'Accept': 'application/json'
}

r = requests.post('/api/projects/{project_id}/persons/funnel/', headers = headers)

print(r.json())

```

```php
<?php

require 'vendor/autoload.php';

$headers = array(
    'Content-Type' => 'application/json',
    'Accept' => 'application/json',
);

$client = new \GuzzleHttp\Client();

// Define array of request body.
$request_body = array();

try {
    $response = $client->request('POST','/api/projects/{project_id}/persons/funnel/', array(
        'headers' => $headers,
        'json' => $request_body,
       )
    );
    print_r($response->getBody()->getContents());
 }
 catch (\GuzzleHttp\Exception\BadResponseException $e) {
    // handle exception or api errors.
    print_r($e->getMessage());
 }

 // ...

```

```java
URL obj = new URL("/api/projects/{project_id}/persons/funnel/");
HttpURLConnection con = (HttpURLConnection) obj.openConnection();
con.setRequestMethod("POST");
int responseCode = con.getResponseCode();
BufferedReader in = new BufferedReader(
    new InputStreamReader(con.getInputStream()));
String inputLine;
StringBuffer response = new StringBuffer();
while ((inputLine = in.readLine()) != null) {
    response.append(inputLine);
}
in.close();
System.out.println(response.toString());

```

```go
package main

import (
       "bytes"
       "net/http"
)

func main() {

    headers := map[string][]string{
        "Content-Type": []string{"application/json"},
        "Accept": []string{"application/json"},
    }

    data := bytes.NewBuffer([]byte{jsonReq})
    req, err := http.NewRequest("POST", "/api/projects/{project_id}/persons/funnel/", data)
    req.Header = headers

    client := &http.Client{}
    resp, err := client.Do(req)
    // ...
}

```

`POST /api/projects/{project_id}/persons/funnel/`

> Body parameter

```json
{
  "properties": {
    "property1": null,
    "property2": null
  }
}
```

```yaml
properties:
  ? property1
  ? property2

```

<h3 id="persons_funnel_create-parameters">Parameters</h3>

|Name|In|Type|Required|Description|
|---|---|---|---|---|
|format|query|string|false|none|
|project_id|path|string|true|Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/.|
|body|body|[Person](#schemaperson)|false|none|

#### Enumerated Values

|Parameter|Value|
|---|---|
|format|csv|
|format|json|

> Example responses

> 200 Response

```json
{
  "id": 0,
  "name": "string",
  "distinct_ids": [
    "string"
  ],
  "properties": {
    "property1": null,
    "property2": null
  },
  "created_at": "2019-08-24T14:15:22Z",
  "uuid": "095be615-a8ad-4c33-8e9c-c7612fbf6c9f"
}
```

<h3 id="persons_funnel_create-responses">Responses</h3>

|Status|Meaning|Description|Schema|
|---|---|---|---|
|200|[OK](https://tools.ietf.org/html/rfc7231#section-6.3.1)|none|[Person](#schemaperson)|

<aside class="success">
This operation does not require authentication
</aside>

## persons_funnel_correlation_retrieve

<a id="opIdpersons_funnel_correlation_retrieve"></a>

> Code samples

```shell
# You can also use wget
curl -X GET /api/projects/{project_id}/persons/funnel/correlation/ \
  -H 'Accept: application/json'

```

```http
GET /api/projects/{project_id}/persons/funnel/correlation/ HTTP/1.1

Accept: application/json

```

```javascript

const headers = {
  'Accept':'application/json'
};

fetch('/api/projects/{project_id}/persons/funnel/correlation/',
{
  method: 'GET',

  headers: headers
})
.then(function(res) {
    return res.json();
}).then(function(body) {
    console.log(body);
});

```

```ruby
require 'rest-client'
require 'json'

headers = {
  'Accept' => 'application/json'
}

result = RestClient.get '/api/projects/{project_id}/persons/funnel/correlation/',
  params: {
  }, headers: headers

p JSON.parse(result)

```

```python
import requests
headers = {
  'Accept': 'application/json'
}

r = requests.get('/api/projects/{project_id}/persons/funnel/correlation/', headers = headers)

print(r.json())

```

```php
<?php

require 'vendor/autoload.php';

$headers = array(
    'Accept' => 'application/json',
);

$client = new \GuzzleHttp\Client();

// Define array of request body.
$request_body = array();

try {
    $response = $client->request('GET','/api/projects/{project_id}/persons/funnel/correlation/', array(
        'headers' => $headers,
        'json' => $request_body,
       )
    );
    print_r($response->getBody()->getContents());
 }
 catch (\GuzzleHttp\Exception\BadResponseException $e) {
    // handle exception or api errors.
    print_r($e->getMessage());
 }

 // ...

```

```java
URL obj = new URL("/api/projects/{project_id}/persons/funnel/correlation/");
HttpURLConnection con = (HttpURLConnection) obj.openConnection();
con.setRequestMethod("GET");
int responseCode = con.getResponseCode();
BufferedReader in = new BufferedReader(
    new InputStreamReader(con.getInputStream()));
String inputLine;
StringBuffer response = new StringBuffer();
while ((inputLine = in.readLine()) != null) {
    response.append(inputLine);
}
in.close();
System.out.println(response.toString());

```

```go
package main

import (
       "bytes"
       "net/http"
)

func main() {

    headers := map[string][]string{
        "Accept": []string{"application/json"},
    }

    data := bytes.NewBuffer([]byte{jsonReq})
    req, err := http.NewRequest("GET", "/api/projects/{project_id}/persons/funnel/correlation/", data)
    req.Header = headers

    client := &http.Client{}
    resp, err := client.Do(req)
    // ...
}

```

`GET /api/projects/{project_id}/persons/funnel/correlation/`

<h3 id="persons_funnel_correlation_retrieve-parameters">Parameters</h3>

|Name|In|Type|Required|Description|
|---|---|---|---|---|
|format|query|string|false|none|
|project_id|path|string|true|Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/.|

#### Enumerated Values

|Parameter|Value|
|---|---|
|format|csv|
|format|json|

> Example responses

> 200 Response

```json
{
  "id": 0,
  "name": "string",
  "distinct_ids": [
    "string"
  ],
  "properties": {
    "property1": null,
    "property2": null
  },
  "created_at": "2019-08-24T14:15:22Z",
  "uuid": "095be615-a8ad-4c33-8e9c-c7612fbf6c9f"
}
```

<h3 id="persons_funnel_correlation_retrieve-responses">Responses</h3>

|Status|Meaning|Description|Schema|
|---|---|---|---|
|200|[OK](https://tools.ietf.org/html/rfc7231#section-6.3.1)|none|[Person](#schemaperson)|

<aside class="success">
This operation does not require authentication
</aside>

## persons_funnel_correlation_create

<a id="opIdpersons_funnel_correlation_create"></a>

> Code samples

```shell
# You can also use wget
curl -X POST /api/projects/{project_id}/persons/funnel/correlation/ \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json'

```

```http
POST /api/projects/{project_id}/persons/funnel/correlation/ HTTP/1.1

Content-Type: application/json
Accept: application/json

```

```javascript
const inputBody = '{
  "properties": {
    "property1": null,
    "property2": null
  }
}';
const headers = {
  'Content-Type':'application/json',
  'Accept':'application/json'
};

fetch('/api/projects/{project_id}/persons/funnel/correlation/',
{
  method: 'POST',
  body: inputBody,
  headers: headers
})
.then(function(res) {
    return res.json();
}).then(function(body) {
    console.log(body);
});

```

```ruby
require 'rest-client'
require 'json'

headers = {
  'Content-Type' => 'application/json',
  'Accept' => 'application/json'
}

result = RestClient.post '/api/projects/{project_id}/persons/funnel/correlation/',
  params: {
  }, headers: headers

p JSON.parse(result)

```

```python
import requests
headers = {
  'Content-Type': 'application/json',
  'Accept': 'application/json'
}

r = requests.post('/api/projects/{project_id}/persons/funnel/correlation/', headers = headers)

print(r.json())

```

```php
<?php

require 'vendor/autoload.php';

$headers = array(
    'Content-Type' => 'application/json',
    'Accept' => 'application/json',
);

$client = new \GuzzleHttp\Client();

// Define array of request body.
$request_body = array();

try {
    $response = $client->request('POST','/api/projects/{project_id}/persons/funnel/correlation/', array(
        'headers' => $headers,
        'json' => $request_body,
       )
    );
    print_r($response->getBody()->getContents());
 }
 catch (\GuzzleHttp\Exception\BadResponseException $e) {
    // handle exception or api errors.
    print_r($e->getMessage());
 }

 // ...

```

```java
URL obj = new URL("/api/projects/{project_id}/persons/funnel/correlation/");
HttpURLConnection con = (HttpURLConnection) obj.openConnection();
con.setRequestMethod("POST");
int responseCode = con.getResponseCode();
BufferedReader in = new BufferedReader(
    new InputStreamReader(con.getInputStream()));
String inputLine;
StringBuffer response = new StringBuffer();
while ((inputLine = in.readLine()) != null) {
    response.append(inputLine);
}
in.close();
System.out.println(response.toString());

```

```go
package main

import (
       "bytes"
       "net/http"
)

func main() {

    headers := map[string][]string{
        "Content-Type": []string{"application/json"},
        "Accept": []string{"application/json"},
    }

    data := bytes.NewBuffer([]byte{jsonReq})
    req, err := http.NewRequest("POST", "/api/projects/{project_id}/persons/funnel/correlation/", data)
    req.Header = headers

    client := &http.Client{}
    resp, err := client.Do(req)
    // ...
}

```

`POST /api/projects/{project_id}/persons/funnel/correlation/`

> Body parameter

```json
{
  "properties": {
    "property1": null,
    "property2": null
  }
}
```

```yaml
properties:
  ? property1
  ? property2

```

<h3 id="persons_funnel_correlation_create-parameters">Parameters</h3>

|Name|In|Type|Required|Description|
|---|---|---|---|---|
|format|query|string|false|none|
|project_id|path|string|true|Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/.|
|body|body|[Person](#schemaperson)|false|none|

#### Enumerated Values

|Parameter|Value|
|---|---|
|format|csv|
|format|json|

> Example responses

> 200 Response

```json
{
  "id": 0,
  "name": "string",
  "distinct_ids": [
    "string"
  ],
  "properties": {
    "property1": null,
    "property2": null
  },
  "created_at": "2019-08-24T14:15:22Z",
  "uuid": "095be615-a8ad-4c33-8e9c-c7612fbf6c9f"
}
```

<h3 id="persons_funnel_correlation_create-responses">Responses</h3>

|Status|Meaning|Description|Schema|
|---|---|---|---|
|200|[OK](https://tools.ietf.org/html/rfc7231#section-6.3.1)|none|[Person](#schemaperson)|

<aside class="success">
This operation does not require authentication
</aside>

## persons_lifecycle_retrieve

<a id="opIdpersons_lifecycle_retrieve"></a>

> Code samples

```shell
# You can also use wget
curl -X GET /api/projects/{project_id}/persons/lifecycle/ \
  -H 'Accept: application/json'

```

```http
GET /api/projects/{project_id}/persons/lifecycle/ HTTP/1.1

Accept: application/json

```

```javascript

const headers = {
  'Accept':'application/json'
};

fetch('/api/projects/{project_id}/persons/lifecycle/',
{
  method: 'GET',

  headers: headers
})
.then(function(res) {
    return res.json();
}).then(function(body) {
    console.log(body);
});

```

```ruby
require 'rest-client'
require 'json'

headers = {
  'Accept' => 'application/json'
}

result = RestClient.get '/api/projects/{project_id}/persons/lifecycle/',
  params: {
  }, headers: headers

p JSON.parse(result)

```

```python
import requests
headers = {
  'Accept': 'application/json'
}

r = requests.get('/api/projects/{project_id}/persons/lifecycle/', headers = headers)

print(r.json())

```

```php
<?php

require 'vendor/autoload.php';

$headers = array(
    'Accept' => 'application/json',
);

$client = new \GuzzleHttp\Client();

// Define array of request body.
$request_body = array();

try {
    $response = $client->request('GET','/api/projects/{project_id}/persons/lifecycle/', array(
        'headers' => $headers,
        'json' => $request_body,
       )
    );
    print_r($response->getBody()->getContents());
 }
 catch (\GuzzleHttp\Exception\BadResponseException $e) {
    // handle exception or api errors.
    print_r($e->getMessage());
 }

 // ...

```

```java
URL obj = new URL("/api/projects/{project_id}/persons/lifecycle/");
HttpURLConnection con = (HttpURLConnection) obj.openConnection();
con.setRequestMethod("GET");
int responseCode = con.getResponseCode();
BufferedReader in = new BufferedReader(
    new InputStreamReader(con.getInputStream()));
String inputLine;
StringBuffer response = new StringBuffer();
while ((inputLine = in.readLine()) != null) {
    response.append(inputLine);
}
in.close();
System.out.println(response.toString());

```

```go
package main

import (
       "bytes"
       "net/http"
)

func main() {

    headers := map[string][]string{
        "Accept": []string{"application/json"},
    }

    data := bytes.NewBuffer([]byte{jsonReq})
    req, err := http.NewRequest("GET", "/api/projects/{project_id}/persons/lifecycle/", data)
    req.Header = headers

    client := &http.Client{}
    resp, err := client.Do(req)
    // ...
}

```

`GET /api/projects/{project_id}/persons/lifecycle/`

<h3 id="persons_lifecycle_retrieve-parameters">Parameters</h3>

|Name|In|Type|Required|Description|
|---|---|---|---|---|
|format|query|string|false|none|
|project_id|path|string|true|Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/.|

#### Enumerated Values

|Parameter|Value|
|---|---|
|format|csv|
|format|json|

> Example responses

> 200 Response

```json
{
  "id": 0,
  "name": "string",
  "distinct_ids": [
    "string"
  ],
  "properties": {
    "property1": null,
    "property2": null
  },
  "created_at": "2019-08-24T14:15:22Z",
  "uuid": "095be615-a8ad-4c33-8e9c-c7612fbf6c9f"
}
```

<h3 id="persons_lifecycle_retrieve-responses">Responses</h3>

|Status|Meaning|Description|Schema|
|---|---|---|---|
|200|[OK](https://tools.ietf.org/html/rfc7231#section-6.3.1)|none|[Person](#schemaperson)|

<aside class="success">
This operation does not require authentication
</aside>

## persons_path_retrieve

<a id="opIdpersons_path_retrieve"></a>

> Code samples

```shell
# You can also use wget
curl -X GET /api/projects/{project_id}/persons/path/ \
  -H 'Accept: application/json'

```

```http
GET /api/projects/{project_id}/persons/path/ HTTP/1.1

Accept: application/json

```

```javascript

const headers = {
  'Accept':'application/json'
};

fetch('/api/projects/{project_id}/persons/path/',
{
  method: 'GET',

  headers: headers
})
.then(function(res) {
    return res.json();
}).then(function(body) {
    console.log(body);
});

```

```ruby
require 'rest-client'
require 'json'

headers = {
  'Accept' => 'application/json'
}

result = RestClient.get '/api/projects/{project_id}/persons/path/',
  params: {
  }, headers: headers

p JSON.parse(result)

```

```python
import requests
headers = {
  'Accept': 'application/json'
}

r = requests.get('/api/projects/{project_id}/persons/path/', headers = headers)

print(r.json())

```

```php
<?php

require 'vendor/autoload.php';

$headers = array(
    'Accept' => 'application/json',
);

$client = new \GuzzleHttp\Client();

// Define array of request body.
$request_body = array();

try {
    $response = $client->request('GET','/api/projects/{project_id}/persons/path/', array(
        'headers' => $headers,
        'json' => $request_body,
       )
    );
    print_r($response->getBody()->getContents());
 }
 catch (\GuzzleHttp\Exception\BadResponseException $e) {
    // handle exception or api errors.
    print_r($e->getMessage());
 }

 // ...

```

```java
URL obj = new URL("/api/projects/{project_id}/persons/path/");
HttpURLConnection con = (HttpURLConnection) obj.openConnection();
con.setRequestMethod("GET");
int responseCode = con.getResponseCode();
BufferedReader in = new BufferedReader(
    new InputStreamReader(con.getInputStream()));
String inputLine;
StringBuffer response = new StringBuffer();
while ((inputLine = in.readLine()) != null) {
    response.append(inputLine);
}
in.close();
System.out.println(response.toString());

```

```go
package main

import (
       "bytes"
       "net/http"
)

func main() {

    headers := map[string][]string{
        "Accept": []string{"application/json"},
    }

    data := bytes.NewBuffer([]byte{jsonReq})
    req, err := http.NewRequest("GET", "/api/projects/{project_id}/persons/path/", data)
    req.Header = headers

    client := &http.Client{}
    resp, err := client.Do(req)
    // ...
}

```

`GET /api/projects/{project_id}/persons/path/`

<h3 id="persons_path_retrieve-parameters">Parameters</h3>

|Name|In|Type|Required|Description|
|---|---|---|---|---|
|format|query|string|false|none|
|project_id|path|string|true|Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/.|

#### Enumerated Values

|Parameter|Value|
|---|---|
|format|csv|
|format|json|

> Example responses

> 200 Response

```json
{
  "id": 0,
  "name": "string",
  "distinct_ids": [
    "string"
  ],
  "properties": {
    "property1": null,
    "property2": null
  },
  "created_at": "2019-08-24T14:15:22Z",
  "uuid": "095be615-a8ad-4c33-8e9c-c7612fbf6c9f"
}
```

<h3 id="persons_path_retrieve-responses">Responses</h3>

|Status|Meaning|Description|Schema|
|---|---|---|---|
|200|[OK](https://tools.ietf.org/html/rfc7231#section-6.3.1)|none|[Person](#schemaperson)|

<aside class="success">
This operation does not require authentication
</aside>

## persons_path_create

<a id="opIdpersons_path_create"></a>

> Code samples

```shell
# You can also use wget
curl -X POST /api/projects/{project_id}/persons/path/ \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json'

```

```http
POST /api/projects/{project_id}/persons/path/ HTTP/1.1

Content-Type: application/json
Accept: application/json

```

```javascript
const inputBody = '{
  "properties": {
    "property1": null,
    "property2": null
  }
}';
const headers = {
  'Content-Type':'application/json',
  'Accept':'application/json'
};

fetch('/api/projects/{project_id}/persons/path/',
{
  method: 'POST',
  body: inputBody,
  headers: headers
})
.then(function(res) {
    return res.json();
}).then(function(body) {
    console.log(body);
});

```

```ruby
require 'rest-client'
require 'json'

headers = {
  'Content-Type' => 'application/json',
  'Accept' => 'application/json'
}

result = RestClient.post '/api/projects/{project_id}/persons/path/',
  params: {
  }, headers: headers

p JSON.parse(result)

```

```python
import requests
headers = {
  'Content-Type': 'application/json',
  'Accept': 'application/json'
}

r = requests.post('/api/projects/{project_id}/persons/path/', headers = headers)

print(r.json())

```

```php
<?php

require 'vendor/autoload.php';

$headers = array(
    'Content-Type' => 'application/json',
    'Accept' => 'application/json',
);

$client = new \GuzzleHttp\Client();

// Define array of request body.
$request_body = array();

try {
    $response = $client->request('POST','/api/projects/{project_id}/persons/path/', array(
        'headers' => $headers,
        'json' => $request_body,
       )
    );
    print_r($response->getBody()->getContents());
 }
 catch (\GuzzleHttp\Exception\BadResponseException $e) {
    // handle exception or api errors.
    print_r($e->getMessage());
 }

 // ...

```

```java
URL obj = new URL("/api/projects/{project_id}/persons/path/");
HttpURLConnection con = (HttpURLConnection) obj.openConnection();
con.setRequestMethod("POST");
int responseCode = con.getResponseCode();
BufferedReader in = new BufferedReader(
    new InputStreamReader(con.getInputStream()));
String inputLine;
StringBuffer response = new StringBuffer();
while ((inputLine = in.readLine()) != null) {
    response.append(inputLine);
}
in.close();
System.out.println(response.toString());

```

```go
package main

import (
       "bytes"
       "net/http"
)

func main() {

    headers := map[string][]string{
        "Content-Type": []string{"application/json"},
        "Accept": []string{"application/json"},
    }

    data := bytes.NewBuffer([]byte{jsonReq})
    req, err := http.NewRequest("POST", "/api/projects/{project_id}/persons/path/", data)
    req.Header = headers

    client := &http.Client{}
    resp, err := client.Do(req)
    // ...
}

```

`POST /api/projects/{project_id}/persons/path/`

> Body parameter

```json
{
  "properties": {
    "property1": null,
    "property2": null
  }
}
```

```yaml
properties:
  ? property1
  ? property2

```

<h3 id="persons_path_create-parameters">Parameters</h3>

|Name|In|Type|Required|Description|
|---|---|---|---|---|
|format|query|string|false|none|
|project_id|path|string|true|Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/.|
|body|body|[Person](#schemaperson)|false|none|

#### Enumerated Values

|Parameter|Value|
|---|---|
|format|csv|
|format|json|

> Example responses

> 200 Response

```json
{
  "id": 0,
  "name": "string",
  "distinct_ids": [
    "string"
  ],
  "properties": {
    "property1": null,
    "property2": null
  },
  "created_at": "2019-08-24T14:15:22Z",
  "uuid": "095be615-a8ad-4c33-8e9c-c7612fbf6c9f"
}
```

<h3 id="persons_path_create-responses">Responses</h3>

|Status|Meaning|Description|Schema|
|---|---|---|---|
|200|[OK](https://tools.ietf.org/html/rfc7231#section-6.3.1)|none|[Person](#schemaperson)|

<aside class="success">
This operation does not require authentication
</aside>

## persons_properties_retrieve

<a id="opIdpersons_properties_retrieve"></a>

> Code samples

```shell
# You can also use wget
curl -X GET /api/projects/{project_id}/persons/properties/ \
  -H 'Accept: application/json'

```

```http
GET /api/projects/{project_id}/persons/properties/ HTTP/1.1

Accept: application/json

```

```javascript

const headers = {
  'Accept':'application/json'
};

fetch('/api/projects/{project_id}/persons/properties/',
{
  method: 'GET',

  headers: headers
})
.then(function(res) {
    return res.json();
}).then(function(body) {
    console.log(body);
});

```

```ruby
require 'rest-client'
require 'json'

headers = {
  'Accept' => 'application/json'
}

result = RestClient.get '/api/projects/{project_id}/persons/properties/',
  params: {
  }, headers: headers

p JSON.parse(result)

```

```python
import requests
headers = {
  'Accept': 'application/json'
}

r = requests.get('/api/projects/{project_id}/persons/properties/', headers = headers)

print(r.json())

```

```php
<?php

require 'vendor/autoload.php';

$headers = array(
    'Accept' => 'application/json',
);

$client = new \GuzzleHttp\Client();

// Define array of request body.
$request_body = array();

try {
    $response = $client->request('GET','/api/projects/{project_id}/persons/properties/', array(
        'headers' => $headers,
        'json' => $request_body,
       )
    );
    print_r($response->getBody()->getContents());
 }
 catch (\GuzzleHttp\Exception\BadResponseException $e) {
    // handle exception or api errors.
    print_r($e->getMessage());
 }

 // ...

```

```java
URL obj = new URL("/api/projects/{project_id}/persons/properties/");
HttpURLConnection con = (HttpURLConnection) obj.openConnection();
con.setRequestMethod("GET");
int responseCode = con.getResponseCode();
BufferedReader in = new BufferedReader(
    new InputStreamReader(con.getInputStream()));
String inputLine;
StringBuffer response = new StringBuffer();
while ((inputLine = in.readLine()) != null) {
    response.append(inputLine);
}
in.close();
System.out.println(response.toString());

```

```go
package main

import (
       "bytes"
       "net/http"
)

func main() {

    headers := map[string][]string{
        "Accept": []string{"application/json"},
    }

    data := bytes.NewBuffer([]byte{jsonReq})
    req, err := http.NewRequest("GET", "/api/projects/{project_id}/persons/properties/", data)
    req.Header = headers

    client := &http.Client{}
    resp, err := client.Do(req)
    // ...
}

```

`GET /api/projects/{project_id}/persons/properties/`

<h3 id="persons_properties_retrieve-parameters">Parameters</h3>

|Name|In|Type|Required|Description|
|---|---|---|---|---|
|format|query|string|false|none|
|project_id|path|string|true|Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/.|

#### Enumerated Values

|Parameter|Value|
|---|---|
|format|csv|
|format|json|

> Example responses

> 200 Response

```json
{
  "id": 0,
  "name": "string",
  "distinct_ids": [
    "string"
  ],
  "properties": {
    "property1": null,
    "property2": null
  },
  "created_at": "2019-08-24T14:15:22Z",
  "uuid": "095be615-a8ad-4c33-8e9c-c7612fbf6c9f"
}
```

<h3 id="persons_properties_retrieve-responses">Responses</h3>

|Status|Meaning|Description|Schema|
|---|---|---|---|
|200|[OK](https://tools.ietf.org/html/rfc7231#section-6.3.1)|none|[Person](#schemaperson)|

<aside class="success">
This operation does not require authentication
</aside>

## persons_retention_retrieve

<a id="opIdpersons_retention_retrieve"></a>

> Code samples

```shell
# You can also use wget
curl -X GET /api/projects/{project_id}/persons/retention/ \
  -H 'Accept: application/json'

```

```http
GET /api/projects/{project_id}/persons/retention/ HTTP/1.1

Accept: application/json

```

```javascript

const headers = {
  'Accept':'application/json'
};

fetch('/api/projects/{project_id}/persons/retention/',
{
  method: 'GET',

  headers: headers
})
.then(function(res) {
    return res.json();
}).then(function(body) {
    console.log(body);
});

```

```ruby
require 'rest-client'
require 'json'

headers = {
  'Accept' => 'application/json'
}

result = RestClient.get '/api/projects/{project_id}/persons/retention/',
  params: {
  }, headers: headers

p JSON.parse(result)

```

```python
import requests
headers = {
  'Accept': 'application/json'
}

r = requests.get('/api/projects/{project_id}/persons/retention/', headers = headers)

print(r.json())

```

```php
<?php

require 'vendor/autoload.php';

$headers = array(
    'Accept' => 'application/json',
);

$client = new \GuzzleHttp\Client();

// Define array of request body.
$request_body = array();

try {
    $response = $client->request('GET','/api/projects/{project_id}/persons/retention/', array(
        'headers' => $headers,
        'json' => $request_body,
       )
    );
    print_r($response->getBody()->getContents());
 }
 catch (\GuzzleHttp\Exception\BadResponseException $e) {
    // handle exception or api errors.
    print_r($e->getMessage());
 }

 // ...

```

```java
URL obj = new URL("/api/projects/{project_id}/persons/retention/");
HttpURLConnection con = (HttpURLConnection) obj.openConnection();
con.setRequestMethod("GET");
int responseCode = con.getResponseCode();
BufferedReader in = new BufferedReader(
    new InputStreamReader(con.getInputStream()));
String inputLine;
StringBuffer response = new StringBuffer();
while ((inputLine = in.readLine()) != null) {
    response.append(inputLine);
}
in.close();
System.out.println(response.toString());

```

```go
package main

import (
       "bytes"
       "net/http"
)

func main() {

    headers := map[string][]string{
        "Accept": []string{"application/json"},
    }

    data := bytes.NewBuffer([]byte{jsonReq})
    req, err := http.NewRequest("GET", "/api/projects/{project_id}/persons/retention/", data)
    req.Header = headers

    client := &http.Client{}
    resp, err := client.Do(req)
    // ...
}

```

`GET /api/projects/{project_id}/persons/retention/`

<h3 id="persons_retention_retrieve-parameters">Parameters</h3>

|Name|In|Type|Required|Description|
|---|---|---|---|---|
|format|query|string|false|none|
|project_id|path|string|true|Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/.|

#### Enumerated Values

|Parameter|Value|
|---|---|
|format|csv|
|format|json|

> Example responses

> 200 Response

```json
{
  "id": 0,
  "name": "string",
  "distinct_ids": [
    "string"
  ],
  "properties": {
    "property1": null,
    "property2": null
  },
  "created_at": "2019-08-24T14:15:22Z",
  "uuid": "095be615-a8ad-4c33-8e9c-c7612fbf6c9f"
}
```

<h3 id="persons_retention_retrieve-responses">Responses</h3>

|Status|Meaning|Description|Schema|
|---|---|---|---|
|200|[OK](https://tools.ietf.org/html/rfc7231#section-6.3.1)|none|[Person](#schemaperson)|

<aside class="success">
This operation does not require authentication
</aside>

## persons_stickiness_retrieve

<a id="opIdpersons_stickiness_retrieve"></a>

> Code samples

```shell
# You can also use wget
curl -X GET /api/projects/{project_id}/persons/stickiness/ \
  -H 'Accept: application/json'

```

```http
GET /api/projects/{project_id}/persons/stickiness/ HTTP/1.1

Accept: application/json

```

```javascript

const headers = {
  'Accept':'application/json'
};

fetch('/api/projects/{project_id}/persons/stickiness/',
{
  method: 'GET',

  headers: headers
})
.then(function(res) {
    return res.json();
}).then(function(body) {
    console.log(body);
});

```

```ruby
require 'rest-client'
require 'json'

headers = {
  'Accept' => 'application/json'
}

result = RestClient.get '/api/projects/{project_id}/persons/stickiness/',
  params: {
  }, headers: headers

p JSON.parse(result)

```

```python
import requests
headers = {
  'Accept': 'application/json'
}

r = requests.get('/api/projects/{project_id}/persons/stickiness/', headers = headers)

print(r.json())

```

```php
<?php

require 'vendor/autoload.php';

$headers = array(
    'Accept' => 'application/json',
);

$client = new \GuzzleHttp\Client();

// Define array of request body.
$request_body = array();

try {
    $response = $client->request('GET','/api/projects/{project_id}/persons/stickiness/', array(
        'headers' => $headers,
        'json' => $request_body,
       )
    );
    print_r($response->getBody()->getContents());
 }
 catch (\GuzzleHttp\Exception\BadResponseException $e) {
    // handle exception or api errors.
    print_r($e->getMessage());
 }

 // ...

```

```java
URL obj = new URL("/api/projects/{project_id}/persons/stickiness/");
HttpURLConnection con = (HttpURLConnection) obj.openConnection();
con.setRequestMethod("GET");
int responseCode = con.getResponseCode();
BufferedReader in = new BufferedReader(
    new InputStreamReader(con.getInputStream()));
String inputLine;
StringBuffer response = new StringBuffer();
while ((inputLine = in.readLine()) != null) {
    response.append(inputLine);
}
in.close();
System.out.println(response.toString());

```

```go
package main

import (
       "bytes"
       "net/http"
)

func main() {

    headers := map[string][]string{
        "Accept": []string{"application/json"},
    }

    data := bytes.NewBuffer([]byte{jsonReq})
    req, err := http.NewRequest("GET", "/api/projects/{project_id}/persons/stickiness/", data)
    req.Header = headers

    client := &http.Client{}
    resp, err := client.Do(req)
    // ...
}

```

`GET /api/projects/{project_id}/persons/stickiness/`

<h3 id="persons_stickiness_retrieve-parameters">Parameters</h3>

|Name|In|Type|Required|Description|
|---|---|---|---|---|
|format|query|string|false|none|
|project_id|path|string|true|Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/.|

#### Enumerated Values

|Parameter|Value|
|---|---|
|format|csv|
|format|json|

> Example responses

> 200 Response

```json
{
  "id": 0,
  "name": "string",
  "distinct_ids": [
    "string"
  ],
  "properties": {
    "property1": null,
    "property2": null
  },
  "created_at": "2019-08-24T14:15:22Z",
  "uuid": "095be615-a8ad-4c33-8e9c-c7612fbf6c9f"
}
```

<h3 id="persons_stickiness_retrieve-responses">Responses</h3>

|Status|Meaning|Description|Schema|
|---|---|---|---|
|200|[OK](https://tools.ietf.org/html/rfc7231#section-6.3.1)|none|[Person](#schemaperson)|

<aside class="success">
This operation does not require authentication
</aside>

## persons_values_retrieve

<a id="opIdpersons_values_retrieve"></a>

> Code samples

```shell
# You can also use wget
curl -X GET /api/projects/{project_id}/persons/values/ \
  -H 'Accept: application/json'

```

```http
GET /api/projects/{project_id}/persons/values/ HTTP/1.1

Accept: application/json

```

```javascript

const headers = {
  'Accept':'application/json'
};

fetch('/api/projects/{project_id}/persons/values/',
{
  method: 'GET',

  headers: headers
})
.then(function(res) {
    return res.json();
}).then(function(body) {
    console.log(body);
});

```

```ruby
require 'rest-client'
require 'json'

headers = {
  'Accept' => 'application/json'
}

result = RestClient.get '/api/projects/{project_id}/persons/values/',
  params: {
  }, headers: headers

p JSON.parse(result)

```

```python
import requests
headers = {
  'Accept': 'application/json'
}

r = requests.get('/api/projects/{project_id}/persons/values/', headers = headers)

print(r.json())

```

```php
<?php

require 'vendor/autoload.php';

$headers = array(
    'Accept' => 'application/json',
);

$client = new \GuzzleHttp\Client();

// Define array of request body.
$request_body = array();

try {
    $response = $client->request('GET','/api/projects/{project_id}/persons/values/', array(
        'headers' => $headers,
        'json' => $request_body,
       )
    );
    print_r($response->getBody()->getContents());
 }
 catch (\GuzzleHttp\Exception\BadResponseException $e) {
    // handle exception or api errors.
    print_r($e->getMessage());
 }

 // ...

```

```java
URL obj = new URL("/api/projects/{project_id}/persons/values/");
HttpURLConnection con = (HttpURLConnection) obj.openConnection();
con.setRequestMethod("GET");
int responseCode = con.getResponseCode();
BufferedReader in = new BufferedReader(
    new InputStreamReader(con.getInputStream()));
String inputLine;
StringBuffer response = new StringBuffer();
while ((inputLine = in.readLine()) != null) {
    response.append(inputLine);
}
in.close();
System.out.println(response.toString());

```

```go
package main

import (
       "bytes"
       "net/http"
)

func main() {

    headers := map[string][]string{
        "Accept": []string{"application/json"},
    }

    data := bytes.NewBuffer([]byte{jsonReq})
    req, err := http.NewRequest("GET", "/api/projects/{project_id}/persons/values/", data)
    req.Header = headers

    client := &http.Client{}
    resp, err := client.Do(req)
    // ...
}

```

`GET /api/projects/{project_id}/persons/values/`

<h3 id="persons_values_retrieve-parameters">Parameters</h3>

|Name|In|Type|Required|Description|
|---|---|---|---|---|
|format|query|string|false|none|
|project_id|path|string|true|Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/.|

#### Enumerated Values

|Parameter|Value|
|---|---|
|format|csv|
|format|json|

> Example responses

> 200 Response

```json
{
  "id": 0,
  "name": "string",
  "distinct_ids": [
    "string"
  ],
  "properties": {
    "property1": null,
    "property2": null
  },
  "created_at": "2019-08-24T14:15:22Z",
  "uuid": "095be615-a8ad-4c33-8e9c-c7612fbf6c9f"
}
```

<h3 id="persons_values_retrieve-responses">Responses</h3>

|Status|Meaning|Description|Schema|
|---|---|---|---|
|200|[OK](https://tools.ietf.org/html/rfc7231#section-6.3.1)|none|[Person](#schemaperson)|

<aside class="success">
This operation does not require authentication
</aside>

<h1 id="-plugin_configs">plugin_configs</h1>

## plugin_configs_list

<a id="opIdplugin_configs_list"></a>

> Code samples

```shell
# You can also use wget
curl -X GET /api/projects/{project_id}/plugin_configs/ \
  -H 'Accept: application/json'

```

```http
GET /api/projects/{project_id}/plugin_configs/ HTTP/1.1

Accept: application/json

```

```javascript

const headers = {
  'Accept':'application/json'
};

fetch('/api/projects/{project_id}/plugin_configs/',
{
  method: 'GET',

  headers: headers
})
.then(function(res) {
    return res.json();
}).then(function(body) {
    console.log(body);
});

```

```ruby
require 'rest-client'
require 'json'

headers = {
  'Accept' => 'application/json'
}

result = RestClient.get '/api/projects/{project_id}/plugin_configs/',
  params: {
  }, headers: headers

p JSON.parse(result)

```

```python
import requests
headers = {
  'Accept': 'application/json'
}

r = requests.get('/api/projects/{project_id}/plugin_configs/', headers = headers)

print(r.json())

```

```php
<?php

require 'vendor/autoload.php';

$headers = array(
    'Accept' => 'application/json',
);

$client = new \GuzzleHttp\Client();

// Define array of request body.
$request_body = array();

try {
    $response = $client->request('GET','/api/projects/{project_id}/plugin_configs/', array(
        'headers' => $headers,
        'json' => $request_body,
       )
    );
    print_r($response->getBody()->getContents());
 }
 catch (\GuzzleHttp\Exception\BadResponseException $e) {
    // handle exception or api errors.
    print_r($e->getMessage());
 }

 // ...

```

```java
URL obj = new URL("/api/projects/{project_id}/plugin_configs/");
HttpURLConnection con = (HttpURLConnection) obj.openConnection();
con.setRequestMethod("GET");
int responseCode = con.getResponseCode();
BufferedReader in = new BufferedReader(
    new InputStreamReader(con.getInputStream()));
String inputLine;
StringBuffer response = new StringBuffer();
while ((inputLine = in.readLine()) != null) {
    response.append(inputLine);
}
in.close();
System.out.println(response.toString());

```

```go
package main

import (
       "bytes"
       "net/http"
)

func main() {

    headers := map[string][]string{
        "Accept": []string{"application/json"},
    }

    data := bytes.NewBuffer([]byte{jsonReq})
    req, err := http.NewRequest("GET", "/api/projects/{project_id}/plugin_configs/", data)
    req.Header = headers

    client := &http.Client{}
    resp, err := client.Do(req)
    // ...
}

```

`GET /api/projects/{project_id}/plugin_configs/`

<h3 id="plugin_configs_list-parameters">Parameters</h3>

|Name|In|Type|Required|Description|
|---|---|---|---|---|
|limit|query|integer|false|Number of results to return per page.|
|offset|query|integer|false|The initial index from which to return the results.|
|project_id|path|string|true|Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/.|

> Example responses

> 200 Response

```json
{
  "count": 123,
  "next": "http://api.example.org/accounts/?offset=400&limit=100",
  "previous": "http://api.example.org/accounts/?offset=200&limit=100",
  "results": [
    {
      "id": 0,
      "plugin": 0,
      "enabled": true,
      "order": -2147483648,
      "config": "string",
      "error": {
        "property1": null,
        "property2": null
      },
      "team_id": 0
    }
  ]
}
```

<h3 id="plugin_configs_list-responses">Responses</h3>

|Status|Meaning|Description|Schema|
|---|---|---|---|
|200|[OK](https://tools.ietf.org/html/rfc7231#section-6.3.1)|none|[PaginatedPluginConfigList](#schemapaginatedpluginconfiglist)|

<aside class="success">
This operation does not require authentication
</aside>

## plugin_configs_create

<a id="opIdplugin_configs_create"></a>

> Code samples

```shell
# You can also use wget
curl -X POST /api/projects/{project_id}/plugin_configs/ \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json'

```

```http
POST /api/projects/{project_id}/plugin_configs/ HTTP/1.1

Content-Type: application/json
Accept: application/json

```

```javascript
const inputBody = '{
  "plugin": 0,
  "enabled": true,
  "order": -2147483648,
  "error": {
    "property1": null,
    "property2": null
  }
}';
const headers = {
  'Content-Type':'application/json',
  'Accept':'application/json'
};

fetch('/api/projects/{project_id}/plugin_configs/',
{
  method: 'POST',
  body: inputBody,
  headers: headers
})
.then(function(res) {
    return res.json();
}).then(function(body) {
    console.log(body);
});

```

```ruby
require 'rest-client'
require 'json'

headers = {
  'Content-Type' => 'application/json',
  'Accept' => 'application/json'
}

result = RestClient.post '/api/projects/{project_id}/plugin_configs/',
  params: {
  }, headers: headers

p JSON.parse(result)

```

```python
import requests
headers = {
  'Content-Type': 'application/json',
  'Accept': 'application/json'
}

r = requests.post('/api/projects/{project_id}/plugin_configs/', headers = headers)

print(r.json())

```

```php
<?php

require 'vendor/autoload.php';

$headers = array(
    'Content-Type' => 'application/json',
    'Accept' => 'application/json',
);

$client = new \GuzzleHttp\Client();

// Define array of request body.
$request_body = array();

try {
    $response = $client->request('POST','/api/projects/{project_id}/plugin_configs/', array(
        'headers' => $headers,
        'json' => $request_body,
       )
    );
    print_r($response->getBody()->getContents());
 }
 catch (\GuzzleHttp\Exception\BadResponseException $e) {
    // handle exception or api errors.
    print_r($e->getMessage());
 }

 // ...

```

```java
URL obj = new URL("/api/projects/{project_id}/plugin_configs/");
HttpURLConnection con = (HttpURLConnection) obj.openConnection();
con.setRequestMethod("POST");
int responseCode = con.getResponseCode();
BufferedReader in = new BufferedReader(
    new InputStreamReader(con.getInputStream()));
String inputLine;
StringBuffer response = new StringBuffer();
while ((inputLine = in.readLine()) != null) {
    response.append(inputLine);
}
in.close();
System.out.println(response.toString());

```

```go
package main

import (
       "bytes"
       "net/http"
)

func main() {

    headers := map[string][]string{
        "Content-Type": []string{"application/json"},
        "Accept": []string{"application/json"},
    }

    data := bytes.NewBuffer([]byte{jsonReq})
    req, err := http.NewRequest("POST", "/api/projects/{project_id}/plugin_configs/", data)
    req.Header = headers

    client := &http.Client{}
    resp, err := client.Do(req)
    // ...
}

```

`POST /api/projects/{project_id}/plugin_configs/`

> Body parameter

```json
{
  "plugin": 0,
  "enabled": true,
  "order": -2147483648,
  "error": {
    "property1": null,
    "property2": null
  }
}
```

```yaml
plugin: 0
enabled: true
order: -2147483648
error:
  ? property1
  ? property2

```

<h3 id="plugin_configs_create-parameters">Parameters</h3>

|Name|In|Type|Required|Description|
|---|---|---|---|---|
|project_id|path|string|true|Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/.|
|body|body|[PluginConfig](#schemapluginconfig)|true|none|

> Example responses

> 201 Response

```json
{
  "id": 0,
  "plugin": 0,
  "enabled": true,
  "order": -2147483648,
  "config": "string",
  "error": {
    "property1": null,
    "property2": null
  },
  "team_id": 0
}
```

<h3 id="plugin_configs_create-responses">Responses</h3>

|Status|Meaning|Description|Schema|
|---|---|---|---|
|201|[Created](https://tools.ietf.org/html/rfc7231#section-6.3.2)|none|[PluginConfig](#schemapluginconfig)|

<aside class="success">
This operation does not require authentication
</aside>

## plugin_configs_logs_list

<a id="opIdplugin_configs_logs_list"></a>

> Code samples

```shell
# You can also use wget
curl -X GET /api/projects/{project_id}/plugin_configs/{parent_lookup_plugin_config_id}/logs/ \
  -H 'Accept: application/json'

```

```http
GET /api/projects/{project_id}/plugin_configs/{parent_lookup_plugin_config_id}/logs/ HTTP/1.1

Accept: application/json

```

```javascript

const headers = {
  'Accept':'application/json'
};

fetch('/api/projects/{project_id}/plugin_configs/{parent_lookup_plugin_config_id}/logs/',
{
  method: 'GET',

  headers: headers
})
.then(function(res) {
    return res.json();
}).then(function(body) {
    console.log(body);
});

```

```ruby
require 'rest-client'
require 'json'

headers = {
  'Accept' => 'application/json'
}

result = RestClient.get '/api/projects/{project_id}/plugin_configs/{parent_lookup_plugin_config_id}/logs/',
  params: {
  }, headers: headers

p JSON.parse(result)

```

```python
import requests
headers = {
  'Accept': 'application/json'
}

r = requests.get('/api/projects/{project_id}/plugin_configs/{parent_lookup_plugin_config_id}/logs/', headers = headers)

print(r.json())

```

```php
<?php

require 'vendor/autoload.php';

$headers = array(
    'Accept' => 'application/json',
);

$client = new \GuzzleHttp\Client();

// Define array of request body.
$request_body = array();

try {
    $response = $client->request('GET','/api/projects/{project_id}/plugin_configs/{parent_lookup_plugin_config_id}/logs/', array(
        'headers' => $headers,
        'json' => $request_body,
       )
    );
    print_r($response->getBody()->getContents());
 }
 catch (\GuzzleHttp\Exception\BadResponseException $e) {
    // handle exception or api errors.
    print_r($e->getMessage());
 }

 // ...

```

```java
URL obj = new URL("/api/projects/{project_id}/plugin_configs/{parent_lookup_plugin_config_id}/logs/");
HttpURLConnection con = (HttpURLConnection) obj.openConnection();
con.setRequestMethod("GET");
int responseCode = con.getResponseCode();
BufferedReader in = new BufferedReader(
    new InputStreamReader(con.getInputStream()));
String inputLine;
StringBuffer response = new StringBuffer();
while ((inputLine = in.readLine()) != null) {
    response.append(inputLine);
}
in.close();
System.out.println(response.toString());

```

```go
package main

import (
       "bytes"
       "net/http"
)

func main() {

    headers := map[string][]string{
        "Accept": []string{"application/json"},
    }

    data := bytes.NewBuffer([]byte{jsonReq})
    req, err := http.NewRequest("GET", "/api/projects/{project_id}/plugin_configs/{parent_lookup_plugin_config_id}/logs/", data)
    req.Header = headers

    client := &http.Client{}
    resp, err := client.Do(req)
    // ...
}

```

`GET /api/projects/{project_id}/plugin_configs/{parent_lookup_plugin_config_id}/logs/`

<h3 id="plugin_configs_logs_list-parameters">Parameters</h3>

|Name|In|Type|Required|Description|
|---|---|---|---|---|
|limit|query|integer|false|Number of results to return per page.|
|offset|query|integer|false|The initial index from which to return the results.|
|parent_lookup_plugin_config_id|path|string|true|none|
|project_id|path|string|true|Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/.|

> Example responses

> 200 Response

```json
{
  "count": 123,
  "next": "http://api.example.org/accounts/?offset=400&limit=100",
  "previous": "http://api.example.org/accounts/?offset=200&limit=100",
  "results": [
    {
      "id": "497f6eca-6276-4993-bfeb-53cbbbba6f08",
      "team_id": 0,
      "plugin_id": 0,
      "timestamp": "2019-08-24T14:15:22Z",
      "source": "SYSTEM",
      "type": "DEBUG",
      "message": "string",
      "instance_id": "06587974-2dbe-4e10-8bf9-38cce0f5a366"
    }
  ]
}
```

<h3 id="plugin_configs_logs_list-responses">Responses</h3>

|Status|Meaning|Description|Schema|
|---|---|---|---|
|200|[OK](https://tools.ietf.org/html/rfc7231#section-6.3.1)|none|[PaginatedPluginLogEntryList](#schemapaginatedpluginlogentrylist)|

<aside class="success">
This operation does not require authentication
</aside>

## plugin_configs_retrieve

<a id="opIdplugin_configs_retrieve"></a>

> Code samples

```shell
# You can also use wget
curl -X GET /api/projects/{project_id}/plugin_configs/{id}/ \
  -H 'Accept: application/json'

```

```http
GET /api/projects/{project_id}/plugin_configs/{id}/ HTTP/1.1

Accept: application/json

```

```javascript

const headers = {
  'Accept':'application/json'
};

fetch('/api/projects/{project_id}/plugin_configs/{id}/',
{
  method: 'GET',

  headers: headers
})
.then(function(res) {
    return res.json();
}).then(function(body) {
    console.log(body);
});

```

```ruby
require 'rest-client'
require 'json'

headers = {
  'Accept' => 'application/json'
}

result = RestClient.get '/api/projects/{project_id}/plugin_configs/{id}/',
  params: {
  }, headers: headers

p JSON.parse(result)

```

```python
import requests
headers = {
  'Accept': 'application/json'
}

r = requests.get('/api/projects/{project_id}/plugin_configs/{id}/', headers = headers)

print(r.json())

```

```php
<?php

require 'vendor/autoload.php';

$headers = array(
    'Accept' => 'application/json',
);

$client = new \GuzzleHttp\Client();

// Define array of request body.
$request_body = array();

try {
    $response = $client->request('GET','/api/projects/{project_id}/plugin_configs/{id}/', array(
        'headers' => $headers,
        'json' => $request_body,
       )
    );
    print_r($response->getBody()->getContents());
 }
 catch (\GuzzleHttp\Exception\BadResponseException $e) {
    // handle exception or api errors.
    print_r($e->getMessage());
 }

 // ...

```

```java
URL obj = new URL("/api/projects/{project_id}/plugin_configs/{id}/");
HttpURLConnection con = (HttpURLConnection) obj.openConnection();
con.setRequestMethod("GET");
int responseCode = con.getResponseCode();
BufferedReader in = new BufferedReader(
    new InputStreamReader(con.getInputStream()));
String inputLine;
StringBuffer response = new StringBuffer();
while ((inputLine = in.readLine()) != null) {
    response.append(inputLine);
}
in.close();
System.out.println(response.toString());

```

```go
package main

import (
       "bytes"
       "net/http"
)

func main() {

    headers := map[string][]string{
        "Accept": []string{"application/json"},
    }

    data := bytes.NewBuffer([]byte{jsonReq})
    req, err := http.NewRequest("GET", "/api/projects/{project_id}/plugin_configs/{id}/", data)
    req.Header = headers

    client := &http.Client{}
    resp, err := client.Do(req)
    // ...
}

```

`GET /api/projects/{project_id}/plugin_configs/{id}/`

<h3 id="plugin_configs_retrieve-parameters">Parameters</h3>

|Name|In|Type|Required|Description|
|---|---|---|---|---|
|id|path|integer|true|A unique integer value identifying this plugin config.|
|project_id|path|string|true|Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/.|

> Example responses

> 200 Response

```json
{
  "id": 0,
  "plugin": 0,
  "enabled": true,
  "order": -2147483648,
  "config": "string",
  "error": {
    "property1": null,
    "property2": null
  },
  "team_id": 0
}
```

<h3 id="plugin_configs_retrieve-responses">Responses</h3>

|Status|Meaning|Description|Schema|
|---|---|---|---|
|200|[OK](https://tools.ietf.org/html/rfc7231#section-6.3.1)|none|[PluginConfig](#schemapluginconfig)|

<aside class="success">
This operation does not require authentication
</aside>

## plugin_configs_update

<a id="opIdplugin_configs_update"></a>

> Code samples

```shell
# You can also use wget
curl -X PUT /api/projects/{project_id}/plugin_configs/{id}/ \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json'

```

```http
PUT /api/projects/{project_id}/plugin_configs/{id}/ HTTP/1.1

Content-Type: application/json
Accept: application/json

```

```javascript
const inputBody = '{
  "plugin": 0,
  "enabled": true,
  "order": -2147483648,
  "error": {
    "property1": null,
    "property2": null
  }
}';
const headers = {
  'Content-Type':'application/json',
  'Accept':'application/json'
};

fetch('/api/projects/{project_id}/plugin_configs/{id}/',
{
  method: 'PUT',
  body: inputBody,
  headers: headers
})
.then(function(res) {
    return res.json();
}).then(function(body) {
    console.log(body);
});

```

```ruby
require 'rest-client'
require 'json'

headers = {
  'Content-Type' => 'application/json',
  'Accept' => 'application/json'
}

result = RestClient.put '/api/projects/{project_id}/plugin_configs/{id}/',
  params: {
  }, headers: headers

p JSON.parse(result)

```

```python
import requests
headers = {
  'Content-Type': 'application/json',
  'Accept': 'application/json'
}

r = requests.put('/api/projects/{project_id}/plugin_configs/{id}/', headers = headers)

print(r.json())

```

```php
<?php

require 'vendor/autoload.php';

$headers = array(
    'Content-Type' => 'application/json',
    'Accept' => 'application/json',
);

$client = new \GuzzleHttp\Client();

// Define array of request body.
$request_body = array();

try {
    $response = $client->request('PUT','/api/projects/{project_id}/plugin_configs/{id}/', array(
        'headers' => $headers,
        'json' => $request_body,
       )
    );
    print_r($response->getBody()->getContents());
 }
 catch (\GuzzleHttp\Exception\BadResponseException $e) {
    // handle exception or api errors.
    print_r($e->getMessage());
 }

 // ...

```

```java
URL obj = new URL("/api/projects/{project_id}/plugin_configs/{id}/");
HttpURLConnection con = (HttpURLConnection) obj.openConnection();
con.setRequestMethod("PUT");
int responseCode = con.getResponseCode();
BufferedReader in = new BufferedReader(
    new InputStreamReader(con.getInputStream()));
String inputLine;
StringBuffer response = new StringBuffer();
while ((inputLine = in.readLine()) != null) {
    response.append(inputLine);
}
in.close();
System.out.println(response.toString());

```

```go
package main

import (
       "bytes"
       "net/http"
)

func main() {

    headers := map[string][]string{
        "Content-Type": []string{"application/json"},
        "Accept": []string{"application/json"},
    }

    data := bytes.NewBuffer([]byte{jsonReq})
    req, err := http.NewRequest("PUT", "/api/projects/{project_id}/plugin_configs/{id}/", data)
    req.Header = headers

    client := &http.Client{}
    resp, err := client.Do(req)
    // ...
}

```

`PUT /api/projects/{project_id}/plugin_configs/{id}/`

> Body parameter

```json
{
  "plugin": 0,
  "enabled": true,
  "order": -2147483648,
  "error": {
    "property1": null,
    "property2": null
  }
}
```

```yaml
plugin: 0
enabled: true
order: -2147483648
error:
  ? property1
  ? property2

```

<h3 id="plugin_configs_update-parameters">Parameters</h3>

|Name|In|Type|Required|Description|
|---|---|---|---|---|
|id|path|integer|true|A unique integer value identifying this plugin config.|
|project_id|path|string|true|Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/.|
|body|body|[PluginConfig](#schemapluginconfig)|true|none|

> Example responses

> 200 Response

```json
{
  "id": 0,
  "plugin": 0,
  "enabled": true,
  "order": -2147483648,
  "config": "string",
  "error": {
    "property1": null,
    "property2": null
  },
  "team_id": 0
}
```

<h3 id="plugin_configs_update-responses">Responses</h3>

|Status|Meaning|Description|Schema|
|---|---|---|---|
|200|[OK](https://tools.ietf.org/html/rfc7231#section-6.3.1)|none|[PluginConfig](#schemapluginconfig)|

<aside class="success">
This operation does not require authentication
</aside>

## plugin_configs_partial_update

<a id="opIdplugin_configs_partial_update"></a>

> Code samples

```shell
# You can also use wget
curl -X PATCH /api/projects/{project_id}/plugin_configs/{id}/ \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json'

```

```http
PATCH /api/projects/{project_id}/plugin_configs/{id}/ HTTP/1.1

Content-Type: application/json
Accept: application/json

```

```javascript
const inputBody = '{
  "plugin": 0,
  "enabled": true,
  "order": -2147483648,
  "error": {
    "property1": null,
    "property2": null
  }
}';
const headers = {
  'Content-Type':'application/json',
  'Accept':'application/json'
};

fetch('/api/projects/{project_id}/plugin_configs/{id}/',
{
  method: 'PATCH',
  body: inputBody,
  headers: headers
})
.then(function(res) {
    return res.json();
}).then(function(body) {
    console.log(body);
});

```

```ruby
require 'rest-client'
require 'json'

headers = {
  'Content-Type' => 'application/json',
  'Accept' => 'application/json'
}

result = RestClient.patch '/api/projects/{project_id}/plugin_configs/{id}/',
  params: {
  }, headers: headers

p JSON.parse(result)

```

```python
import requests
headers = {
  'Content-Type': 'application/json',
  'Accept': 'application/json'
}

r = requests.patch('/api/projects/{project_id}/plugin_configs/{id}/', headers = headers)

print(r.json())

```

```php
<?php

require 'vendor/autoload.php';

$headers = array(
    'Content-Type' => 'application/json',
    'Accept' => 'application/json',
);

$client = new \GuzzleHttp\Client();

// Define array of request body.
$request_body = array();

try {
    $response = $client->request('PATCH','/api/projects/{project_id}/plugin_configs/{id}/', array(
        'headers' => $headers,
        'json' => $request_body,
       )
    );
    print_r($response->getBody()->getContents());
 }
 catch (\GuzzleHttp\Exception\BadResponseException $e) {
    // handle exception or api errors.
    print_r($e->getMessage());
 }

 // ...

```

```java
URL obj = new URL("/api/projects/{project_id}/plugin_configs/{id}/");
HttpURLConnection con = (HttpURLConnection) obj.openConnection();
con.setRequestMethod("PATCH");
int responseCode = con.getResponseCode();
BufferedReader in = new BufferedReader(
    new InputStreamReader(con.getInputStream()));
String inputLine;
StringBuffer response = new StringBuffer();
while ((inputLine = in.readLine()) != null) {
    response.append(inputLine);
}
in.close();
System.out.println(response.toString());

```

```go
package main

import (
       "bytes"
       "net/http"
)

func main() {

    headers := map[string][]string{
        "Content-Type": []string{"application/json"},
        "Accept": []string{"application/json"},
    }

    data := bytes.NewBuffer([]byte{jsonReq})
    req, err := http.NewRequest("PATCH", "/api/projects/{project_id}/plugin_configs/{id}/", data)
    req.Header = headers

    client := &http.Client{}
    resp, err := client.Do(req)
    // ...
}

```

`PATCH /api/projects/{project_id}/plugin_configs/{id}/`

> Body parameter

```json
{
  "plugin": 0,
  "enabled": true,
  "order": -2147483648,
  "error": {
    "property1": null,
    "property2": null
  }
}
```

```yaml
plugin: 0
enabled: true
order: -2147483648
error:
  ? property1
  ? property2

```

<h3 id="plugin_configs_partial_update-parameters">Parameters</h3>

|Name|In|Type|Required|Description|
|---|---|---|---|---|
|id|path|integer|true|A unique integer value identifying this plugin config.|
|project_id|path|string|true|Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/.|
|body|body|[PatchedPluginConfig](#schemapatchedpluginconfig)|false|none|

> Example responses

> 200 Response

```json
{
  "id": 0,
  "plugin": 0,
  "enabled": true,
  "order": -2147483648,
  "config": "string",
  "error": {
    "property1": null,
    "property2": null
  },
  "team_id": 0
}
```

<h3 id="plugin_configs_partial_update-responses">Responses</h3>

|Status|Meaning|Description|Schema|
|---|---|---|---|
|200|[OK](https://tools.ietf.org/html/rfc7231#section-6.3.1)|none|[PluginConfig](#schemapluginconfig)|

<aside class="success">
This operation does not require authentication
</aside>

## plugin_configs_destroy

<a id="opIdplugin_configs_destroy"></a>

> Code samples

```shell
# You can also use wget
curl -X DELETE /api/projects/{project_id}/plugin_configs/{id}/

```

```http
DELETE /api/projects/{project_id}/plugin_configs/{id}/ HTTP/1.1

```

```javascript

fetch('/api/projects/{project_id}/plugin_configs/{id}/',
{
  method: 'DELETE'

})
.then(function(res) {
    return res.json();
}).then(function(body) {
    console.log(body);
});

```

```ruby
require 'rest-client'
require 'json'

result = RestClient.delete '/api/projects/{project_id}/plugin_configs/{id}/',
  params: {
  }

p JSON.parse(result)

```

```python
import requests

r = requests.delete('/api/projects/{project_id}/plugin_configs/{id}/')

print(r.json())

```

```php
<?php

require 'vendor/autoload.php';

$client = new \GuzzleHttp\Client();

// Define array of request body.
$request_body = array();

try {
    $response = $client->request('DELETE','/api/projects/{project_id}/plugin_configs/{id}/', array(
        'headers' => $headers,
        'json' => $request_body,
       )
    );
    print_r($response->getBody()->getContents());
 }
 catch (\GuzzleHttp\Exception\BadResponseException $e) {
    // handle exception or api errors.
    print_r($e->getMessage());
 }

 // ...

```

```java
URL obj = new URL("/api/projects/{project_id}/plugin_configs/{id}/");
HttpURLConnection con = (HttpURLConnection) obj.openConnection();
con.setRequestMethod("DELETE");
int responseCode = con.getResponseCode();
BufferedReader in = new BufferedReader(
    new InputStreamReader(con.getInputStream()));
String inputLine;
StringBuffer response = new StringBuffer();
while ((inputLine = in.readLine()) != null) {
    response.append(inputLine);
}
in.close();
System.out.println(response.toString());

```

```go
package main

import (
       "bytes"
       "net/http"
)

func main() {

    data := bytes.NewBuffer([]byte{jsonReq})
    req, err := http.NewRequest("DELETE", "/api/projects/{project_id}/plugin_configs/{id}/", data)
    req.Header = headers

    client := &http.Client{}
    resp, err := client.Do(req)
    // ...
}

```

`DELETE /api/projects/{project_id}/plugin_configs/{id}/`

<h3 id="plugin_configs_destroy-parameters">Parameters</h3>

|Name|In|Type|Required|Description|
|---|---|---|---|---|
|id|path|integer|true|A unique integer value identifying this plugin config.|
|project_id|path|string|true|Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/.|

<h3 id="plugin_configs_destroy-responses">Responses</h3>

|Status|Meaning|Description|Schema|
|---|---|---|---|
|204|[No Content](https://tools.ietf.org/html/rfc7231#section-6.3.5)|No response body|None|

<aside class="success">
This operation does not require authentication
</aside>

## plugin_configs_job_create

<a id="opIdplugin_configs_job_create"></a>

> Code samples

```shell
# You can also use wget
curl -X POST /api/projects/{project_id}/plugin_configs/{id}/job/ \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json'

```

```http
POST /api/projects/{project_id}/plugin_configs/{id}/job/ HTTP/1.1

Content-Type: application/json
Accept: application/json

```

```javascript
const inputBody = '{
  "plugin": 0,
  "enabled": true,
  "order": -2147483648,
  "error": {
    "property1": null,
    "property2": null
  }
}';
const headers = {
  'Content-Type':'application/json',
  'Accept':'application/json'
};

fetch('/api/projects/{project_id}/plugin_configs/{id}/job/',
{
  method: 'POST',
  body: inputBody,
  headers: headers
})
.then(function(res) {
    return res.json();
}).then(function(body) {
    console.log(body);
});

```

```ruby
require 'rest-client'
require 'json'

headers = {
  'Content-Type' => 'application/json',
  'Accept' => 'application/json'
}

result = RestClient.post '/api/projects/{project_id}/plugin_configs/{id}/job/',
  params: {
  }, headers: headers

p JSON.parse(result)

```

```python
import requests
headers = {
  'Content-Type': 'application/json',
  'Accept': 'application/json'
}

r = requests.post('/api/projects/{project_id}/plugin_configs/{id}/job/', headers = headers)

print(r.json())

```

```php
<?php

require 'vendor/autoload.php';

$headers = array(
    'Content-Type' => 'application/json',
    'Accept' => 'application/json',
);

$client = new \GuzzleHttp\Client();

// Define array of request body.
$request_body = array();

try {
    $response = $client->request('POST','/api/projects/{project_id}/plugin_configs/{id}/job/', array(
        'headers' => $headers,
        'json' => $request_body,
       )
    );
    print_r($response->getBody()->getContents());
 }
 catch (\GuzzleHttp\Exception\BadResponseException $e) {
    // handle exception or api errors.
    print_r($e->getMessage());
 }

 // ...

```

```java
URL obj = new URL("/api/projects/{project_id}/plugin_configs/{id}/job/");
HttpURLConnection con = (HttpURLConnection) obj.openConnection();
con.setRequestMethod("POST");
int responseCode = con.getResponseCode();
BufferedReader in = new BufferedReader(
    new InputStreamReader(con.getInputStream()));
String inputLine;
StringBuffer response = new StringBuffer();
while ((inputLine = in.readLine()) != null) {
    response.append(inputLine);
}
in.close();
System.out.println(response.toString());

```

```go
package main

import (
       "bytes"
       "net/http"
)

func main() {

    headers := map[string][]string{
        "Content-Type": []string{"application/json"},
        "Accept": []string{"application/json"},
    }

    data := bytes.NewBuffer([]byte{jsonReq})
    req, err := http.NewRequest("POST", "/api/projects/{project_id}/plugin_configs/{id}/job/", data)
    req.Header = headers

    client := &http.Client{}
    resp, err := client.Do(req)
    // ...
}

```

`POST /api/projects/{project_id}/plugin_configs/{id}/job/`

> Body parameter

```json
{
  "plugin": 0,
  "enabled": true,
  "order": -2147483648,
  "error": {
    "property1": null,
    "property2": null
  }
}
```

```yaml
plugin: 0
enabled: true
order: -2147483648
error:
  ? property1
  ? property2

```

<h3 id="plugin_configs_job_create-parameters">Parameters</h3>

|Name|In|Type|Required|Description|
|---|---|---|---|---|
|id|path|integer|true|A unique integer value identifying this plugin config.|
|project_id|path|string|true|Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/.|
|body|body|[PluginConfig](#schemapluginconfig)|true|none|

> Example responses

> 200 Response

```json
{
  "id": 0,
  "plugin": 0,
  "enabled": true,
  "order": -2147483648,
  "config": "string",
  "error": {
    "property1": null,
    "property2": null
  },
  "team_id": 0
}
```

<h3 id="plugin_configs_job_create-responses">Responses</h3>

|Status|Meaning|Description|Schema|
|---|---|---|---|
|200|[OK](https://tools.ietf.org/html/rfc7231#section-6.3.1)|none|[PluginConfig](#schemapluginconfig)|

<aside class="success">
This operation does not require authentication
</aside>

## plugin_configs_rearrange_partial_update

<a id="opIdplugin_configs_rearrange_partial_update"></a>

> Code samples

```shell
# You can also use wget
curl -X PATCH /api/projects/{project_id}/plugin_configs/rearrange/ \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json'

```

```http
PATCH /api/projects/{project_id}/plugin_configs/rearrange/ HTTP/1.1

Content-Type: application/json
Accept: application/json

```

```javascript
const inputBody = '{
  "plugin": 0,
  "enabled": true,
  "order": -2147483648,
  "error": {
    "property1": null,
    "property2": null
  }
}';
const headers = {
  'Content-Type':'application/json',
  'Accept':'application/json'
};

fetch('/api/projects/{project_id}/plugin_configs/rearrange/',
{
  method: 'PATCH',
  body: inputBody,
  headers: headers
})
.then(function(res) {
    return res.json();
}).then(function(body) {
    console.log(body);
});

```

```ruby
require 'rest-client'
require 'json'

headers = {
  'Content-Type' => 'application/json',
  'Accept' => 'application/json'
}

result = RestClient.patch '/api/projects/{project_id}/plugin_configs/rearrange/',
  params: {
  }, headers: headers

p JSON.parse(result)

```

```python
import requests
headers = {
  'Content-Type': 'application/json',
  'Accept': 'application/json'
}

r = requests.patch('/api/projects/{project_id}/plugin_configs/rearrange/', headers = headers)

print(r.json())

```

```php
<?php

require 'vendor/autoload.php';

$headers = array(
    'Content-Type' => 'application/json',
    'Accept' => 'application/json',
);

$client = new \GuzzleHttp\Client();

// Define array of request body.
$request_body = array();

try {
    $response = $client->request('PATCH','/api/projects/{project_id}/plugin_configs/rearrange/', array(
        'headers' => $headers,
        'json' => $request_body,
       )
    );
    print_r($response->getBody()->getContents());
 }
 catch (\GuzzleHttp\Exception\BadResponseException $e) {
    // handle exception or api errors.
    print_r($e->getMessage());
 }

 // ...

```

```java
URL obj = new URL("/api/projects/{project_id}/plugin_configs/rearrange/");
HttpURLConnection con = (HttpURLConnection) obj.openConnection();
con.setRequestMethod("PATCH");
int responseCode = con.getResponseCode();
BufferedReader in = new BufferedReader(
    new InputStreamReader(con.getInputStream()));
String inputLine;
StringBuffer response = new StringBuffer();
while ((inputLine = in.readLine()) != null) {
    response.append(inputLine);
}
in.close();
System.out.println(response.toString());

```

```go
package main

import (
       "bytes"
       "net/http"
)

func main() {

    headers := map[string][]string{
        "Content-Type": []string{"application/json"},
        "Accept": []string{"application/json"},
    }

    data := bytes.NewBuffer([]byte{jsonReq})
    req, err := http.NewRequest("PATCH", "/api/projects/{project_id}/plugin_configs/rearrange/", data)
    req.Header = headers

    client := &http.Client{}
    resp, err := client.Do(req)
    // ...
}

```

`PATCH /api/projects/{project_id}/plugin_configs/rearrange/`

> Body parameter

```json
{
  "plugin": 0,
  "enabled": true,
  "order": -2147483648,
  "error": {
    "property1": null,
    "property2": null
  }
}
```

```yaml
plugin: 0
enabled: true
order: -2147483648
error:
  ? property1
  ? property2

```

<h3 id="plugin_configs_rearrange_partial_update-parameters">Parameters</h3>

|Name|In|Type|Required|Description|
|---|---|---|---|---|
|project_id|path|string|true|Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/.|
|body|body|[PatchedPluginConfig](#schemapatchedpluginconfig)|false|none|

> Example responses

> 200 Response

```json
{
  "id": 0,
  "plugin": 0,
  "enabled": true,
  "order": -2147483648,
  "config": "string",
  "error": {
    "property1": null,
    "property2": null
  },
  "team_id": 0
}
```

<h3 id="plugin_configs_rearrange_partial_update-responses">Responses</h3>

|Status|Meaning|Description|Schema|
|---|---|---|---|
|200|[OK](https://tools.ietf.org/html/rfc7231#section-6.3.1)|none|[PluginConfig](#schemapluginconfig)|

<aside class="success">
This operation does not require authentication
</aside>

<h1 id="-property_definitions">property_definitions</h1>

## property_definitions_retrieve

<a id="opIdproperty_definitions_retrieve"></a>

> Code samples

```shell
# You can also use wget
curl -X GET /api/projects/{project_id}/property_definitions/

```

```http
GET /api/projects/{project_id}/property_definitions/ HTTP/1.1

```

```javascript

fetch('/api/projects/{project_id}/property_definitions/',
{
  method: 'GET'

})
.then(function(res) {
    return res.json();
}).then(function(body) {
    console.log(body);
});

```

```ruby
require 'rest-client'
require 'json'

result = RestClient.get '/api/projects/{project_id}/property_definitions/',
  params: {
  }

p JSON.parse(result)

```

```python
import requests

r = requests.get('/api/projects/{project_id}/property_definitions/')

print(r.json())

```

```php
<?php

require 'vendor/autoload.php';

$client = new \GuzzleHttp\Client();

// Define array of request body.
$request_body = array();

try {
    $response = $client->request('GET','/api/projects/{project_id}/property_definitions/', array(
        'headers' => $headers,
        'json' => $request_body,
       )
    );
    print_r($response->getBody()->getContents());
 }
 catch (\GuzzleHttp\Exception\BadResponseException $e) {
    // handle exception or api errors.
    print_r($e->getMessage());
 }

 // ...

```

```java
URL obj = new URL("/api/projects/{project_id}/property_definitions/");
HttpURLConnection con = (HttpURLConnection) obj.openConnection();
con.setRequestMethod("GET");
int responseCode = con.getResponseCode();
BufferedReader in = new BufferedReader(
    new InputStreamReader(con.getInputStream()));
String inputLine;
StringBuffer response = new StringBuffer();
while ((inputLine = in.readLine()) != null) {
    response.append(inputLine);
}
in.close();
System.out.println(response.toString());

```

```go
package main

import (
       "bytes"
       "net/http"
)

func main() {

    data := bytes.NewBuffer([]byte{jsonReq})
    req, err := http.NewRequest("GET", "/api/projects/{project_id}/property_definitions/", data)
    req.Header = headers

    client := &http.Client{}
    resp, err := client.Do(req)
    // ...
}

```

`GET /api/projects/{project_id}/property_definitions/`

<h3 id="property_definitions_retrieve-parameters">Parameters</h3>

|Name|In|Type|Required|Description|
|---|---|---|---|---|
|project_id|path|string|true|Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/.|

<h3 id="property_definitions_retrieve-responses">Responses</h3>

|Status|Meaning|Description|Schema|
|---|---|---|---|
|200|[OK](https://tools.ietf.org/html/rfc7231#section-6.3.1)|No response body|None|

<aside class="success">
This operation does not require authentication
</aside>

## property_definitions_retrieve_2

<a id="opIdproperty_definitions_retrieve_2"></a>

> Code samples

```shell
# You can also use wget
curl -X GET /api/projects/{project_id}/property_definitions/{id}/

```

```http
GET /api/projects/{project_id}/property_definitions/{id}/ HTTP/1.1

```

```javascript

fetch('/api/projects/{project_id}/property_definitions/{id}/',
{
  method: 'GET'

})
.then(function(res) {
    return res.json();
}).then(function(body) {
    console.log(body);
});

```

```ruby
require 'rest-client'
require 'json'

result = RestClient.get '/api/projects/{project_id}/property_definitions/{id}/',
  params: {
  }

p JSON.parse(result)

```

```python
import requests

r = requests.get('/api/projects/{project_id}/property_definitions/{id}/')

print(r.json())

```

```php
<?php

require 'vendor/autoload.php';

$client = new \GuzzleHttp\Client();

// Define array of request body.
$request_body = array();

try {
    $response = $client->request('GET','/api/projects/{project_id}/property_definitions/{id}/', array(
        'headers' => $headers,
        'json' => $request_body,
       )
    );
    print_r($response->getBody()->getContents());
 }
 catch (\GuzzleHttp\Exception\BadResponseException $e) {
    // handle exception or api errors.
    print_r($e->getMessage());
 }

 // ...

```

```java
URL obj = new URL("/api/projects/{project_id}/property_definitions/{id}/");
HttpURLConnection con = (HttpURLConnection) obj.openConnection();
con.setRequestMethod("GET");
int responseCode = con.getResponseCode();
BufferedReader in = new BufferedReader(
    new InputStreamReader(con.getInputStream()));
String inputLine;
StringBuffer response = new StringBuffer();
while ((inputLine = in.readLine()) != null) {
    response.append(inputLine);
}
in.close();
System.out.println(response.toString());

```

```go
package main

import (
       "bytes"
       "net/http"
)

func main() {

    data := bytes.NewBuffer([]byte{jsonReq})
    req, err := http.NewRequest("GET", "/api/projects/{project_id}/property_definitions/{id}/", data)
    req.Header = headers

    client := &http.Client{}
    resp, err := client.Do(req)
    // ...
}

```

`GET /api/projects/{project_id}/property_definitions/{id}/`

<h3 id="property_definitions_retrieve_2-parameters">Parameters</h3>

|Name|In|Type|Required|Description|
|---|---|---|---|---|
|id|path|string|true|none|
|project_id|path|string|true|Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/.|

<h3 id="property_definitions_retrieve_2-responses">Responses</h3>

|Status|Meaning|Description|Schema|
|---|---|---|---|
|200|[OK](https://tools.ietf.org/html/rfc7231#section-6.3.1)|No response body|None|

<aside class="success">
This operation does not require authentication
</aside>

## property_definitions_update

<a id="opIdproperty_definitions_update"></a>

> Code samples

```shell
# You can also use wget
curl -X PUT /api/projects/{project_id}/property_definitions/{id}/

```

```http
PUT /api/projects/{project_id}/property_definitions/{id}/ HTTP/1.1

```

```javascript

fetch('/api/projects/{project_id}/property_definitions/{id}/',
{
  method: 'PUT'

})
.then(function(res) {
    return res.json();
}).then(function(body) {
    console.log(body);
});

```

```ruby
require 'rest-client'
require 'json'

result = RestClient.put '/api/projects/{project_id}/property_definitions/{id}/',
  params: {
  }

p JSON.parse(result)

```

```python
import requests

r = requests.put('/api/projects/{project_id}/property_definitions/{id}/')

print(r.json())

```

```php
<?php

require 'vendor/autoload.php';

$client = new \GuzzleHttp\Client();

// Define array of request body.
$request_body = array();

try {
    $response = $client->request('PUT','/api/projects/{project_id}/property_definitions/{id}/', array(
        'headers' => $headers,
        'json' => $request_body,
       )
    );
    print_r($response->getBody()->getContents());
 }
 catch (\GuzzleHttp\Exception\BadResponseException $e) {
    // handle exception or api errors.
    print_r($e->getMessage());
 }

 // ...

```

```java
URL obj = new URL("/api/projects/{project_id}/property_definitions/{id}/");
HttpURLConnection con = (HttpURLConnection) obj.openConnection();
con.setRequestMethod("PUT");
int responseCode = con.getResponseCode();
BufferedReader in = new BufferedReader(
    new InputStreamReader(con.getInputStream()));
String inputLine;
StringBuffer response = new StringBuffer();
while ((inputLine = in.readLine()) != null) {
    response.append(inputLine);
}
in.close();
System.out.println(response.toString());

```

```go
package main

import (
       "bytes"
       "net/http"
)

func main() {

    data := bytes.NewBuffer([]byte{jsonReq})
    req, err := http.NewRequest("PUT", "/api/projects/{project_id}/property_definitions/{id}/", data)
    req.Header = headers

    client := &http.Client{}
    resp, err := client.Do(req)
    // ...
}

```

`PUT /api/projects/{project_id}/property_definitions/{id}/`

<h3 id="property_definitions_update-parameters">Parameters</h3>

|Name|In|Type|Required|Description|
|---|---|---|---|---|
|id|path|string|true|none|
|project_id|path|string|true|Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/.|

<h3 id="property_definitions_update-responses">Responses</h3>

|Status|Meaning|Description|Schema|
|---|---|---|---|
|200|[OK](https://tools.ietf.org/html/rfc7231#section-6.3.1)|No response body|None|

<aside class="success">
This operation does not require authentication
</aside>

## property_definitions_partial_update

<a id="opIdproperty_definitions_partial_update"></a>

> Code samples

```shell
# You can also use wget
curl -X PATCH /api/projects/{project_id}/property_definitions/{id}/

```

```http
PATCH /api/projects/{project_id}/property_definitions/{id}/ HTTP/1.1

```

```javascript

fetch('/api/projects/{project_id}/property_definitions/{id}/',
{
  method: 'PATCH'

})
.then(function(res) {
    return res.json();
}).then(function(body) {
    console.log(body);
});

```

```ruby
require 'rest-client'
require 'json'

result = RestClient.patch '/api/projects/{project_id}/property_definitions/{id}/',
  params: {
  }

p JSON.parse(result)

```

```python
import requests

r = requests.patch('/api/projects/{project_id}/property_definitions/{id}/')

print(r.json())

```

```php
<?php

require 'vendor/autoload.php';

$client = new \GuzzleHttp\Client();

// Define array of request body.
$request_body = array();

try {
    $response = $client->request('PATCH','/api/projects/{project_id}/property_definitions/{id}/', array(
        'headers' => $headers,
        'json' => $request_body,
       )
    );
    print_r($response->getBody()->getContents());
 }
 catch (\GuzzleHttp\Exception\BadResponseException $e) {
    // handle exception or api errors.
    print_r($e->getMessage());
 }

 // ...

```

```java
URL obj = new URL("/api/projects/{project_id}/property_definitions/{id}/");
HttpURLConnection con = (HttpURLConnection) obj.openConnection();
con.setRequestMethod("PATCH");
int responseCode = con.getResponseCode();
BufferedReader in = new BufferedReader(
    new InputStreamReader(con.getInputStream()));
String inputLine;
StringBuffer response = new StringBuffer();
while ((inputLine = in.readLine()) != null) {
    response.append(inputLine);
}
in.close();
System.out.println(response.toString());

```

```go
package main

import (
       "bytes"
       "net/http"
)

func main() {

    data := bytes.NewBuffer([]byte{jsonReq})
    req, err := http.NewRequest("PATCH", "/api/projects/{project_id}/property_definitions/{id}/", data)
    req.Header = headers

    client := &http.Client{}
    resp, err := client.Do(req)
    // ...
}

```

`PATCH /api/projects/{project_id}/property_definitions/{id}/`

<h3 id="property_definitions_partial_update-parameters">Parameters</h3>

|Name|In|Type|Required|Description|
|---|---|---|---|---|
|id|path|string|true|none|
|project_id|path|string|true|Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/.|

<h3 id="property_definitions_partial_update-responses">Responses</h3>

|Status|Meaning|Description|Schema|
|---|---|---|---|
|200|[OK](https://tools.ietf.org/html/rfc7231#section-6.3.1)|No response body|None|

<aside class="success">
This operation does not require authentication
</aside>

<h1 id="-session_recordings">session_recordings</h1>

## session_recordings_retrieve

<a id="opIdsession_recordings_retrieve"></a>

> Code samples

```shell
# You can also use wget
curl -X GET /api/projects/{project_id}/session_recordings/

```

```http
GET /api/projects/{project_id}/session_recordings/ HTTP/1.1

```

```javascript

fetch('/api/projects/{project_id}/session_recordings/',
{
  method: 'GET'

})
.then(function(res) {
    return res.json();
}).then(function(body) {
    console.log(body);
});

```

```ruby
require 'rest-client'
require 'json'

result = RestClient.get '/api/projects/{project_id}/session_recordings/',
  params: {
  }

p JSON.parse(result)

```

```python
import requests

r = requests.get('/api/projects/{project_id}/session_recordings/')

print(r.json())

```

```php
<?php

require 'vendor/autoload.php';

$client = new \GuzzleHttp\Client();

// Define array of request body.
$request_body = array();

try {
    $response = $client->request('GET','/api/projects/{project_id}/session_recordings/', array(
        'headers' => $headers,
        'json' => $request_body,
       )
    );
    print_r($response->getBody()->getContents());
 }
 catch (\GuzzleHttp\Exception\BadResponseException $e) {
    // handle exception or api errors.
    print_r($e->getMessage());
 }

 // ...

```

```java
URL obj = new URL("/api/projects/{project_id}/session_recordings/");
HttpURLConnection con = (HttpURLConnection) obj.openConnection();
con.setRequestMethod("GET");
int responseCode = con.getResponseCode();
BufferedReader in = new BufferedReader(
    new InputStreamReader(con.getInputStream()));
String inputLine;
StringBuffer response = new StringBuffer();
while ((inputLine = in.readLine()) != null) {
    response.append(inputLine);
}
in.close();
System.out.println(response.toString());

```

```go
package main

import (
       "bytes"
       "net/http"
)

func main() {

    data := bytes.NewBuffer([]byte{jsonReq})
    req, err := http.NewRequest("GET", "/api/projects/{project_id}/session_recordings/", data)
    req.Header = headers

    client := &http.Client{}
    resp, err := client.Do(req)
    // ...
}

```

`GET /api/projects/{project_id}/session_recordings/`

<h3 id="session_recordings_retrieve-parameters">Parameters</h3>

|Name|In|Type|Required|Description|
|---|---|---|---|---|
|project_id|path|string|true|Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/.|

<h3 id="session_recordings_retrieve-responses">Responses</h3>

|Status|Meaning|Description|Schema|
|---|---|---|---|
|200|[OK](https://tools.ietf.org/html/rfc7231#section-6.3.1)|No response body|None|

<aside class="success">
This operation does not require authentication
</aside>

## session_recordings_retrieve_2

<a id="opIdsession_recordings_retrieve_2"></a>

> Code samples

```shell
# You can also use wget
curl -X GET /api/projects/{project_id}/session_recordings/{id}/

```

```http
GET /api/projects/{project_id}/session_recordings/{id}/ HTTP/1.1

```

```javascript

fetch('/api/projects/{project_id}/session_recordings/{id}/',
{
  method: 'GET'

})
.then(function(res) {
    return res.json();
}).then(function(body) {
    console.log(body);
});

```

```ruby
require 'rest-client'
require 'json'

result = RestClient.get '/api/projects/{project_id}/session_recordings/{id}/',
  params: {
  }

p JSON.parse(result)

```

```python
import requests

r = requests.get('/api/projects/{project_id}/session_recordings/{id}/')

print(r.json())

```

```php
<?php

require 'vendor/autoload.php';

$client = new \GuzzleHttp\Client();

// Define array of request body.
$request_body = array();

try {
    $response = $client->request('GET','/api/projects/{project_id}/session_recordings/{id}/', array(
        'headers' => $headers,
        'json' => $request_body,
       )
    );
    print_r($response->getBody()->getContents());
 }
 catch (\GuzzleHttp\Exception\BadResponseException $e) {
    // handle exception or api errors.
    print_r($e->getMessage());
 }

 // ...

```

```java
URL obj = new URL("/api/projects/{project_id}/session_recordings/{id}/");
HttpURLConnection con = (HttpURLConnection) obj.openConnection();
con.setRequestMethod("GET");
int responseCode = con.getResponseCode();
BufferedReader in = new BufferedReader(
    new InputStreamReader(con.getInputStream()));
String inputLine;
StringBuffer response = new StringBuffer();
while ((inputLine = in.readLine()) != null) {
    response.append(inputLine);
}
in.close();
System.out.println(response.toString());

```

```go
package main

import (
       "bytes"
       "net/http"
)

func main() {

    data := bytes.NewBuffer([]byte{jsonReq})
    req, err := http.NewRequest("GET", "/api/projects/{project_id}/session_recordings/{id}/", data)
    req.Header = headers

    client := &http.Client{}
    resp, err := client.Do(req)
    // ...
}

```

`GET /api/projects/{project_id}/session_recordings/{id}/`

<h3 id="session_recordings_retrieve_2-parameters">Parameters</h3>

|Name|In|Type|Required|Description|
|---|---|---|---|---|
|id|path|string|true|none|
|project_id|path|string|true|Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/.|

<h3 id="session_recordings_retrieve_2-responses">Responses</h3>

|Status|Meaning|Description|Schema|
|---|---|---|---|
|200|[OK](https://tools.ietf.org/html/rfc7231#section-6.3.1)|No response body|None|

<aside class="success">
This operation does not require authentication
</aside>

## session_recordings_snapshots_retrieve

<a id="opIdsession_recordings_snapshots_retrieve"></a>

> Code samples

```shell
# You can also use wget
curl -X GET /api/projects/{project_id}/session_recordings/{id}/snapshots/

```

```http
GET /api/projects/{project_id}/session_recordings/{id}/snapshots/ HTTP/1.1

```

```javascript

fetch('/api/projects/{project_id}/session_recordings/{id}/snapshots/',
{
  method: 'GET'

})
.then(function(res) {
    return res.json();
}).then(function(body) {
    console.log(body);
});

```

```ruby
require 'rest-client'
require 'json'

result = RestClient.get '/api/projects/{project_id}/session_recordings/{id}/snapshots/',
  params: {
  }

p JSON.parse(result)

```

```python
import requests

r = requests.get('/api/projects/{project_id}/session_recordings/{id}/snapshots/')

print(r.json())

```

```php
<?php

require 'vendor/autoload.php';

$client = new \GuzzleHttp\Client();

// Define array of request body.
$request_body = array();

try {
    $response = $client->request('GET','/api/projects/{project_id}/session_recordings/{id}/snapshots/', array(
        'headers' => $headers,
        'json' => $request_body,
       )
    );
    print_r($response->getBody()->getContents());
 }
 catch (\GuzzleHttp\Exception\BadResponseException $e) {
    // handle exception or api errors.
    print_r($e->getMessage());
 }

 // ...

```

```java
URL obj = new URL("/api/projects/{project_id}/session_recordings/{id}/snapshots/");
HttpURLConnection con = (HttpURLConnection) obj.openConnection();
con.setRequestMethod("GET");
int responseCode = con.getResponseCode();
BufferedReader in = new BufferedReader(
    new InputStreamReader(con.getInputStream()));
String inputLine;
StringBuffer response = new StringBuffer();
while ((inputLine = in.readLine()) != null) {
    response.append(inputLine);
}
in.close();
System.out.println(response.toString());

```

```go
package main

import (
       "bytes"
       "net/http"
)

func main() {

    data := bytes.NewBuffer([]byte{jsonReq})
    req, err := http.NewRequest("GET", "/api/projects/{project_id}/session_recordings/{id}/snapshots/", data)
    req.Header = headers

    client := &http.Client{}
    resp, err := client.Do(req)
    // ...
}

```

`GET /api/projects/{project_id}/session_recordings/{id}/snapshots/`

<h3 id="session_recordings_snapshots_retrieve-parameters">Parameters</h3>

|Name|In|Type|Required|Description|
|---|---|---|---|---|
|id|path|string|true|none|
|project_id|path|string|true|Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/.|

<h3 id="session_recordings_snapshots_retrieve-responses">Responses</h3>

|Status|Meaning|Description|Schema|
|---|---|---|---|
|200|[OK](https://tools.ietf.org/html/rfc7231#section-6.3.1)|No response body|None|

<aside class="success">
This operation does not require authentication
</aside>

# Schemas

<h2 id="tocS_Action">Action</h2>
<!-- backwards compatibility -->
<a id="schemaaction"></a>
<a id="schema_Action"></a>
<a id="tocSaction"></a>
<a id="tocsaction"></a>

```json
{
  "id": 0,
  "name": "string",
  "post_to_slack": true,
  "slack_message_format": "string",
  "steps": [
    {
      "id": "string",
      "event": "string",
      "tag_name": "string",
      "text": "string",
      "href": "string",
      "selector": "string",
      "url": "string",
      "name": "string",
      "url_matching": "contains",
      "properties": {
        "property1": null,
        "property2": null
      }
    }
  ],
  "created_at": "2019-08-24T14:15:22Z",
  "deleted": true,
  "is_calculating": true,
  "last_calculated_at": "2019-08-24T14:15:22Z",
  "created_by": {
    "id": 0,
    "uuid": "095be615-a8ad-4c33-8e9c-c7612fbf6c9f",
    "distinct_id": "string",
    "first_name": "string",
    "email": "user@example.com"
  },
  "team_id": 0
}

```

### Properties

|Name|Type|Required|Restrictions|Description|
|---|---|---|---|---|
|id|integer|true|read-only|none|
|name|string¦null|false|none|none|
|post_to_slack|boolean|false|none|none|
|slack_message_format|string|false|none|none|
|steps|[[ActionStep](#schemaactionstep)]|false|none|none|
|created_at|string(date-time)|true|read-only|none|
|deleted|boolean|false|none|none|
|is_calculating|boolean|true|read-only|none|
|last_calculated_at|string(date-time)|false|none|none|
|created_by|[UserBasic](#schemauserbasic)|true|read-only|none|
|team_id|integer|true|read-only|none|

<h2 id="tocS_ActionStep">ActionStep</h2>
<!-- backwards compatibility -->
<a id="schemaactionstep"></a>
<a id="schema_ActionStep"></a>
<a id="tocSactionstep"></a>
<a id="tocsactionstep"></a>

```json
{
  "id": "string",
  "event": "string",
  "tag_name": "string",
  "text": "string",
  "href": "string",
  "selector": "string",
  "url": "string",
  "name": "string",
  "url_matching": "contains",
  "properties": {
    "property1": null,
    "property2": null
  }
}

```

### Properties

|Name|Type|Required|Restrictions|Description|
|---|---|---|---|---|
|id|string|false|none|none|
|event|string¦null|false|none|none|
|tag_name|string¦null|false|none|none|
|text|string¦null|false|none|none|
|href|string¦null|false|none|none|
|selector|string¦null|false|none|none|
|url|string¦null|false|none|none|
|name|string¦null|false|none|none|
|url_matching|string¦null|false|none|none|
|properties|object¦null|false|none|none|
|» **additionalProperties**|any|false|none|none|

#### Enumerated Values

|Property|Value|
|---|---|
|url_matching|contains|
|url_matching|regex|
|url_matching|exact|
|url_matching||
|url_matching|null|

<h2 id="tocS_Annotation">Annotation</h2>
<!-- backwards compatibility -->
<a id="schemaannotation"></a>
<a id="schema_Annotation"></a>
<a id="tocSannotation"></a>
<a id="tocsannotation"></a>

```json
{
  "id": 0,
  "content": "string",
  "date_marker": "2019-08-24T14:15:22Z",
  "creation_type": "USR",
  "dashboard_item": 0,
  "created_by": {
    "id": 0,
    "uuid": "095be615-a8ad-4c33-8e9c-c7612fbf6c9f",
    "distinct_id": "string",
    "first_name": "string",
    "email": "user@example.com"
  },
  "created_at": "2019-08-24T14:15:22Z",
  "updated_at": "2019-08-24T14:15:22Z",
  "deleted": true,
  "scope": "dashboard_item"
}

```

### Properties

|Name|Type|Required|Restrictions|Description|
|---|---|---|---|---|
|id|integer|true|read-only|none|
|content|string¦null|false|none|none|
|date_marker|string(date-time)¦null|false|none|none|
|creation_type|string|true|read-only|none|
|dashboard_item|integer¦null|false|none|none|
|created_by|[UserBasic](#schemauserbasic)|true|read-only|none|
|created_at|string(date-time)|true|read-only|none|
|updated_at|string(date-time)|true|read-only|none|
|deleted|boolean|false|none|none|
|scope|string|false|none|none|

#### Enumerated Values

|Property|Value|
|---|---|
|creation_type|USR|
|creation_type|GIT|
|scope|dashboard_item|
|scope|project|
|scope|organization|

<h2 id="tocS_ClickhouseCohort">ClickhouseCohort</h2>
<!-- backwards compatibility -->
<a id="schemaclickhousecohort"></a>
<a id="schema_ClickhouseCohort"></a>
<a id="tocSclickhousecohort"></a>
<a id="tocsclickhousecohort"></a>

```json
{
  "id": 0,
  "name": "string",
  "description": "string",
  "groups": {
    "property1": null,
    "property2": null
  },
  "deleted": true,
  "is_calculating": true,
  "created_by": {
    "id": 0,
    "uuid": "095be615-a8ad-4c33-8e9c-c7612fbf6c9f",
    "distinct_id": "string",
    "first_name": "string",
    "email": "user@example.com"
  },
  "created_at": "2019-08-24T14:15:22Z",
  "last_calculation": "2019-08-24T14:15:22Z",
  "errors_calculating": 0,
  "count": 0,
  "is_static": true
}

```

### Properties

|Name|Type|Required|Restrictions|Description|
|---|---|---|---|---|
|id|integer|true|read-only|none|
|name|string¦null|false|none|none|
|description|string|false|none|none|
|groups|object|false|none|none|
|» **additionalProperties**|any|false|none|none|
|deleted|boolean|false|none|none|
|is_calculating|boolean|true|read-only|none|
|created_by|[UserBasic](#schemauserbasic)|true|read-only|none|
|created_at|string(date-time)|true|read-only|none|
|last_calculation|string(date-time)|true|read-only|none|
|errors_calculating|integer|true|read-only|none|
|count|integer¦null|true|read-only|none|
|is_static|boolean|false|none|none|

<h2 id="tocS_ClickhouseEvent">ClickhouseEvent</h2>
<!-- backwards compatibility -->
<a id="schemaclickhouseevent"></a>
<a id="schema_ClickhouseEvent"></a>
<a id="tocSclickhouseevent"></a>
<a id="tocsclickhouseevent"></a>

```json
{
  "id": "string",
  "distinct_id": "string",
  "properties": "string",
  "event": "string",
  "timestamp": "string",
  "person": "string",
  "elements": "string",
  "elements_chain": "string"
}

```

### Properties

|Name|Type|Required|Restrictions|Description|
|---|---|---|---|---|
|id|string|true|read-only|none|
|distinct_id|string|true|read-only|none|
|properties|string|true|read-only|none|
|event|string|true|read-only|none|
|timestamp|string|true|read-only|none|
|person|string|true|read-only|none|
|elements|string|true|read-only|none|
|elements_chain|string|true|read-only|none|

<h2 id="tocS_Dashboard">Dashboard</h2>
<!-- backwards compatibility -->
<a id="schemadashboard"></a>
<a id="schema_Dashboard"></a>
<a id="tocSdashboard"></a>
<a id="tocsdashboard"></a>

```json
{
  "id": 0,
  "name": "string",
  "description": "string",
  "pinned": true,
  "items": "string",
  "created_at": "2019-08-24T14:15:22Z",
  "created_by": {
    "id": 0,
    "uuid": "095be615-a8ad-4c33-8e9c-c7612fbf6c9f",
    "distinct_id": "string",
    "first_name": "string",
    "email": "user@example.com"
  },
  "is_shared": true,
  "share_token": "string",
  "deleted": true,
  "creation_mode": "default",
  "use_template": "string",
  "use_dashboard": 0,
  "filters": {
    "property1": null,
    "property2": null
  },
  "tags": [
    "string"
  ]
}

```

### Properties

|Name|Type|Required|Restrictions|Description|
|---|---|---|---|---|
|id|integer|true|read-only|none|
|name|string¦null|false|none|none|
|description|string|false|none|none|
|pinned|boolean|false|none|none|
|items|string|true|read-only|none|
|created_at|string(date-time)|true|read-only|none|
|created_by|[UserBasic](#schemauserbasic)|true|read-only|none|
|is_shared|boolean|false|none|none|
|share_token|string¦null|false|none|none|
|deleted|boolean|false|none|none|
|creation_mode|string|true|read-only|none|
|use_template|string|false|write-only|none|
|use_dashboard|integer¦null|false|write-only|none|
|filters|object|false|none|none|
|» **additionalProperties**|any|false|none|none|
|tags|[string]|false|none|none|

#### Enumerated Values

|Property|Value|
|---|---|
|creation_mode|default|
|creation_mode|template|
|creation_mode|duplicate|

<h2 id="tocS_Experiment">Experiment</h2>
<!-- backwards compatibility -->
<a id="schemaexperiment"></a>
<a id="schema_Experiment"></a>
<a id="tocSexperiment"></a>
<a id="tocsexperiment"></a>

```json
{
  "id": 0,
  "name": "string",
  "description": "string",
  "start_date": "2019-08-24T14:15:22Z",
  "end_date": "2019-08-24T14:15:22Z",
  "feature_flag_key": "string",
  "parameters": {
    "property1": null,
    "property2": null
  },
  "secondary_metrics": {
    "property1": null,
    "property2": null
  },
  "filters": {
    "property1": null,
    "property2": null
  },
  "archived": true,
  "created_by": {
    "id": 0,
    "uuid": "095be615-a8ad-4c33-8e9c-c7612fbf6c9f",
    "distinct_id": "string",
    "first_name": "string",
    "email": "user@example.com"
  },
  "created_at": "2019-08-24T14:15:22Z",
  "updated_at": "2019-08-24T14:15:22Z"
}

```

### Properties

|Name|Type|Required|Restrictions|Description|
|---|---|---|---|---|
|id|integer|true|read-only|none|
|name|string|true|none|none|
|description|string¦null|false|none|none|
|start_date|string(date-time)¦null|false|none|none|
|end_date|string(date-time)¦null|false|none|none|
|feature_flag_key|string|true|none|none|
|parameters|object¦null|false|none|none|
|» **additionalProperties**|any|false|none|none|
|secondary_metrics|object¦null|false|none|none|
|» **additionalProperties**|any|false|none|none|
|filters|object|false|none|none|
|» **additionalProperties**|any|false|none|none|
|archived|boolean|false|none|none|
|created_by|[UserBasic](#schemauserbasic)|true|read-only|none|
|created_at|string(date-time)|true|read-only|none|
|updated_at|string(date-time)|true|read-only|none|

<h2 id="tocS_FeatureFlag">FeatureFlag</h2>
<!-- backwards compatibility -->
<a id="schemafeatureflag"></a>
<a id="schema_FeatureFlag"></a>
<a id="tocSfeatureflag"></a>
<a id="tocsfeatureflag"></a>

```json
{
  "id": 0,
  "name": "string",
  "key": "string",
  "filters": {
    "property1": null,
    "property2": null
  },
  "deleted": true,
  "active": true,
  "created_by": {
    "id": 0,
    "uuid": "095be615-a8ad-4c33-8e9c-c7612fbf6c9f",
    "distinct_id": "string",
    "first_name": "string",
    "email": "user@example.com"
  },
  "created_at": "2019-08-24T14:15:22Z",
  "is_simple_flag": true,
  "rollout_percentage": 0
}

```

### Properties

|Name|Type|Required|Restrictions|Description|
|---|---|---|---|---|
|id|integer|true|read-only|none|
|name|string|false|none|none|
|key|string|true|none|none|
|filters|object|false|none|none|
|» **additionalProperties**|any|false|none|none|
|deleted|boolean|false|none|none|
|active|boolean|false|none|none|
|created_by|[UserBasic](#schemauserbasic)|true|read-only|none|
|created_at|string(date-time)|false|none|none|
|is_simple_flag|boolean|true|read-only|none|
|rollout_percentage|integer¦null|true|read-only|none|

<h2 id="tocS_FilterAction">FilterAction</h2>
<!-- backwards compatibility -->
<a id="schemafilteraction"></a>
<a id="schema_FilterAction"></a>
<a id="tocSfilteraction"></a>
<a id="tocsfilteraction"></a>

```json
{
  "id": "string",
  "properties": [
    {
      "key": "string",
      "value": "string",
      "operator": "exact",
      "type": "event"
    }
  ]
}

```

### Properties

|Name|Type|Required|Restrictions|Description|
|---|---|---|---|---|
|id|string|true|none|Name of the event to filter on. For example `$pageview` or `user sign up`.|
|properties|[[Property](#schemaproperty)]|false|none|none|

<h2 id="tocS_FilterEvent">FilterEvent</h2>
<!-- backwards compatibility -->
<a id="schemafilterevent"></a>
<a id="schema_FilterEvent"></a>
<a id="tocSfilterevent"></a>
<a id="tocsfilterevent"></a>

```json
{
  "id": "string",
  "properties": [
    {
      "key": "string",
      "value": "string",
      "operator": "exact",
      "type": "event"
    }
  ]
}

```

### Properties

|Name|Type|Required|Restrictions|Description|
|---|---|---|---|---|
|id|string|true|none|Name of the event to filter on. For example `$pageview` or `user sign up`.|
|properties|[[Property](#schemaproperty)]|false|none|none|

<h2 id="tocS_Funnel">Funnel</h2>
<!-- backwards compatibility -->
<a id="schemafunnel"></a>
<a id="schema_Funnel"></a>
<a id="tocSfunnel"></a>
<a id="tocsfunnel"></a>

```json
{
  "events": [
    {
      "id": "string",
      "properties": [
        {
          "key": "string",
          "value": "string",
          "operator": "exact",
          "type": "event"
        }
      ]
    }
  ],
  "actions": [
    {
      "id": "string",
      "properties": [
        {
          "key": "string",
          "value": "string",
          "operator": "exact",
          "type": "event"
        }
      ]
    }
  ],
  "properties": [
    {
      "key": "string",
      "value": "string",
      "operator": "exact",
      "type": "event"
    }
  ],
  "filter_test_accounts": false,
  "date_from": "-7d",
  "date_to": "-7d",
  "breakdown": "string",
  "breakdown_type": "event",
  "funnel_window_interval": 14,
  "funnel_window_interval_type": "DAY",
  "funnel_viz_type": "trends",
  "funnel_order_type": "strict",
  "exclusions": [
    {
      "id": "string",
      "properties": [
        {
          "key": "string",
          "value": "string",
          "operator": "exact",
          "type": "event"
        }
      ],
      "funnel_from_step": 0,
      "funnel_to_step": 1
    }
  ],
  "aggregation_group_type_index": 0,
  "breakdown_limit": 10,
  "funnel_window_days": 14
}

```

### Properties

|Name|Type|Required|Restrictions|Description|
|---|---|---|---|---|
|events|[[FilterEvent](#schemafilterevent)]|false|none|Events to filter on. One of `events` or `actions` is required.|
|actions|[[FilterAction](#schemafilteraction)]|false|none|Actions to filter on. One of `events` or `actions` is required.|
|properties|[[Property](#schemaproperty)]|false|none|none|
|filter_test_accounts|boolean|false|none|Whether to filter out internal and test accounts. See "project settings" in your PostHog account for the filters.|
|date_from|string|false|none|What date to filter the results from. Can either be a date `2021-01-01`, or a relative date, like `-7d` for last seven days, `-1m` for last month, `mStart` for start of the month or `yStart` for the start of the year.|
|date_to|string|false|none|What date to filter the results to. Can either be a date `2021-01-01`, or a relative date, like `-7d` for last seven days, `-1m` for last month, `mStart` for start of the month or `yStart` for the start of the year.|
|breakdown|string|false|none|A property to break down on. You can select the type of the property with breakdown_type.|
|breakdown_type|string|false|none|Type of property to break down on.|
|funnel_window_interval|integer|false|none|Funnel window size. Set in combination with funnel_window_interval, so defaults to 'days'.|
|funnel_window_interval_type|string|false|none|The type of interval. Used in combination with `funnel_window_intervals`.|
|funnel_viz_type|string|false|none|The visualisation type.<br>- `steps` Track instances progress between steps of the funnel<br>- `trends` Track how this funnel's conversion rate is trending over time.<br>- `time_to_convert` Track how long it takes for instances to convert|
|funnel_order_type|string|false|none|- `ordered` - Step B must happen after Step A, but any number events can happen between A and B.<br>- `strict` - Step B must happen directly after Step A without any events in between.<br>- `unordered` - Steps can be completed in any sequence.|
|exclusions|[[FunnelExclusion](#schemafunnelexclusion)]|false|none|Exclude users/groups that completed the specified event between two specific steps. Note that these users/groups will be completely excluded from the entire funnel.|
|aggregation_group_type_index|integer|false|none|Aggregate by users or by groups. `0` means user, `>0` means a group. See interface for the corresponding ID of the group.|
|breakdown_limit|integer|false|none|none|
|funnel_window_days|integer|false|none|(DEPRECATED) Funnel window size in days.|

#### Enumerated Values

|Property|Value|
|---|---|
|breakdown_type|event|
|breakdown_type|person|
|breakdown_type|cohort|
|breakdown_type|group|
|funnel_window_interval_type|DAY|
|funnel_window_interval_type|MINUTE|
|funnel_window_interval_type|HOUR|
|funnel_window_interval_type|WEEK|
|funnel_window_interval_type|MONTH|
|funnel_viz_type|trends|
|funnel_viz_type|time_to_convert|
|funnel_viz_type|steps|
|funnel_order_type|strict|
|funnel_order_type|unordered|
|funnel_order_type|ordered|

<h2 id="tocS_FunnelExclusion">FunnelExclusion</h2>
<!-- backwards compatibility -->
<a id="schemafunnelexclusion"></a>
<a id="schema_FunnelExclusion"></a>
<a id="tocSfunnelexclusion"></a>
<a id="tocsfunnelexclusion"></a>

```json
{
  "id": "string",
  "properties": [
    {
      "key": "string",
      "value": "string",
      "operator": "exact",
      "type": "event"
    }
  ],
  "funnel_from_step": 0,
  "funnel_to_step": 1
}

```

### Properties

|Name|Type|Required|Restrictions|Description|
|---|---|---|---|---|
|id|string|true|none|Name of the event to filter on. For example `$pageview` or `user sign up`.|
|properties|[[Property](#schemaproperty)]|false|none|none|
|funnel_from_step|integer|false|none|none|
|funnel_to_step|integer|false|none|none|

<h2 id="tocS_FunnelStepsResult">FunnelStepsResult</h2>
<!-- backwards compatibility -->
<a id="schemafunnelstepsresult"></a>
<a id="schema_FunnelStepsResult"></a>
<a id="tocSfunnelstepsresult"></a>
<a id="tocsfunnelstepsresult"></a>

```json
{
  "count": 0,
  "action_id": "string",
  "average_conversion_time": 0,
  "median_conversion_time": 0,
  "converted_people_url": "string",
  "dropped_people_url": "string",
  "order": "string"
}

```

### Properties

|Name|Type|Required|Restrictions|Description|
|---|---|---|---|---|
|count|integer|true|none|Number of people in this step.|
|action_id|string|true|none|Corresponds to the `id` of the entities passed through to `events` or `actions`.|
|average_conversion_time|number(float)|true|none|Average conversion time of person or groups between steps. `null` for the first step.|
|median_conversion_time|number(float)|true|none|Median conversion time of person or groups between steps. `null` for the first step.|
|converted_people_url|string|true|none|Path of a URL to get a list of people that converted after this step. In this format: `/api/person/funnel?...`|
|dropped_people_url|string|true|none|Path of a URL to get a list of people that dropped after this step. In this format: `/api/person/funnel?...`|
|order|string|true|none|Order of this step in the funnel. The API should return the steps in order anyway.|

<h2 id="tocS_FunnelStepsResults">FunnelStepsResults</h2>
<!-- backwards compatibility -->
<a id="schemafunnelstepsresults"></a>
<a id="schema_FunnelStepsResults"></a>
<a id="tocSfunnelstepsresults"></a>
<a id="tocsfunnelstepsresults"></a>

```json
{
  "is_cached": true,
  "last_refresh": "2019-08-24T14:15:22Z",
  "result": [
    {
      "count": 0,
      "action_id": "string",
      "average_conversion_time": 0,
      "median_conversion_time": 0,
      "converted_people_url": "string",
      "dropped_people_url": "string",
      "order": "string"
    }
  ]
}

```

### Properties

|Name|Type|Required|Restrictions|Description|
|---|---|---|---|---|
|is_cached|boolean|true|none|Whether the result is cached. To force a refresh, pass ?refresh=true|
|last_refresh|string(date-time)|true|none|If the result is cached, when it was last refreshed.|
|result|[[FunnelStepsResult](#schemafunnelstepsresult)]|true|none|none|

<h2 id="tocS_GenericInsights">GenericInsights</h2>
<!-- backwards compatibility -->
<a id="schemagenericinsights"></a>
<a id="schema_GenericInsights"></a>
<a id="tocSgenericinsights"></a>
<a id="tocsgenericinsights"></a>

```json
{
  "events": [
    {
      "id": "string",
      "properties": [
        {
          "key": "string",
          "value": "string",
          "operator": "exact",
          "type": "event"
        }
      ]
    }
  ],
  "actions": [
    {
      "id": "string",
      "properties": [
        {
          "key": "string",
          "value": "string",
          "operator": "exact",
          "type": "event"
        }
      ]
    }
  ],
  "properties": [
    {
      "key": "string",
      "value": "string",
      "operator": "exact",
      "type": "event"
    }
  ],
  "filter_test_accounts": false,
  "date_from": "-7d",
  "date_to": "-7d"
}

```

### Properties

|Name|Type|Required|Restrictions|Description|
|---|---|---|---|---|
|events|[[FilterEvent](#schemafilterevent)]|false|none|Events to filter on. One of `events` or `actions` is required.|
|actions|[[FilterAction](#schemafilteraction)]|false|none|Actions to filter on. One of `events` or `actions` is required.|
|properties|[[Property](#schemaproperty)]|false|none|none|
|filter_test_accounts|boolean|false|none|Whether to filter out internal and test accounts. See "project settings" in your PostHog account for the filters.|
|date_from|string|false|none|What date to filter the results from. Can either be a date `2021-01-01`, or a relative date, like `-7d` for last seven days, `-1m` for last month, `mStart` for start of the month or `yStart` for the start of the year.|
|date_to|string|false|none|What date to filter the results to. Can either be a date `2021-01-01`, or a relative date, like `-7d` for last seven days, `-1m` for last month, `mStart` for start of the month or `yStart` for the start of the year.|

<h2 id="tocS_Group">Group</h2>
<!-- backwards compatibility -->
<a id="schemagroup"></a>
<a id="schema_Group"></a>
<a id="tocSgroup"></a>
<a id="tocsgroup"></a>

```json
{
  "group_type_index": -2147483648,
  "group_key": "string",
  "group_properties": {
    "property1": null,
    "property2": null
  },
  "created_at": "2019-08-24T14:15:22Z"
}

```

### Properties

|Name|Type|Required|Restrictions|Description|
|---|---|---|---|---|
|group_type_index|integer|true|none|none|
|group_key|string|true|none|none|
|group_properties|object|false|none|none|
|» **additionalProperties**|any|false|none|none|
|created_at|string(date-time)|true|read-only|none|

<h2 id="tocS_GroupType">GroupType</h2>
<!-- backwards compatibility -->
<a id="schemagrouptype"></a>
<a id="schema_GroupType"></a>
<a id="tocSgrouptype"></a>
<a id="tocsgrouptype"></a>

```json
{
  "group_type": "string",
  "group_type_index": 0,
  "name_singular": "string",
  "name_plural": "string"
}

```

### Properties

|Name|Type|Required|Restrictions|Description|
|---|---|---|---|---|
|group_type|string|true|read-only|none|
|group_type_index|integer|true|read-only|none|
|name_singular|string¦null|false|none|none|
|name_plural|string¦null|false|none|none|

<h2 id="tocS_Hook">Hook</h2>
<!-- backwards compatibility -->
<a id="schemahook"></a>
<a id="schema_Hook"></a>
<a id="tocShook"></a>
<a id="tocshook"></a>

```json
{
  "id": "string",
  "created": "2019-08-24T14:15:22Z",
  "updated": "2019-08-24T14:15:22Z",
  "event": "string",
  "target": "http://example.com",
  "resource_id": -2147483648,
  "team": 0
}

```

### Properties

|Name|Type|Required|Restrictions|Description|
|---|---|---|---|---|
|id|string|false|none|none|
|created|string(date-time)|true|read-only|none|
|updated|string(date-time)|true|read-only|none|
|event|string|true|none|none|
|target|string(uri)|true|none|none|
|resource_id|integer¦null|false|none|none|
|team|integer|true|read-only|none|

<h2 id="tocS_Insight">Insight</h2>
<!-- backwards compatibility -->
<a id="schemainsight"></a>
<a id="schema_Insight"></a>
<a id="tocSinsight"></a>
<a id="tocsinsight"></a>

```json
{
  "id": 0,
  "short_id": "string",
  "name": "string",
  "filters": {
    "property1": null,
    "property2": null
  },
  "filters_hash": "string",
  "order": -2147483648,
  "deleted": true,
  "dashboard": 0,
  "dive_dashboard": 0,
  "layouts": {
    "property1": null,
    "property2": null
  },
  "color": "string",
  "last_refresh": "string",
  "refreshing": true,
  "result": "string",
  "created_at": "2019-08-24T14:15:22Z",
  "description": "string",
  "updated_at": "2019-08-24T14:15:22Z",
  "tags": [
    "string"
  ],
  "favorited": true,
  "saved": true,
  "created_by": {
    "id": 0,
    "uuid": "095be615-a8ad-4c33-8e9c-c7612fbf6c9f",
    "distinct_id": "string",
    "first_name": "string",
    "email": "user@example.com"
  },
  "is_sample": true
}

```

Simplified serializer to speed response times when loading large amounts of objects.

### Properties

|Name|Type|Required|Restrictions|Description|
|---|---|---|---|---|
|id|integer|true|read-only|none|
|short_id|string|true|read-only|none|
|name|string¦null|false|none|none|
|filters|object|false|none|none|
|» **additionalProperties**|any|false|none|none|
|filters_hash|string¦null|false|none|none|
|order|integer¦null|false|none|none|
|deleted|boolean|false|none|none|
|dashboard|integer¦null|false|none|none|
|dive_dashboard|integer¦null|false|none|none|
|layouts|object|false|none|none|
|» **additionalProperties**|any|false|none|none|
|color|string¦null|false|none|none|
|last_refresh|string|true|read-only|none|
|refreshing|boolean|false|none|none|
|result|string|true|read-only|none|
|created_at|string(date-time)|true|read-only|none|
|description|string¦null|false|none|none|
|updated_at|string(date-time)|true|read-only|none|
|tags|[string]|false|none|none|
|favorited|boolean|false|none|none|
|saved|boolean|false|none|none|
|created_by|[UserBasic](#schemauserbasic)|true|read-only|none|
|is_sample|boolean|true|read-only|none|

<h2 id="tocS_OrganizationInvite">OrganizationInvite</h2>
<!-- backwards compatibility -->
<a id="schemaorganizationinvite"></a>
<a id="schema_OrganizationInvite"></a>
<a id="tocSorganizationinvite"></a>
<a id="tocsorganizationinvite"></a>

```json
{
  "id": "497f6eca-6276-4993-bfeb-53cbbbba6f08",
  "target_email": "user@example.com",
  "first_name": "string",
  "emailing_attempt_made": true,
  "is_expired": true,
  "created_by": {
    "id": 0,
    "uuid": "095be615-a8ad-4c33-8e9c-c7612fbf6c9f",
    "distinct_id": "string",
    "first_name": "string",
    "email": "user@example.com"
  },
  "created_at": "2019-08-24T14:15:22Z",
  "updated_at": "2019-08-24T14:15:22Z"
}

```

### Properties

|Name|Type|Required|Restrictions|Description|
|---|---|---|---|---|
|id|string(uuid)|true|read-only|none|
|target_email|string(email)|true|none|none|
|first_name|string|false|none|none|
|emailing_attempt_made|boolean|true|read-only|none|
|is_expired|boolean|true|read-only|none|
|created_by|[UserBasic](#schemauserbasic)|true|read-only|none|
|created_at|string(date-time)|true|read-only|none|
|updated_at|string(date-time)|true|read-only|none|

<h2 id="tocS_OrganizationMember">OrganizationMember</h2>
<!-- backwards compatibility -->
<a id="schemaorganizationmember"></a>
<a id="schema_OrganizationMember"></a>
<a id="tocSorganizationmember"></a>
<a id="tocsorganizationmember"></a>

```json
{
  "id": "497f6eca-6276-4993-bfeb-53cbbbba6f08",
  "user": {
    "id": 0,
    "uuid": "095be615-a8ad-4c33-8e9c-c7612fbf6c9f",
    "distinct_id": "string",
    "first_name": "string",
    "email": "user@example.com"
  },
  "level": 1,
  "joined_at": "2019-08-24T14:15:22Z",
  "updated_at": "2019-08-24T14:15:22Z"
}

```

### Properties

|Name|Type|Required|Restrictions|Description|
|---|---|---|---|---|
|id|string(uuid)|true|read-only|none|
|user|[UserBasic](#schemauserbasic)|true|read-only|none|
|level|integer|false|none|none|
|joined_at|string(date-time)|true|read-only|none|
|updated_at|string(date-time)|true|read-only|none|

#### Enumerated Values

|Property|Value|
|---|---|
|level|1|
|level|8|
|level|15|

<h2 id="tocS_PaginatedActionList">PaginatedActionList</h2>
<!-- backwards compatibility -->
<a id="schemapaginatedactionlist"></a>
<a id="schema_PaginatedActionList"></a>
<a id="tocSpaginatedactionlist"></a>
<a id="tocspaginatedactionlist"></a>

```json
{
  "count": 123,
  "next": "http://api.example.org/accounts/?offset=400&limit=100",
  "previous": "http://api.example.org/accounts/?offset=200&limit=100",
  "results": [
    {
      "id": 0,
      "name": "string",
      "post_to_slack": true,
      "slack_message_format": "string",
      "steps": [
        {
          "id": "string",
          "event": "string",
          "tag_name": "string",
          "text": "string",
          "href": "string",
          "selector": "string",
          "url": "string",
          "name": "string",
          "url_matching": "contains",
          "properties": {
            "property1": null,
            "property2": null
          }
        }
      ],
      "created_at": "2019-08-24T14:15:22Z",
      "deleted": true,
      "is_calculating": true,
      "last_calculated_at": "2019-08-24T14:15:22Z",
      "created_by": {
        "id": 0,
        "uuid": "095be615-a8ad-4c33-8e9c-c7612fbf6c9f",
        "distinct_id": "string",
        "first_name": "string",
        "email": "user@example.com"
      },
      "team_id": 0
    }
  ]
}

```

### Properties

|Name|Type|Required|Restrictions|Description|
|---|---|---|---|---|
|count|integer|false|none|none|
|next|string(uri)¦null|false|none|none|
|previous|string(uri)¦null|false|none|none|
|results|[[Action](#schemaaction)]|false|none|none|

<h2 id="tocS_PaginatedAnnotationList">PaginatedAnnotationList</h2>
<!-- backwards compatibility -->
<a id="schemapaginatedannotationlist"></a>
<a id="schema_PaginatedAnnotationList"></a>
<a id="tocSpaginatedannotationlist"></a>
<a id="tocspaginatedannotationlist"></a>

```json
{
  "count": 123,
  "next": "http://api.example.org/accounts/?offset=400&limit=100",
  "previous": "http://api.example.org/accounts/?offset=200&limit=100",
  "results": [
    {
      "id": 0,
      "content": "string",
      "date_marker": "2019-08-24T14:15:22Z",
      "creation_type": "USR",
      "dashboard_item": 0,
      "created_by": {
        "id": 0,
        "uuid": "095be615-a8ad-4c33-8e9c-c7612fbf6c9f",
        "distinct_id": "string",
        "first_name": "string",
        "email": "user@example.com"
      },
      "created_at": "2019-08-24T14:15:22Z",
      "updated_at": "2019-08-24T14:15:22Z",
      "deleted": true,
      "scope": "dashboard_item"
    }
  ]
}

```

### Properties

|Name|Type|Required|Restrictions|Description|
|---|---|---|---|---|
|count|integer|false|none|none|
|next|string(uri)¦null|false|none|none|
|previous|string(uri)¦null|false|none|none|
|results|[[Annotation](#schemaannotation)]|false|none|none|

<h2 id="tocS_PaginatedClickhouseCohortList">PaginatedClickhouseCohortList</h2>
<!-- backwards compatibility -->
<a id="schemapaginatedclickhousecohortlist"></a>
<a id="schema_PaginatedClickhouseCohortList"></a>
<a id="tocSpaginatedclickhousecohortlist"></a>
<a id="tocspaginatedclickhousecohortlist"></a>

```json
{
  "count": 123,
  "next": "http://api.example.org/accounts/?offset=400&limit=100",
  "previous": "http://api.example.org/accounts/?offset=200&limit=100",
  "results": [
    {
      "id": 0,
      "name": "string",
      "description": "string",
      "groups": {
        "property1": null,
        "property2": null
      },
      "deleted": true,
      "is_calculating": true,
      "created_by": {
        "id": 0,
        "uuid": "095be615-a8ad-4c33-8e9c-c7612fbf6c9f",
        "distinct_id": "string",
        "first_name": "string",
        "email": "user@example.com"
      },
      "created_at": "2019-08-24T14:15:22Z",
      "last_calculation": "2019-08-24T14:15:22Z",
      "errors_calculating": 0,
      "count": 0,
      "is_static": true
    }
  ]
}

```

### Properties

|Name|Type|Required|Restrictions|Description|
|---|---|---|---|---|
|count|integer|false|none|none|
|next|string(uri)¦null|false|none|none|
|previous|string(uri)¦null|false|none|none|
|results|[[ClickhouseCohort](#schemaclickhousecohort)]|false|none|none|

<h2 id="tocS_PaginatedClickhouseEventList">PaginatedClickhouseEventList</h2>
<!-- backwards compatibility -->
<a id="schemapaginatedclickhouseeventlist"></a>
<a id="schema_PaginatedClickhouseEventList"></a>
<a id="tocSpaginatedclickhouseeventlist"></a>
<a id="tocspaginatedclickhouseeventlist"></a>

```json
{
  "count": 123,
  "next": "http://api.example.org/accounts/?offset=400&limit=100",
  "previous": "http://api.example.org/accounts/?offset=200&limit=100",
  "results": [
    {
      "id": "string",
      "distinct_id": "string",
      "properties": "string",
      "event": "string",
      "timestamp": "string",
      "person": "string",
      "elements": "string",
      "elements_chain": "string"
    }
  ]
}

```

### Properties

|Name|Type|Required|Restrictions|Description|
|---|---|---|---|---|
|count|integer|false|none|none|
|next|string(uri)¦null|false|none|none|
|previous|string(uri)¦null|false|none|none|
|results|[[ClickhouseEvent](#schemaclickhouseevent)]|false|none|none|

<h2 id="tocS_PaginatedDashboardList">PaginatedDashboardList</h2>
<!-- backwards compatibility -->
<a id="schemapaginateddashboardlist"></a>
<a id="schema_PaginatedDashboardList"></a>
<a id="tocSpaginateddashboardlist"></a>
<a id="tocspaginateddashboardlist"></a>

```json
{
  "count": 123,
  "next": "http://api.example.org/accounts/?offset=400&limit=100",
  "previous": "http://api.example.org/accounts/?offset=200&limit=100",
  "results": [
    {
      "id": 0,
      "name": "string",
      "description": "string",
      "pinned": true,
      "items": "string",
      "created_at": "2019-08-24T14:15:22Z",
      "created_by": {
        "id": 0,
        "uuid": "095be615-a8ad-4c33-8e9c-c7612fbf6c9f",
        "distinct_id": "string",
        "first_name": "string",
        "email": "user@example.com"
      },
      "is_shared": true,
      "share_token": "string",
      "deleted": true,
      "creation_mode": "default",
      "use_template": "string",
      "use_dashboard": 0,
      "filters": {
        "property1": null,
        "property2": null
      },
      "tags": [
        "string"
      ]
    }
  ]
}

```

### Properties

|Name|Type|Required|Restrictions|Description|
|---|---|---|---|---|
|count|integer|false|none|none|
|next|string(uri)¦null|false|none|none|
|previous|string(uri)¦null|false|none|none|
|results|[[Dashboard](#schemadashboard)]|false|none|none|

<h2 id="tocS_PaginatedExperimentList">PaginatedExperimentList</h2>
<!-- backwards compatibility -->
<a id="schemapaginatedexperimentlist"></a>
<a id="schema_PaginatedExperimentList"></a>
<a id="tocSpaginatedexperimentlist"></a>
<a id="tocspaginatedexperimentlist"></a>

```json
{
  "count": 123,
  "next": "http://api.example.org/accounts/?offset=400&limit=100",
  "previous": "http://api.example.org/accounts/?offset=200&limit=100",
  "results": [
    {
      "id": 0,
      "name": "string",
      "description": "string",
      "start_date": "2019-08-24T14:15:22Z",
      "end_date": "2019-08-24T14:15:22Z",
      "feature_flag_key": "string",
      "parameters": {
        "property1": null,
        "property2": null
      },
      "secondary_metrics": {
        "property1": null,
        "property2": null
      },
      "filters": {
        "property1": null,
        "property2": null
      },
      "archived": true,
      "created_by": {
        "id": 0,
        "uuid": "095be615-a8ad-4c33-8e9c-c7612fbf6c9f",
        "distinct_id": "string",
        "first_name": "string",
        "email": "user@example.com"
      },
      "created_at": "2019-08-24T14:15:22Z",
      "updated_at": "2019-08-24T14:15:22Z"
    }
  ]
}

```

### Properties

|Name|Type|Required|Restrictions|Description|
|---|---|---|---|---|
|count|integer|false|none|none|
|next|string(uri)¦null|false|none|none|
|previous|string(uri)¦null|false|none|none|
|results|[[Experiment](#schemaexperiment)]|false|none|none|

<h2 id="tocS_PaginatedFeatureFlagList">PaginatedFeatureFlagList</h2>
<!-- backwards compatibility -->
<a id="schemapaginatedfeatureflaglist"></a>
<a id="schema_PaginatedFeatureFlagList"></a>
<a id="tocSpaginatedfeatureflaglist"></a>
<a id="tocspaginatedfeatureflaglist"></a>

```json
{
  "count": 123,
  "next": "http://api.example.org/accounts/?offset=400&limit=100",
  "previous": "http://api.example.org/accounts/?offset=200&limit=100",
  "results": [
    {
      "id": 0,
      "name": "string",
      "key": "string",
      "filters": {
        "property1": null,
        "property2": null
      },
      "deleted": true,
      "active": true,
      "created_by": {
        "id": 0,
        "uuid": "095be615-a8ad-4c33-8e9c-c7612fbf6c9f",
        "distinct_id": "string",
        "first_name": "string",
        "email": "user@example.com"
      },
      "created_at": "2019-08-24T14:15:22Z",
      "is_simple_flag": true,
      "rollout_percentage": 0
    }
  ]
}

```

### Properties

|Name|Type|Required|Restrictions|Description|
|---|---|---|---|---|
|count|integer|false|none|none|
|next|string(uri)¦null|false|none|none|
|previous|string(uri)¦null|false|none|none|
|results|[[FeatureFlag](#schemafeatureflag)]|false|none|none|

<h2 id="tocS_PaginatedGroupList">PaginatedGroupList</h2>
<!-- backwards compatibility -->
<a id="schemapaginatedgrouplist"></a>
<a id="schema_PaginatedGroupList"></a>
<a id="tocSpaginatedgrouplist"></a>
<a id="tocspaginatedgrouplist"></a>

```json
{
  "next": "string",
  "previous": "string",
  "results": [
    {
      "group_type_index": -2147483648,
      "group_key": "string",
      "group_properties": {
        "property1": null,
        "property2": null
      },
      "created_at": "2019-08-24T14:15:22Z"
    }
  ]
}

```

### Properties

|Name|Type|Required|Restrictions|Description|
|---|---|---|---|---|
|next|string¦null|false|none|none|
|previous|string¦null|false|none|none|
|results|[[Group](#schemagroup)]|false|none|none|

<h2 id="tocS_PaginatedHookList">PaginatedHookList</h2>
<!-- backwards compatibility -->
<a id="schemapaginatedhooklist"></a>
<a id="schema_PaginatedHookList"></a>
<a id="tocSpaginatedhooklist"></a>
<a id="tocspaginatedhooklist"></a>

```json
{
  "count": 123,
  "next": "http://api.example.org/accounts/?offset=400&limit=100",
  "previous": "http://api.example.org/accounts/?offset=200&limit=100",
  "results": [
    {
      "id": "string",
      "created": "2019-08-24T14:15:22Z",
      "updated": "2019-08-24T14:15:22Z",
      "event": "string",
      "target": "http://example.com",
      "resource_id": -2147483648,
      "team": 0
    }
  ]
}

```

### Properties

|Name|Type|Required|Restrictions|Description|
|---|---|---|---|---|
|count|integer|false|none|none|
|next|string(uri)¦null|false|none|none|
|previous|string(uri)¦null|false|none|none|
|results|[[Hook](#schemahook)]|false|none|none|

<h2 id="tocS_PaginatedInsightList">PaginatedInsightList</h2>
<!-- backwards compatibility -->
<a id="schemapaginatedinsightlist"></a>
<a id="schema_PaginatedInsightList"></a>
<a id="tocSpaginatedinsightlist"></a>
<a id="tocspaginatedinsightlist"></a>

```json
{
  "count": 123,
  "next": "http://api.example.org/accounts/?offset=400&limit=100",
  "previous": "http://api.example.org/accounts/?offset=200&limit=100",
  "results": [
    {
      "id": 0,
      "short_id": "string",
      "name": "string",
      "filters": {
        "property1": null,
        "property2": null
      },
      "filters_hash": "string",
      "order": -2147483648,
      "deleted": true,
      "dashboard": 0,
      "dive_dashboard": 0,
      "layouts": {
        "property1": null,
        "property2": null
      },
      "color": "string",
      "last_refresh": "string",
      "refreshing": true,
      "result": "string",
      "created_at": "2019-08-24T14:15:22Z",
      "description": "string",
      "updated_at": "2019-08-24T14:15:22Z",
      "tags": [
        "string"
      ],
      "favorited": true,
      "saved": true,
      "created_by": {
        "id": 0,
        "uuid": "095be615-a8ad-4c33-8e9c-c7612fbf6c9f",
        "distinct_id": "string",
        "first_name": "string",
        "email": "user@example.com"
      },
      "is_sample": true
    }
  ]
}

```

### Properties

|Name|Type|Required|Restrictions|Description|
|---|---|---|---|---|
|count|integer|false|none|none|
|next|string(uri)¦null|false|none|none|
|previous|string(uri)¦null|false|none|none|
|results|[[Insight](#schemainsight)]|false|none|[Simplified serializer to speed response times when loading large amounts of objects.]|

<h2 id="tocS_PaginatedOrganizationInviteList">PaginatedOrganizationInviteList</h2>
<!-- backwards compatibility -->
<a id="schemapaginatedorganizationinvitelist"></a>
<a id="schema_PaginatedOrganizationInviteList"></a>
<a id="tocSpaginatedorganizationinvitelist"></a>
<a id="tocspaginatedorganizationinvitelist"></a>

```json
{
  "count": 123,
  "next": "http://api.example.org/accounts/?offset=400&limit=100",
  "previous": "http://api.example.org/accounts/?offset=200&limit=100",
  "results": [
    {
      "id": "497f6eca-6276-4993-bfeb-53cbbbba6f08",
      "target_email": "user@example.com",
      "first_name": "string",
      "emailing_attempt_made": true,
      "is_expired": true,
      "created_by": {
        "id": 0,
        "uuid": "095be615-a8ad-4c33-8e9c-c7612fbf6c9f",
        "distinct_id": "string",
        "first_name": "string",
        "email": "user@example.com"
      },
      "created_at": "2019-08-24T14:15:22Z",
      "updated_at": "2019-08-24T14:15:22Z"
    }
  ]
}

```

### Properties

|Name|Type|Required|Restrictions|Description|
|---|---|---|---|---|
|count|integer|false|none|none|
|next|string(uri)¦null|false|none|none|
|previous|string(uri)¦null|false|none|none|
|results|[[OrganizationInvite](#schemaorganizationinvite)]|false|none|none|

<h2 id="tocS_PaginatedOrganizationMemberList">PaginatedOrganizationMemberList</h2>
<!-- backwards compatibility -->
<a id="schemapaginatedorganizationmemberlist"></a>
<a id="schema_PaginatedOrganizationMemberList"></a>
<a id="tocSpaginatedorganizationmemberlist"></a>
<a id="tocspaginatedorganizationmemberlist"></a>

```json
{
  "count": 123,
  "next": "http://api.example.org/accounts/?offset=400&limit=100",
  "previous": "http://api.example.org/accounts/?offset=200&limit=100",
  "results": [
    {
      "id": "497f6eca-6276-4993-bfeb-53cbbbba6f08",
      "user": {
        "id": 0,
        "uuid": "095be615-a8ad-4c33-8e9c-c7612fbf6c9f",
        "distinct_id": "string",
        "first_name": "string",
        "email": "user@example.com"
      },
      "level": 1,
      "joined_at": "2019-08-24T14:15:22Z",
      "updated_at": "2019-08-24T14:15:22Z"
    }
  ]
}

```

### Properties

|Name|Type|Required|Restrictions|Description|
|---|---|---|---|---|
|count|integer|false|none|none|
|next|string(uri)¦null|false|none|none|
|previous|string(uri)¦null|false|none|none|
|results|[[OrganizationMember](#schemaorganizationmember)]|false|none|none|

<h2 id="tocS_PaginatedPersonList">PaginatedPersonList</h2>
<!-- backwards compatibility -->
<a id="schemapaginatedpersonlist"></a>
<a id="schema_PaginatedPersonList"></a>
<a id="tocSpaginatedpersonlist"></a>
<a id="tocspaginatedpersonlist"></a>

```json
{
  "next": "string",
  "previous": "string",
  "results": [
    {
      "id": 0,
      "name": "string",
      "distinct_ids": [
        "string"
      ],
      "properties": {
        "property1": null,
        "property2": null
      },
      "created_at": "2019-08-24T14:15:22Z",
      "uuid": "095be615-a8ad-4c33-8e9c-c7612fbf6c9f"
    }
  ]
}

```

### Properties

|Name|Type|Required|Restrictions|Description|
|---|---|---|---|---|
|next|string¦null|false|none|none|
|previous|string¦null|false|none|none|
|results|[[Person](#schemaperson)]|false|none|none|

<h2 id="tocS_PaginatedPluginConfigList">PaginatedPluginConfigList</h2>
<!-- backwards compatibility -->
<a id="schemapaginatedpluginconfiglist"></a>
<a id="schema_PaginatedPluginConfigList"></a>
<a id="tocSpaginatedpluginconfiglist"></a>
<a id="tocspaginatedpluginconfiglist"></a>

```json
{
  "count": 123,
  "next": "http://api.example.org/accounts/?offset=400&limit=100",
  "previous": "http://api.example.org/accounts/?offset=200&limit=100",
  "results": [
    {
      "id": 0,
      "plugin": 0,
      "enabled": true,
      "order": -2147483648,
      "config": "string",
      "error": {
        "property1": null,
        "property2": null
      },
      "team_id": 0
    }
  ]
}

```

### Properties

|Name|Type|Required|Restrictions|Description|
|---|---|---|---|---|
|count|integer|false|none|none|
|next|string(uri)¦null|false|none|none|
|previous|string(uri)¦null|false|none|none|
|results|[[PluginConfig](#schemapluginconfig)]|false|none|none|

<h2 id="tocS_PaginatedPluginList">PaginatedPluginList</h2>
<!-- backwards compatibility -->
<a id="schemapaginatedpluginlist"></a>
<a id="schema_PaginatedPluginList"></a>
<a id="tocSpaginatedpluginlist"></a>
<a id="tocspaginatedpluginlist"></a>

```json
{
  "count": 123,
  "next": "http://api.example.org/accounts/?offset=400&limit=100",
  "previous": "http://api.example.org/accounts/?offset=200&limit=100",
  "results": [
    {
      "id": 0,
      "plugin_type": "local",
      "name": "string",
      "description": "string",
      "url": "string",
      "config_schema": {
        "property1": null,
        "property2": null
      },
      "tag": "string",
      "source": "string",
      "latest_tag": "string",
      "is_global": true,
      "organization_id": "7c60d51f-b44e-4682-87d6-449835ea4de6",
      "organization_name": "string",
      "capabilities": {
        "property1": null,
        "property2": null
      },
      "metrics": {
        "property1": null,
        "property2": null
      },
      "public_jobs": {
        "property1": null,
        "property2": null
      }
    }
  ]
}

```

### Properties

|Name|Type|Required|Restrictions|Description|
|---|---|---|---|---|
|count|integer|false|none|none|
|next|string(uri)¦null|false|none|none|
|previous|string(uri)¦null|false|none|none|
|results|[[Plugin](#schemaplugin)]|false|none|none|

<h2 id="tocS_PaginatedPluginLogEntryList">PaginatedPluginLogEntryList</h2>
<!-- backwards compatibility -->
<a id="schemapaginatedpluginlogentrylist"></a>
<a id="schema_PaginatedPluginLogEntryList"></a>
<a id="tocSpaginatedpluginlogentrylist"></a>
<a id="tocspaginatedpluginlogentrylist"></a>

```json
{
  "count": 123,
  "next": "http://api.example.org/accounts/?offset=400&limit=100",
  "previous": "http://api.example.org/accounts/?offset=200&limit=100",
  "results": [
    {
      "id": "497f6eca-6276-4993-bfeb-53cbbbba6f08",
      "team_id": 0,
      "plugin_id": 0,
      "timestamp": "2019-08-24T14:15:22Z",
      "source": "SYSTEM",
      "type": "DEBUG",
      "message": "string",
      "instance_id": "06587974-2dbe-4e10-8bf9-38cce0f5a366"
    }
  ]
}

```

### Properties

|Name|Type|Required|Restrictions|Description|
|---|---|---|---|---|
|count|integer|false|none|none|
|next|string(uri)¦null|false|none|none|
|previous|string(uri)¦null|false|none|none|
|results|[[PluginLogEntry](#schemapluginlogentry)]|false|none|none|

<h2 id="tocS_PaginatedTeamBasicList">PaginatedTeamBasicList</h2>
<!-- backwards compatibility -->
<a id="schemapaginatedteambasiclist"></a>
<a id="schema_PaginatedTeamBasicList"></a>
<a id="tocSpaginatedteambasiclist"></a>
<a id="tocspaginatedteambasiclist"></a>

```json
{
  "count": 123,
  "next": "http://api.example.org/accounts/?offset=400&limit=100",
  "previous": "http://api.example.org/accounts/?offset=200&limit=100",
  "results": [
    {
      "id": 0,
      "uuid": "095be615-a8ad-4c33-8e9c-c7612fbf6c9f",
      "organization": "452c1a86-a0af-475b-b03f-724878b0f387",
      "api_token": "stringstri",
      "name": "string",
      "completed_snippet_onboarding": true,
      "ingested_event": true,
      "is_demo": true,
      "timezone": "Africa/Abidjan",
      "access_control": true,
      "effective_membership_level": 1
    }
  ]
}

```

### Properties

|Name|Type|Required|Restrictions|Description|
|---|---|---|---|---|
|count|integer|false|none|none|
|next|string(uri)¦null|false|none|none|
|previous|string(uri)¦null|false|none|none|
|results|[[TeamBasic](#schemateambasic)]|false|none|[Serializer for `Team` model with minimal attributes to speeed up loading and transfer times.<br>Also used for nested serializers.]|

<h2 id="tocS_PatchedAction">PatchedAction</h2>
<!-- backwards compatibility -->
<a id="schemapatchedaction"></a>
<a id="schema_PatchedAction"></a>
<a id="tocSpatchedaction"></a>
<a id="tocspatchedaction"></a>

```json
{
  "id": 0,
  "name": "string",
  "post_to_slack": true,
  "slack_message_format": "string",
  "steps": [
    {
      "id": "string",
      "event": "string",
      "tag_name": "string",
      "text": "string",
      "href": "string",
      "selector": "string",
      "url": "string",
      "name": "string",
      "url_matching": "contains",
      "properties": {
        "property1": null,
        "property2": null
      }
    }
  ],
  "created_at": "2019-08-24T14:15:22Z",
  "deleted": true,
  "is_calculating": true,
  "last_calculated_at": "2019-08-24T14:15:22Z",
  "created_by": {
    "id": 0,
    "uuid": "095be615-a8ad-4c33-8e9c-c7612fbf6c9f",
    "distinct_id": "string",
    "first_name": "string",
    "email": "user@example.com"
  },
  "team_id": 0
}

```

### Properties

|Name|Type|Required|Restrictions|Description|
|---|---|---|---|---|
|id|integer|false|read-only|none|
|name|string¦null|false|none|none|
|post_to_slack|boolean|false|none|none|
|slack_message_format|string|false|none|none|
|steps|[[ActionStep](#schemaactionstep)]|false|none|none|
|created_at|string(date-time)|false|read-only|none|
|deleted|boolean|false|none|none|
|is_calculating|boolean|false|read-only|none|
|last_calculated_at|string(date-time)|false|none|none|
|created_by|[UserBasic](#schemauserbasic)|false|read-only|none|
|team_id|integer|false|read-only|none|

<h2 id="tocS_PatchedAnnotation">PatchedAnnotation</h2>
<!-- backwards compatibility -->
<a id="schemapatchedannotation"></a>
<a id="schema_PatchedAnnotation"></a>
<a id="tocSpatchedannotation"></a>
<a id="tocspatchedannotation"></a>

```json
{
  "id": 0,
  "content": "string",
  "date_marker": "2019-08-24T14:15:22Z",
  "creation_type": "USR",
  "dashboard_item": 0,
  "created_by": {
    "id": 0,
    "uuid": "095be615-a8ad-4c33-8e9c-c7612fbf6c9f",
    "distinct_id": "string",
    "first_name": "string",
    "email": "user@example.com"
  },
  "created_at": "2019-08-24T14:15:22Z",
  "updated_at": "2019-08-24T14:15:22Z",
  "deleted": true,
  "scope": "dashboard_item"
}

```

### Properties

|Name|Type|Required|Restrictions|Description|
|---|---|---|---|---|
|id|integer|false|read-only|none|
|content|string¦null|false|none|none|
|date_marker|string(date-time)¦null|false|none|none|
|creation_type|string|false|read-only|none|
|dashboard_item|integer¦null|false|none|none|
|created_by|[UserBasic](#schemauserbasic)|false|read-only|none|
|created_at|string(date-time)|false|read-only|none|
|updated_at|string(date-time)|false|read-only|none|
|deleted|boolean|false|none|none|
|scope|string|false|none|none|

#### Enumerated Values

|Property|Value|
|---|---|
|creation_type|USR|
|creation_type|GIT|
|scope|dashboard_item|
|scope|project|
|scope|organization|

<h2 id="tocS_PatchedClickhouseCohort">PatchedClickhouseCohort</h2>
<!-- backwards compatibility -->
<a id="schemapatchedclickhousecohort"></a>
<a id="schema_PatchedClickhouseCohort"></a>
<a id="tocSpatchedclickhousecohort"></a>
<a id="tocspatchedclickhousecohort"></a>

```json
{
  "id": 0,
  "name": "string",
  "description": "string",
  "groups": {
    "property1": null,
    "property2": null
  },
  "deleted": true,
  "is_calculating": true,
  "created_by": {
    "id": 0,
    "uuid": "095be615-a8ad-4c33-8e9c-c7612fbf6c9f",
    "distinct_id": "string",
    "first_name": "string",
    "email": "user@example.com"
  },
  "created_at": "2019-08-24T14:15:22Z",
  "last_calculation": "2019-08-24T14:15:22Z",
  "errors_calculating": 0,
  "count": 0,
  "is_static": true
}

```

### Properties

|Name|Type|Required|Restrictions|Description|
|---|---|---|---|---|
|id|integer|false|read-only|none|
|name|string¦null|false|none|none|
|description|string|false|none|none|
|groups|object|false|none|none|
|» **additionalProperties**|any|false|none|none|
|deleted|boolean|false|none|none|
|is_calculating|boolean|false|read-only|none|
|created_by|[UserBasic](#schemauserbasic)|false|read-only|none|
|created_at|string(date-time)|false|read-only|none|
|last_calculation|string(date-time)|false|read-only|none|
|errors_calculating|integer|false|read-only|none|
|count|integer¦null|false|read-only|none|
|is_static|boolean|false|none|none|

<h2 id="tocS_PatchedDashboard">PatchedDashboard</h2>
<!-- backwards compatibility -->
<a id="schemapatcheddashboard"></a>
<a id="schema_PatchedDashboard"></a>
<a id="tocSpatcheddashboard"></a>
<a id="tocspatcheddashboard"></a>

```json
{
  "id": 0,
  "name": "string",
  "description": "string",
  "pinned": true,
  "items": "string",
  "created_at": "2019-08-24T14:15:22Z",
  "created_by": {
    "id": 0,
    "uuid": "095be615-a8ad-4c33-8e9c-c7612fbf6c9f",
    "distinct_id": "string",
    "first_name": "string",
    "email": "user@example.com"
  },
  "is_shared": true,
  "share_token": "string",
  "deleted": true,
  "creation_mode": "default",
  "use_template": "string",
  "use_dashboard": 0,
  "filters": {
    "property1": null,
    "property2": null
  },
  "tags": [
    "string"
  ]
}

```

### Properties

|Name|Type|Required|Restrictions|Description|
|---|---|---|---|---|
|id|integer|false|read-only|none|
|name|string¦null|false|none|none|
|description|string|false|none|none|
|pinned|boolean|false|none|none|
|items|string|false|read-only|none|
|created_at|string(date-time)|false|read-only|none|
|created_by|[UserBasic](#schemauserbasic)|false|read-only|none|
|is_shared|boolean|false|none|none|
|share_token|string¦null|false|none|none|
|deleted|boolean|false|none|none|
|creation_mode|string|false|read-only|none|
|use_template|string|false|write-only|none|
|use_dashboard|integer¦null|false|write-only|none|
|filters|object|false|none|none|
|» **additionalProperties**|any|false|none|none|
|tags|[string]|false|none|none|

#### Enumerated Values

|Property|Value|
|---|---|
|creation_mode|default|
|creation_mode|template|
|creation_mode|duplicate|

<h2 id="tocS_PatchedExperiment">PatchedExperiment</h2>
<!-- backwards compatibility -->
<a id="schemapatchedexperiment"></a>
<a id="schema_PatchedExperiment"></a>
<a id="tocSpatchedexperiment"></a>
<a id="tocspatchedexperiment"></a>

```json
{
  "id": 0,
  "name": "string",
  "description": "string",
  "start_date": "2019-08-24T14:15:22Z",
  "end_date": "2019-08-24T14:15:22Z",
  "feature_flag_key": "string",
  "parameters": {
    "property1": null,
    "property2": null
  },
  "secondary_metrics": {
    "property1": null,
    "property2": null
  },
  "filters": {
    "property1": null,
    "property2": null
  },
  "archived": true,
  "created_by": {
    "id": 0,
    "uuid": "095be615-a8ad-4c33-8e9c-c7612fbf6c9f",
    "distinct_id": "string",
    "first_name": "string",
    "email": "user@example.com"
  },
  "created_at": "2019-08-24T14:15:22Z",
  "updated_at": "2019-08-24T14:15:22Z"
}

```

### Properties

|Name|Type|Required|Restrictions|Description|
|---|---|---|---|---|
|id|integer|false|read-only|none|
|name|string|false|none|none|
|description|string¦null|false|none|none|
|start_date|string(date-time)¦null|false|none|none|
|end_date|string(date-time)¦null|false|none|none|
|feature_flag_key|string|false|none|none|
|parameters|object¦null|false|none|none|
|» **additionalProperties**|any|false|none|none|
|secondary_metrics|object¦null|false|none|none|
|» **additionalProperties**|any|false|none|none|
|filters|object|false|none|none|
|» **additionalProperties**|any|false|none|none|
|archived|boolean|false|none|none|
|created_by|[UserBasic](#schemauserbasic)|false|read-only|none|
|created_at|string(date-time)|false|read-only|none|
|updated_at|string(date-time)|false|read-only|none|

<h2 id="tocS_PatchedFeatureFlag">PatchedFeatureFlag</h2>
<!-- backwards compatibility -->
<a id="schemapatchedfeatureflag"></a>
<a id="schema_PatchedFeatureFlag"></a>
<a id="tocSpatchedfeatureflag"></a>
<a id="tocspatchedfeatureflag"></a>

```json
{
  "id": 0,
  "name": "string",
  "key": "string",
  "filters": {
    "property1": null,
    "property2": null
  },
  "deleted": true,
  "active": true,
  "created_by": {
    "id": 0,
    "uuid": "095be615-a8ad-4c33-8e9c-c7612fbf6c9f",
    "distinct_id": "string",
    "first_name": "string",
    "email": "user@example.com"
  },
  "created_at": "2019-08-24T14:15:22Z",
  "is_simple_flag": true,
  "rollout_percentage": 0
}

```

### Properties

|Name|Type|Required|Restrictions|Description|
|---|---|---|---|---|
|id|integer|false|read-only|none|
|name|string|false|none|none|
|key|string|false|none|none|
|filters|object|false|none|none|
|» **additionalProperties**|any|false|none|none|
|deleted|boolean|false|none|none|
|active|boolean|false|none|none|
|created_by|[UserBasic](#schemauserbasic)|false|read-only|none|
|created_at|string(date-time)|false|none|none|
|is_simple_flag|boolean|false|read-only|none|
|rollout_percentage|integer¦null|false|read-only|none|

<h2 id="tocS_PatchedGroupType">PatchedGroupType</h2>
<!-- backwards compatibility -->
<a id="schemapatchedgrouptype"></a>
<a id="schema_PatchedGroupType"></a>
<a id="tocSpatchedgrouptype"></a>
<a id="tocspatchedgrouptype"></a>

```json
{
  "group_type": "string",
  "group_type_index": 0,
  "name_singular": "string",
  "name_plural": "string"
}

```

### Properties

|Name|Type|Required|Restrictions|Description|
|---|---|---|---|---|
|group_type|string|false|read-only|none|
|group_type_index|integer|false|read-only|none|
|name_singular|string¦null|false|none|none|
|name_plural|string¦null|false|none|none|

<h2 id="tocS_PatchedHook">PatchedHook</h2>
<!-- backwards compatibility -->
<a id="schemapatchedhook"></a>
<a id="schema_PatchedHook"></a>
<a id="tocSpatchedhook"></a>
<a id="tocspatchedhook"></a>

```json
{
  "id": "string",
  "created": "2019-08-24T14:15:22Z",
  "updated": "2019-08-24T14:15:22Z",
  "event": "string",
  "target": "http://example.com",
  "resource_id": -2147483648,
  "team": 0
}

```

### Properties

|Name|Type|Required|Restrictions|Description|
|---|---|---|---|---|
|id|string|false|none|none|
|created|string(date-time)|false|read-only|none|
|updated|string(date-time)|false|read-only|none|
|event|string|false|none|none|
|target|string(uri)|false|none|none|
|resource_id|integer¦null|false|none|none|
|team|integer|false|read-only|none|

<h2 id="tocS_PatchedInsight">PatchedInsight</h2>
<!-- backwards compatibility -->
<a id="schemapatchedinsight"></a>
<a id="schema_PatchedInsight"></a>
<a id="tocSpatchedinsight"></a>
<a id="tocspatchedinsight"></a>

```json
{
  "id": 0,
  "short_id": "string",
  "name": "string",
  "filters": {
    "property1": null,
    "property2": null
  },
  "filters_hash": "string",
  "order": -2147483648,
  "deleted": true,
  "dashboard": 0,
  "dive_dashboard": 0,
  "layouts": {
    "property1": null,
    "property2": null
  },
  "color": "string",
  "last_refresh": "string",
  "refreshing": true,
  "result": "string",
  "created_at": "2019-08-24T14:15:22Z",
  "description": "string",
  "updated_at": "2019-08-24T14:15:22Z",
  "tags": [
    "string"
  ],
  "favorited": true,
  "saved": true,
  "created_by": {
    "id": 0,
    "uuid": "095be615-a8ad-4c33-8e9c-c7612fbf6c9f",
    "distinct_id": "string",
    "first_name": "string",
    "email": "user@example.com"
  },
  "is_sample": true
}

```

Simplified serializer to speed response times when loading large amounts of objects.

### Properties

|Name|Type|Required|Restrictions|Description|
|---|---|---|---|---|
|id|integer|false|read-only|none|
|short_id|string|false|read-only|none|
|name|string¦null|false|none|none|
|filters|object|false|none|none|
|» **additionalProperties**|any|false|none|none|
|filters_hash|string¦null|false|none|none|
|order|integer¦null|false|none|none|
|deleted|boolean|false|none|none|
|dashboard|integer¦null|false|none|none|
|dive_dashboard|integer¦null|false|none|none|
|layouts|object|false|none|none|
|» **additionalProperties**|any|false|none|none|
|color|string¦null|false|none|none|
|last_refresh|string|false|read-only|none|
|refreshing|boolean|false|none|none|
|result|string|false|read-only|none|
|created_at|string(date-time)|false|read-only|none|
|description|string¦null|false|none|none|
|updated_at|string(date-time)|false|read-only|none|
|tags|[string]|false|none|none|
|favorited|boolean|false|none|none|
|saved|boolean|false|none|none|
|created_by|[UserBasic](#schemauserbasic)|false|read-only|none|
|is_sample|boolean|false|read-only|none|

<h2 id="tocS_PatchedOrganizationMember">PatchedOrganizationMember</h2>
<!-- backwards compatibility -->
<a id="schemapatchedorganizationmember"></a>
<a id="schema_PatchedOrganizationMember"></a>
<a id="tocSpatchedorganizationmember"></a>
<a id="tocspatchedorganizationmember"></a>

```json
{
  "id": "497f6eca-6276-4993-bfeb-53cbbbba6f08",
  "user": {
    "id": 0,
    "uuid": "095be615-a8ad-4c33-8e9c-c7612fbf6c9f",
    "distinct_id": "string",
    "first_name": "string",
    "email": "user@example.com"
  },
  "level": 1,
  "joined_at": "2019-08-24T14:15:22Z",
  "updated_at": "2019-08-24T14:15:22Z"
}

```

### Properties

|Name|Type|Required|Restrictions|Description|
|---|---|---|---|---|
|id|string(uuid)|false|read-only|none|
|user|[UserBasic](#schemauserbasic)|false|read-only|none|
|level|integer|false|none|none|
|joined_at|string(date-time)|false|read-only|none|
|updated_at|string(date-time)|false|read-only|none|

#### Enumerated Values

|Property|Value|
|---|---|
|level|1|
|level|8|
|level|15|

<h2 id="tocS_PatchedPerson">PatchedPerson</h2>
<!-- backwards compatibility -->
<a id="schemapatchedperson"></a>
<a id="schema_PatchedPerson"></a>
<a id="tocSpatchedperson"></a>
<a id="tocspatchedperson"></a>

```json
{
  "id": 0,
  "name": "string",
  "distinct_ids": [
    "string"
  ],
  "properties": {
    "property1": null,
    "property2": null
  },
  "created_at": "2019-08-24T14:15:22Z",
  "uuid": "095be615-a8ad-4c33-8e9c-c7612fbf6c9f"
}

```

### Properties

|Name|Type|Required|Restrictions|Description|
|---|---|---|---|---|
|id|integer|false|read-only|none|
|name|string|false|read-only|none|
|distinct_ids|[string]|false|read-only|none|
|properties|object|false|none|none|
|» **additionalProperties**|any|false|none|none|
|created_at|string(date-time)|false|read-only|none|
|uuid|string(uuid)|false|read-only|none|

<h2 id="tocS_PatchedPlugin">PatchedPlugin</h2>
<!-- backwards compatibility -->
<a id="schemapatchedplugin"></a>
<a id="schema_PatchedPlugin"></a>
<a id="tocSpatchedplugin"></a>
<a id="tocspatchedplugin"></a>

```json
{
  "id": 0,
  "plugin_type": "local",
  "name": "string",
  "description": "string",
  "url": "string",
  "config_schema": {
    "property1": null,
    "property2": null
  },
  "tag": "string",
  "source": "string",
  "latest_tag": "string",
  "is_global": true,
  "organization_id": "7c60d51f-b44e-4682-87d6-449835ea4de6",
  "organization_name": "string",
  "capabilities": {
    "property1": null,
    "property2": null
  },
  "metrics": {
    "property1": null,
    "property2": null
  },
  "public_jobs": {
    "property1": null,
    "property2": null
  }
}

```

### Properties

|Name|Type|Required|Restrictions|Description|
|---|---|---|---|---|
|id|integer|false|read-only|none|
|plugin_type|string¦null|false|none|none|
|name|string¦null|false|none|none|
|description|string¦null|false|none|none|
|url|string¦null|false|read-only|none|
|config_schema|object|false|none|none|
|» **additionalProperties**|any|false|none|none|
|tag|string¦null|false|none|none|
|source|string¦null|false|none|none|
|latest_tag|string|false|read-only|none|
|is_global|boolean|false|none|none|
|organization_id|string(uuid)|false|read-only|none|
|organization_name|string|false|read-only|none|
|capabilities|object|false|none|none|
|» **additionalProperties**|any|false|none|none|
|metrics|object¦null|false|none|none|
|» **additionalProperties**|any|false|none|none|
|public_jobs|object¦null|false|none|none|
|» **additionalProperties**|any|false|none|none|

#### Enumerated Values

|Property|Value|
|---|---|
|plugin_type|local|
|plugin_type|custom|
|plugin_type|repository|
|plugin_type|source|
|plugin_type||
|plugin_type|null|

<h2 id="tocS_PatchedPluginConfig">PatchedPluginConfig</h2>
<!-- backwards compatibility -->
<a id="schemapatchedpluginconfig"></a>
<a id="schema_PatchedPluginConfig"></a>
<a id="tocSpatchedpluginconfig"></a>
<a id="tocspatchedpluginconfig"></a>

```json
{
  "id": 0,
  "plugin": 0,
  "enabled": true,
  "order": -2147483648,
  "config": "string",
  "error": {
    "property1": null,
    "property2": null
  },
  "team_id": 0
}

```

### Properties

|Name|Type|Required|Restrictions|Description|
|---|---|---|---|---|
|id|integer|false|read-only|none|
|plugin|integer|false|none|none|
|enabled|boolean|false|none|none|
|order|integer|false|none|none|
|config|string|false|read-only|none|
|error|object¦null|false|none|none|
|» **additionalProperties**|any|false|none|none|
|team_id|integer¦null|false|read-only|none|

<h2 id="tocS_PatchedTeam">PatchedTeam</h2>
<!-- backwards compatibility -->
<a id="schemapatchedteam"></a>
<a id="schema_PatchedTeam"></a>
<a id="tocSpatchedteam"></a>
<a id="tocspatchedteam"></a>

```json
{
  "id": 0,
  "uuid": "095be615-a8ad-4c33-8e9c-c7612fbf6c9f",
  "organization": "452c1a86-a0af-475b-b03f-724878b0f387",
  "api_token": "string",
  "app_urls": [
    "string"
  ],
  "name": "string",
  "slack_incoming_webhook": "string",
  "created_at": "2019-08-24T14:15:22Z",
  "updated_at": "2019-08-24T14:15:22Z",
  "anonymize_ips": true,
  "completed_snippet_onboarding": true,
  "ingested_event": true,
  "test_account_filters": {
    "property1": null,
    "property2": null
  },
  "path_cleaning_filters": {
    "property1": null,
    "property2": null
  },
  "is_demo": true,
  "timezone": "Africa/Abidjan",
  "data_attributes": {
    "property1": null,
    "property2": null
  },
  "correlation_config": {
    "property1": null,
    "property2": null
  },
  "session_recording_opt_in": true,
  "effective_membership_level": 1,
  "access_control": true,
  "has_group_types": true
}

```

### Properties

|Name|Type|Required|Restrictions|Description|
|---|---|---|---|---|
|id|integer|false|read-only|none|
|uuid|string(uuid)|false|read-only|none|
|organization|string(uuid)|false|read-only|none|
|api_token|string|false|read-only|none|
|app_urls|[string]|false|none|none|
|name|string|false|none|none|
|slack_incoming_webhook|string¦null|false|none|none|
|created_at|string(date-time)|false|read-only|none|
|updated_at|string(date-time)|false|read-only|none|
|anonymize_ips|boolean|false|none|none|
|completed_snippet_onboarding|boolean|false|none|none|
|ingested_event|boolean|false|read-only|none|
|test_account_filters|object|false|none|none|
|» **additionalProperties**|any|false|none|none|
|path_cleaning_filters|object¦null|false|none|none|
|» **additionalProperties**|any|false|none|none|
|is_demo|boolean|false|read-only|none|
|timezone|string|false|none|none|
|data_attributes|object|false|none|none|
|» **additionalProperties**|any|false|none|none|
|correlation_config|object¦null|false|none|none|
|» **additionalProperties**|any|false|none|none|
|session_recording_opt_in|boolean|false|none|none|
|effective_membership_level|integer¦null|false|read-only|none|
|access_control|boolean|false|none|none|
|has_group_types|boolean|false|read-only|none|

#### Enumerated Values

|Property|Value|
|---|---|
|timezone|Africa/Abidjan|
|timezone|Africa/Accra|
|timezone|Africa/Addis_Ababa|
|timezone|Africa/Algiers|
|timezone|Africa/Asmara|
|timezone|Africa/Bamako|
|timezone|Africa/Bangui|
|timezone|Africa/Banjul|
|timezone|Africa/Bissau|
|timezone|Africa/Blantyre|
|timezone|Africa/Brazzaville|
|timezone|Africa/Bujumbura|
|timezone|Africa/Cairo|
|timezone|Africa/Casablanca|
|timezone|Africa/Ceuta|
|timezone|Africa/Conakry|
|timezone|Africa/Dakar|
|timezone|Africa/Dar_es_Salaam|
|timezone|Africa/Djibouti|
|timezone|Africa/Douala|
|timezone|Africa/El_Aaiun|
|timezone|Africa/Freetown|
|timezone|Africa/Gaborone|
|timezone|Africa/Harare|
|timezone|Africa/Johannesburg|
|timezone|Africa/Juba|
|timezone|Africa/Kampala|
|timezone|Africa/Khartoum|
|timezone|Africa/Kigali|
|timezone|Africa/Kinshasa|
|timezone|Africa/Lagos|
|timezone|Africa/Libreville|
|timezone|Africa/Lome|
|timezone|Africa/Luanda|
|timezone|Africa/Lubumbashi|
|timezone|Africa/Lusaka|
|timezone|Africa/Malabo|
|timezone|Africa/Maputo|
|timezone|Africa/Maseru|
|timezone|Africa/Mbabane|
|timezone|Africa/Mogadishu|
|timezone|Africa/Monrovia|
|timezone|Africa/Nairobi|
|timezone|Africa/Ndjamena|
|timezone|Africa/Niamey|
|timezone|Africa/Nouakchott|
|timezone|Africa/Ouagadougou|
|timezone|Africa/Porto-Novo|
|timezone|Africa/Sao_Tome|
|timezone|Africa/Tripoli|
|timezone|Africa/Tunis|
|timezone|Africa/Windhoek|
|timezone|America/Adak|
|timezone|America/Anchorage|
|timezone|America/Anguilla|
|timezone|America/Antigua|
|timezone|America/Araguaina|
|timezone|America/Argentina/Buenos_Aires|
|timezone|America/Argentina/Catamarca|
|timezone|America/Argentina/Cordoba|
|timezone|America/Argentina/Jujuy|
|timezone|America/Argentina/La_Rioja|
|timezone|America/Argentina/Mendoza|
|timezone|America/Argentina/Rio_Gallegos|
|timezone|America/Argentina/Salta|
|timezone|America/Argentina/San_Juan|
|timezone|America/Argentina/San_Luis|
|timezone|America/Argentina/Tucuman|
|timezone|America/Argentina/Ushuaia|
|timezone|America/Aruba|
|timezone|America/Asuncion|
|timezone|America/Atikokan|
|timezone|America/Bahia|
|timezone|America/Bahia_Banderas|
|timezone|America/Barbados|
|timezone|America/Belem|
|timezone|America/Belize|
|timezone|America/Blanc-Sablon|
|timezone|America/Boa_Vista|
|timezone|America/Bogota|
|timezone|America/Boise|
|timezone|America/Cambridge_Bay|
|timezone|America/Campo_Grande|
|timezone|America/Cancun|
|timezone|America/Caracas|
|timezone|America/Cayenne|
|timezone|America/Cayman|
|timezone|America/Chicago|
|timezone|America/Chihuahua|
|timezone|America/Costa_Rica|
|timezone|America/Creston|
|timezone|America/Cuiaba|
|timezone|America/Curacao|
|timezone|America/Danmarkshavn|
|timezone|America/Dawson|
|timezone|America/Dawson_Creek|
|timezone|America/Denver|
|timezone|America/Detroit|
|timezone|America/Dominica|
|timezone|America/Edmonton|
|timezone|America/Eirunepe|
|timezone|America/El_Salvador|
|timezone|America/Fort_Nelson|
|timezone|America/Fortaleza|
|timezone|America/Glace_Bay|
|timezone|America/Goose_Bay|
|timezone|America/Grand_Turk|
|timezone|America/Grenada|
|timezone|America/Guadeloupe|
|timezone|America/Guatemala|
|timezone|America/Guayaquil|
|timezone|America/Guyana|
|timezone|America/Halifax|
|timezone|America/Havana|
|timezone|America/Hermosillo|
|timezone|America/Indiana/Indianapolis|
|timezone|America/Indiana/Knox|
|timezone|America/Indiana/Marengo|
|timezone|America/Indiana/Petersburg|
|timezone|America/Indiana/Tell_City|
|timezone|America/Indiana/Vevay|
|timezone|America/Indiana/Vincennes|
|timezone|America/Indiana/Winamac|
|timezone|America/Inuvik|
|timezone|America/Iqaluit|
|timezone|America/Jamaica|
|timezone|America/Juneau|
|timezone|America/Kentucky/Louisville|
|timezone|America/Kentucky/Monticello|
|timezone|America/Kralendijk|
|timezone|America/La_Paz|
|timezone|America/Lima|
|timezone|America/Los_Angeles|
|timezone|America/Lower_Princes|
|timezone|America/Maceio|
|timezone|America/Managua|
|timezone|America/Manaus|
|timezone|America/Marigot|
|timezone|America/Martinique|
|timezone|America/Matamoros|
|timezone|America/Mazatlan|
|timezone|America/Menominee|
|timezone|America/Merida|
|timezone|America/Metlakatla|
|timezone|America/Mexico_City|
|timezone|America/Miquelon|
|timezone|America/Moncton|
|timezone|America/Monterrey|
|timezone|America/Montevideo|
|timezone|America/Montserrat|
|timezone|America/Nassau|
|timezone|America/New_York|
|timezone|America/Nipigon|
|timezone|America/Nome|
|timezone|America/Noronha|
|timezone|America/North_Dakota/Beulah|
|timezone|America/North_Dakota/Center|
|timezone|America/North_Dakota/New_Salem|
|timezone|America/Nuuk|
|timezone|America/Ojinaga|
|timezone|America/Panama|
|timezone|America/Pangnirtung|
|timezone|America/Paramaribo|
|timezone|America/Phoenix|
|timezone|America/Port-au-Prince|
|timezone|America/Port_of_Spain|
|timezone|America/Porto_Velho|
|timezone|America/Puerto_Rico|
|timezone|America/Punta_Arenas|
|timezone|America/Rainy_River|
|timezone|America/Rankin_Inlet|
|timezone|America/Recife|
|timezone|America/Regina|
|timezone|America/Resolute|
|timezone|America/Rio_Branco|
|timezone|America/Santarem|
|timezone|America/Santiago|
|timezone|America/Santo_Domingo|
|timezone|America/Sao_Paulo|
|timezone|America/Scoresbysund|
|timezone|America/Sitka|
|timezone|America/St_Barthelemy|
|timezone|America/St_Johns|
|timezone|America/St_Kitts|
|timezone|America/St_Lucia|
|timezone|America/St_Thomas|
|timezone|America/St_Vincent|
|timezone|America/Swift_Current|
|timezone|America/Tegucigalpa|
|timezone|America/Thule|
|timezone|America/Thunder_Bay|
|timezone|America/Tijuana|
|timezone|America/Toronto|
|timezone|America/Tortola|
|timezone|America/Vancouver|
|timezone|America/Whitehorse|
|timezone|America/Winnipeg|
|timezone|America/Yakutat|
|timezone|America/Yellowknife|
|timezone|Antarctica/Casey|
|timezone|Antarctica/Davis|
|timezone|Antarctica/DumontDUrville|
|timezone|Antarctica/Macquarie|
|timezone|Antarctica/Mawson|
|timezone|Antarctica/McMurdo|
|timezone|Antarctica/Palmer|
|timezone|Antarctica/Rothera|
|timezone|Antarctica/Syowa|
|timezone|Antarctica/Troll|
|timezone|Antarctica/Vostok|
|timezone|Arctic/Longyearbyen|
|timezone|Asia/Aden|
|timezone|Asia/Almaty|
|timezone|Asia/Amman|
|timezone|Asia/Anadyr|
|timezone|Asia/Aqtau|
|timezone|Asia/Aqtobe|
|timezone|Asia/Ashgabat|
|timezone|Asia/Atyrau|
|timezone|Asia/Baghdad|
|timezone|Asia/Bahrain|
|timezone|Asia/Baku|
|timezone|Asia/Bangkok|
|timezone|Asia/Barnaul|
|timezone|Asia/Beirut|
|timezone|Asia/Bishkek|
|timezone|Asia/Brunei|
|timezone|Asia/Chita|
|timezone|Asia/Choibalsan|
|timezone|Asia/Colombo|
|timezone|Asia/Damascus|
|timezone|Asia/Dhaka|
|timezone|Asia/Dili|
|timezone|Asia/Dubai|
|timezone|Asia/Dushanbe|
|timezone|Asia/Famagusta|
|timezone|Asia/Gaza|
|timezone|Asia/Hebron|
|timezone|Asia/Ho_Chi_Minh|
|timezone|Asia/Hong_Kong|
|timezone|Asia/Hovd|
|timezone|Asia/Irkutsk|
|timezone|Asia/Jakarta|
|timezone|Asia/Jayapura|
|timezone|Asia/Jerusalem|
|timezone|Asia/Kabul|
|timezone|Asia/Kamchatka|
|timezone|Asia/Karachi|
|timezone|Asia/Kathmandu|
|timezone|Asia/Khandyga|
|timezone|Asia/Kolkata|
|timezone|Asia/Krasnoyarsk|
|timezone|Asia/Kuala_Lumpur|
|timezone|Asia/Kuching|
|timezone|Asia/Kuwait|
|timezone|Asia/Macau|
|timezone|Asia/Magadan|
|timezone|Asia/Makassar|
|timezone|Asia/Manila|
|timezone|Asia/Muscat|
|timezone|Asia/Nicosia|
|timezone|Asia/Novokuznetsk|
|timezone|Asia/Novosibirsk|
|timezone|Asia/Omsk|
|timezone|Asia/Oral|
|timezone|Asia/Phnom_Penh|
|timezone|Asia/Pontianak|
|timezone|Asia/Pyongyang|
|timezone|Asia/Qatar|
|timezone|Asia/Qostanay|
|timezone|Asia/Qyzylorda|
|timezone|Asia/Riyadh|
|timezone|Asia/Sakhalin|
|timezone|Asia/Samarkand|
|timezone|Asia/Seoul|
|timezone|Asia/Shanghai|
|timezone|Asia/Singapore|
|timezone|Asia/Srednekolymsk|
|timezone|Asia/Taipei|
|timezone|Asia/Tashkent|
|timezone|Asia/Tbilisi|
|timezone|Asia/Tehran|
|timezone|Asia/Thimphu|
|timezone|Asia/Tokyo|
|timezone|Asia/Tomsk|
|timezone|Asia/Ulaanbaatar|
|timezone|Asia/Urumqi|
|timezone|Asia/Ust-Nera|
|timezone|Asia/Vientiane|
|timezone|Asia/Vladivostok|
|timezone|Asia/Yakutsk|
|timezone|Asia/Yangon|
|timezone|Asia/Yekaterinburg|
|timezone|Asia/Yerevan|
|timezone|Atlantic/Azores|
|timezone|Atlantic/Bermuda|
|timezone|Atlantic/Canary|
|timezone|Atlantic/Cape_Verde|
|timezone|Atlantic/Faroe|
|timezone|Atlantic/Madeira|
|timezone|Atlantic/Reykjavik|
|timezone|Atlantic/South_Georgia|
|timezone|Atlantic/St_Helena|
|timezone|Atlantic/Stanley|
|timezone|Australia/Adelaide|
|timezone|Australia/Brisbane|
|timezone|Australia/Broken_Hill|
|timezone|Australia/Darwin|
|timezone|Australia/Eucla|
|timezone|Australia/Hobart|
|timezone|Australia/Lindeman|
|timezone|Australia/Lord_Howe|
|timezone|Australia/Melbourne|
|timezone|Australia/Perth|
|timezone|Australia/Sydney|
|timezone|Canada/Atlantic|
|timezone|Canada/Central|
|timezone|Canada/Eastern|
|timezone|Canada/Mountain|
|timezone|Canada/Newfoundland|
|timezone|Canada/Pacific|
|timezone|Europe/Amsterdam|
|timezone|Europe/Andorra|
|timezone|Europe/Astrakhan|
|timezone|Europe/Athens|
|timezone|Europe/Belgrade|
|timezone|Europe/Berlin|
|timezone|Europe/Bratislava|
|timezone|Europe/Brussels|
|timezone|Europe/Bucharest|
|timezone|Europe/Budapest|
|timezone|Europe/Busingen|
|timezone|Europe/Chisinau|
|timezone|Europe/Copenhagen|
|timezone|Europe/Dublin|
|timezone|Europe/Gibraltar|
|timezone|Europe/Guernsey|
|timezone|Europe/Helsinki|
|timezone|Europe/Isle_of_Man|
|timezone|Europe/Istanbul|
|timezone|Europe/Jersey|
|timezone|Europe/Kaliningrad|
|timezone|Europe/Kiev|
|timezone|Europe/Kirov|
|timezone|Europe/Lisbon|
|timezone|Europe/Ljubljana|
|timezone|Europe/London|
|timezone|Europe/Luxembourg|
|timezone|Europe/Madrid|
|timezone|Europe/Malta|
|timezone|Europe/Mariehamn|
|timezone|Europe/Minsk|
|timezone|Europe/Monaco|
|timezone|Europe/Moscow|
|timezone|Europe/Oslo|
|timezone|Europe/Paris|
|timezone|Europe/Podgorica|
|timezone|Europe/Prague|
|timezone|Europe/Riga|
|timezone|Europe/Rome|
|timezone|Europe/Samara|
|timezone|Europe/San_Marino|
|timezone|Europe/Sarajevo|
|timezone|Europe/Saratov|
|timezone|Europe/Simferopol|
|timezone|Europe/Skopje|
|timezone|Europe/Sofia|
|timezone|Europe/Stockholm|
|timezone|Europe/Tallinn|
|timezone|Europe/Tirane|
|timezone|Europe/Ulyanovsk|
|timezone|Europe/Uzhgorod|
|timezone|Europe/Vaduz|
|timezone|Europe/Vatican|
|timezone|Europe/Vienna|
|timezone|Europe/Vilnius|
|timezone|Europe/Volgograd|
|timezone|Europe/Warsaw|
|timezone|Europe/Zagreb|
|timezone|Europe/Zaporozhye|
|timezone|Europe/Zurich|
|timezone|GMT|
|timezone|Indian/Antananarivo|
|timezone|Indian/Chagos|
|timezone|Indian/Christmas|
|timezone|Indian/Cocos|
|timezone|Indian/Comoro|
|timezone|Indian/Kerguelen|
|timezone|Indian/Mahe|
|timezone|Indian/Maldives|
|timezone|Indian/Mauritius|
|timezone|Indian/Mayotte|
|timezone|Indian/Reunion|
|timezone|Pacific/Apia|
|timezone|Pacific/Auckland|
|timezone|Pacific/Bougainville|
|timezone|Pacific/Chatham|
|timezone|Pacific/Chuuk|
|timezone|Pacific/Easter|
|timezone|Pacific/Efate|
|timezone|Pacific/Enderbury|
|timezone|Pacific/Fakaofo|
|timezone|Pacific/Fiji|
|timezone|Pacific/Funafuti|
|timezone|Pacific/Galapagos|
|timezone|Pacific/Gambier|
|timezone|Pacific/Guadalcanal|
|timezone|Pacific/Guam|
|timezone|Pacific/Honolulu|
|timezone|Pacific/Kiritimati|
|timezone|Pacific/Kosrae|
|timezone|Pacific/Kwajalein|
|timezone|Pacific/Majuro|
|timezone|Pacific/Marquesas|
|timezone|Pacific/Midway|
|timezone|Pacific/Nauru|
|timezone|Pacific/Niue|
|timezone|Pacific/Norfolk|
|timezone|Pacific/Noumea|
|timezone|Pacific/Pago_Pago|
|timezone|Pacific/Palau|
|timezone|Pacific/Pitcairn|
|timezone|Pacific/Pohnpei|
|timezone|Pacific/Port_Moresby|
|timezone|Pacific/Rarotonga|
|timezone|Pacific/Saipan|
|timezone|Pacific/Tahiti|
|timezone|Pacific/Tarawa|
|timezone|Pacific/Tongatapu|
|timezone|Pacific/Wake|
|timezone|Pacific/Wallis|
|timezone|US/Alaska|
|timezone|US/Arizona|
|timezone|US/Central|
|timezone|US/Eastern|
|timezone|US/Hawaii|
|timezone|US/Mountain|
|timezone|US/Pacific|
|timezone|UTC|
|effective_membership_level|1|
|effective_membership_level|8|
|effective_membership_level|15|

<h2 id="tocS_Person">Person</h2>
<!-- backwards compatibility -->
<a id="schemaperson"></a>
<a id="schema_Person"></a>
<a id="tocSperson"></a>
<a id="tocsperson"></a>

```json
{
  "id": 0,
  "name": "string",
  "distinct_ids": [
    "string"
  ],
  "properties": {
    "property1": null,
    "property2": null
  },
  "created_at": "2019-08-24T14:15:22Z",
  "uuid": "095be615-a8ad-4c33-8e9c-c7612fbf6c9f"
}

```

### Properties

|Name|Type|Required|Restrictions|Description|
|---|---|---|---|---|
|id|integer|true|read-only|none|
|name|string|true|read-only|none|
|distinct_ids|[string]|true|read-only|none|
|properties|object|false|none|none|
|» **additionalProperties**|any|false|none|none|
|created_at|string(date-time)|true|read-only|none|
|uuid|string(uuid)|true|read-only|none|

<h2 id="tocS_Plugin">Plugin</h2>
<!-- backwards compatibility -->
<a id="schemaplugin"></a>
<a id="schema_Plugin"></a>
<a id="tocSplugin"></a>
<a id="tocsplugin"></a>

```json
{
  "id": 0,
  "plugin_type": "local",
  "name": "string",
  "description": "string",
  "url": "string",
  "config_schema": {
    "property1": null,
    "property2": null
  },
  "tag": "string",
  "source": "string",
  "latest_tag": "string",
  "is_global": true,
  "organization_id": "7c60d51f-b44e-4682-87d6-449835ea4de6",
  "organization_name": "string",
  "capabilities": {
    "property1": null,
    "property2": null
  },
  "metrics": {
    "property1": null,
    "property2": null
  },
  "public_jobs": {
    "property1": null,
    "property2": null
  }
}

```

### Properties

|Name|Type|Required|Restrictions|Description|
|---|---|---|---|---|
|id|integer|true|read-only|none|
|plugin_type|string¦null|false|none|none|
|name|string¦null|false|none|none|
|description|string¦null|false|none|none|
|url|string¦null|true|read-only|none|
|config_schema|object|false|none|none|
|» **additionalProperties**|any|false|none|none|
|tag|string¦null|false|none|none|
|source|string¦null|false|none|none|
|latest_tag|string|true|read-only|none|
|is_global|boolean|false|none|none|
|organization_id|string(uuid)|true|read-only|none|
|organization_name|string|true|read-only|none|
|capabilities|object|false|none|none|
|» **additionalProperties**|any|false|none|none|
|metrics|object¦null|false|none|none|
|» **additionalProperties**|any|false|none|none|
|public_jobs|object¦null|false|none|none|
|» **additionalProperties**|any|false|none|none|

#### Enumerated Values

|Property|Value|
|---|---|
|plugin_type|local|
|plugin_type|custom|
|plugin_type|repository|
|plugin_type|source|
|plugin_type||
|plugin_type|null|

<h2 id="tocS_PluginConfig">PluginConfig</h2>
<!-- backwards compatibility -->
<a id="schemapluginconfig"></a>
<a id="schema_PluginConfig"></a>
<a id="tocSpluginconfig"></a>
<a id="tocspluginconfig"></a>

```json
{
  "id": 0,
  "plugin": 0,
  "enabled": true,
  "order": -2147483648,
  "config": "string",
  "error": {
    "property1": null,
    "property2": null
  },
  "team_id": 0
}

```

### Properties

|Name|Type|Required|Restrictions|Description|
|---|---|---|---|---|
|id|integer|true|read-only|none|
|plugin|integer|true|none|none|
|enabled|boolean|false|none|none|
|order|integer|true|none|none|
|config|string|true|read-only|none|
|error|object¦null|false|none|none|
|» **additionalProperties**|any|false|none|none|
|team_id|integer¦null|true|read-only|none|

<h2 id="tocS_PluginLogEntry">PluginLogEntry</h2>
<!-- backwards compatibility -->
<a id="schemapluginlogentry"></a>
<a id="schema_PluginLogEntry"></a>
<a id="tocSpluginlogentry"></a>
<a id="tocspluginlogentry"></a>

```json
{
  "id": "497f6eca-6276-4993-bfeb-53cbbbba6f08",
  "team_id": 0,
  "plugin_id": 0,
  "timestamp": "2019-08-24T14:15:22Z",
  "source": "SYSTEM",
  "type": "DEBUG",
  "message": "string",
  "instance_id": "06587974-2dbe-4e10-8bf9-38cce0f5a366"
}

```

### Properties

|Name|Type|Required|Restrictions|Description|
|---|---|---|---|---|
|id|string(uuid)|true|read-only|none|
|team_id|integer|true|read-only|none|
|plugin_id|integer|true|read-only|none|
|timestamp|string(date-time)|true|read-only|none|
|source|string|true|read-only|none|
|type|string|true|read-only|none|
|message|string|true|read-only|none|
|instance_id|string(uuid)|true|read-only|none|

#### Enumerated Values

|Property|Value|
|---|---|
|source|SYSTEM|
|source|PLUGIN|
|source|CONSOLE|
|type|DEBUG|
|type|LOG|
|type|INFO|
|type|WARN|
|type|ERROR|

<h2 id="tocS_Property">Property</h2>
<!-- backwards compatibility -->
<a id="schemaproperty"></a>
<a id="schema_Property"></a>
<a id="tocSproperty"></a>
<a id="tocsproperty"></a>

```json
{
  "key": "string",
  "value": "string",
  "operator": "exact",
  "type": "event"
}

```

### Properties

|Name|Type|Required|Restrictions|Description|
|---|---|---|---|---|
|key|string|true|none|Key of the property you're filtering on. For example `email` or `$current_url`|
|value|string|true|none|Value of your filter. Can be an array. For example `test@example.com` or `https://example.com/test/`. Can be an array, like `["test@example.com","ok@example.com"]`|
|operator|string|false|none|none|
|type|string|false|none|none|

#### Enumerated Values

|Property|Value|
|---|---|
|operator|exact|
|operator|is_not|
|operator|icontains|
|operator|not_icontains|
|operator|regex|
|operator|not_regex|
|operator|gt|
|operator|lt|
|operator|is_set|
|operator|is_not_set|
|operator|is_date_after|
|operator|is_date_before|
|type|event|
|type|person|
|type|cohort|
|type|element|
|type|static-cohort|
|type|precalculated-cohort|
|type|group|

<h2 id="tocS_Team">Team</h2>
<!-- backwards compatibility -->
<a id="schemateam"></a>
<a id="schema_Team"></a>
<a id="tocSteam"></a>
<a id="tocsteam"></a>

```json
{
  "id": 0,
  "uuid": "095be615-a8ad-4c33-8e9c-c7612fbf6c9f",
  "organization": "452c1a86-a0af-475b-b03f-724878b0f387",
  "api_token": "string",
  "app_urls": [
    "string"
  ],
  "name": "string",
  "slack_incoming_webhook": "string",
  "created_at": "2019-08-24T14:15:22Z",
  "updated_at": "2019-08-24T14:15:22Z",
  "anonymize_ips": true,
  "completed_snippet_onboarding": true,
  "ingested_event": true,
  "test_account_filters": {
    "property1": null,
    "property2": null
  },
  "path_cleaning_filters": {
    "property1": null,
    "property2": null
  },
  "is_demo": true,
  "timezone": "Africa/Abidjan",
  "data_attributes": {
    "property1": null,
    "property2": null
  },
  "correlation_config": {
    "property1": null,
    "property2": null
  },
  "session_recording_opt_in": true,
  "effective_membership_level": 1,
  "access_control": true,
  "has_group_types": true
}

```

### Properties

|Name|Type|Required|Restrictions|Description|
|---|---|---|---|---|
|id|integer|true|read-only|none|
|uuid|string(uuid)|true|read-only|none|
|organization|string(uuid)|true|read-only|none|
|api_token|string|true|read-only|none|
|app_urls|[string]|false|none|none|
|name|string|false|none|none|
|slack_incoming_webhook|string¦null|false|none|none|
|created_at|string(date-time)|true|read-only|none|
|updated_at|string(date-time)|true|read-only|none|
|anonymize_ips|boolean|false|none|none|
|completed_snippet_onboarding|boolean|false|none|none|
|ingested_event|boolean|true|read-only|none|
|test_account_filters|object|false|none|none|
|» **additionalProperties**|any|false|none|none|
|path_cleaning_filters|object¦null|false|none|none|
|» **additionalProperties**|any|false|none|none|
|is_demo|boolean|true|read-only|none|
|timezone|string|false|none|none|
|data_attributes|object|false|none|none|
|» **additionalProperties**|any|false|none|none|
|correlation_config|object¦null|false|none|none|
|» **additionalProperties**|any|false|none|none|
|session_recording_opt_in|boolean|false|none|none|
|effective_membership_level|integer¦null|true|read-only|none|
|access_control|boolean|false|none|none|
|has_group_types|boolean|true|read-only|none|

#### Enumerated Values

|Property|Value|
|---|---|
|timezone|Africa/Abidjan|
|timezone|Africa/Accra|
|timezone|Africa/Addis_Ababa|
|timezone|Africa/Algiers|
|timezone|Africa/Asmara|
|timezone|Africa/Bamako|
|timezone|Africa/Bangui|
|timezone|Africa/Banjul|
|timezone|Africa/Bissau|
|timezone|Africa/Blantyre|
|timezone|Africa/Brazzaville|
|timezone|Africa/Bujumbura|
|timezone|Africa/Cairo|
|timezone|Africa/Casablanca|
|timezone|Africa/Ceuta|
|timezone|Africa/Conakry|
|timezone|Africa/Dakar|
|timezone|Africa/Dar_es_Salaam|
|timezone|Africa/Djibouti|
|timezone|Africa/Douala|
|timezone|Africa/El_Aaiun|
|timezone|Africa/Freetown|
|timezone|Africa/Gaborone|
|timezone|Africa/Harare|
|timezone|Africa/Johannesburg|
|timezone|Africa/Juba|
|timezone|Africa/Kampala|
|timezone|Africa/Khartoum|
|timezone|Africa/Kigali|
|timezone|Africa/Kinshasa|
|timezone|Africa/Lagos|
|timezone|Africa/Libreville|
|timezone|Africa/Lome|
|timezone|Africa/Luanda|
|timezone|Africa/Lubumbashi|
|timezone|Africa/Lusaka|
|timezone|Africa/Malabo|
|timezone|Africa/Maputo|
|timezone|Africa/Maseru|
|timezone|Africa/Mbabane|
|timezone|Africa/Mogadishu|
|timezone|Africa/Monrovia|
|timezone|Africa/Nairobi|
|timezone|Africa/Ndjamena|
|timezone|Africa/Niamey|
|timezone|Africa/Nouakchott|
|timezone|Africa/Ouagadougou|
|timezone|Africa/Porto-Novo|
|timezone|Africa/Sao_Tome|
|timezone|Africa/Tripoli|
|timezone|Africa/Tunis|
|timezone|Africa/Windhoek|
|timezone|America/Adak|
|timezone|America/Anchorage|
|timezone|America/Anguilla|
|timezone|America/Antigua|
|timezone|America/Araguaina|
|timezone|America/Argentina/Buenos_Aires|
|timezone|America/Argentina/Catamarca|
|timezone|America/Argentina/Cordoba|
|timezone|America/Argentina/Jujuy|
|timezone|America/Argentina/La_Rioja|
|timezone|America/Argentina/Mendoza|
|timezone|America/Argentina/Rio_Gallegos|
|timezone|America/Argentina/Salta|
|timezone|America/Argentina/San_Juan|
|timezone|America/Argentina/San_Luis|
|timezone|America/Argentina/Tucuman|
|timezone|America/Argentina/Ushuaia|
|timezone|America/Aruba|
|timezone|America/Asuncion|
|timezone|America/Atikokan|
|timezone|America/Bahia|
|timezone|America/Bahia_Banderas|
|timezone|America/Barbados|
|timezone|America/Belem|
|timezone|America/Belize|
|timezone|America/Blanc-Sablon|
|timezone|America/Boa_Vista|
|timezone|America/Bogota|
|timezone|America/Boise|
|timezone|America/Cambridge_Bay|
|timezone|America/Campo_Grande|
|timezone|America/Cancun|
|timezone|America/Caracas|
|timezone|America/Cayenne|
|timezone|America/Cayman|
|timezone|America/Chicago|
|timezone|America/Chihuahua|
|timezone|America/Costa_Rica|
|timezone|America/Creston|
|timezone|America/Cuiaba|
|timezone|America/Curacao|
|timezone|America/Danmarkshavn|
|timezone|America/Dawson|
|timezone|America/Dawson_Creek|
|timezone|America/Denver|
|timezone|America/Detroit|
|timezone|America/Dominica|
|timezone|America/Edmonton|
|timezone|America/Eirunepe|
|timezone|America/El_Salvador|
|timezone|America/Fort_Nelson|
|timezone|America/Fortaleza|
|timezone|America/Glace_Bay|
|timezone|America/Goose_Bay|
|timezone|America/Grand_Turk|
|timezone|America/Grenada|
|timezone|America/Guadeloupe|
|timezone|America/Guatemala|
|timezone|America/Guayaquil|
|timezone|America/Guyana|
|timezone|America/Halifax|
|timezone|America/Havana|
|timezone|America/Hermosillo|
|timezone|America/Indiana/Indianapolis|
|timezone|America/Indiana/Knox|
|timezone|America/Indiana/Marengo|
|timezone|America/Indiana/Petersburg|
|timezone|America/Indiana/Tell_City|
|timezone|America/Indiana/Vevay|
|timezone|America/Indiana/Vincennes|
|timezone|America/Indiana/Winamac|
|timezone|America/Inuvik|
|timezone|America/Iqaluit|
|timezone|America/Jamaica|
|timezone|America/Juneau|
|timezone|America/Kentucky/Louisville|
|timezone|America/Kentucky/Monticello|
|timezone|America/Kralendijk|
|timezone|America/La_Paz|
|timezone|America/Lima|
|timezone|America/Los_Angeles|
|timezone|America/Lower_Princes|
|timezone|America/Maceio|
|timezone|America/Managua|
|timezone|America/Manaus|
|timezone|America/Marigot|
|timezone|America/Martinique|
|timezone|America/Matamoros|
|timezone|America/Mazatlan|
|timezone|America/Menominee|
|timezone|America/Merida|
|timezone|America/Metlakatla|
|timezone|America/Mexico_City|
|timezone|America/Miquelon|
|timezone|America/Moncton|
|timezone|America/Monterrey|
|timezone|America/Montevideo|
|timezone|America/Montserrat|
|timezone|America/Nassau|
|timezone|America/New_York|
|timezone|America/Nipigon|
|timezone|America/Nome|
|timezone|America/Noronha|
|timezone|America/North_Dakota/Beulah|
|timezone|America/North_Dakota/Center|
|timezone|America/North_Dakota/New_Salem|
|timezone|America/Nuuk|
|timezone|America/Ojinaga|
|timezone|America/Panama|
|timezone|America/Pangnirtung|
|timezone|America/Paramaribo|
|timezone|America/Phoenix|
|timezone|America/Port-au-Prince|
|timezone|America/Port_of_Spain|
|timezone|America/Porto_Velho|
|timezone|America/Puerto_Rico|
|timezone|America/Punta_Arenas|
|timezone|America/Rainy_River|
|timezone|America/Rankin_Inlet|
|timezone|America/Recife|
|timezone|America/Regina|
|timezone|America/Resolute|
|timezone|America/Rio_Branco|
|timezone|America/Santarem|
|timezone|America/Santiago|
|timezone|America/Santo_Domingo|
|timezone|America/Sao_Paulo|
|timezone|America/Scoresbysund|
|timezone|America/Sitka|
|timezone|America/St_Barthelemy|
|timezone|America/St_Johns|
|timezone|America/St_Kitts|
|timezone|America/St_Lucia|
|timezone|America/St_Thomas|
|timezone|America/St_Vincent|
|timezone|America/Swift_Current|
|timezone|America/Tegucigalpa|
|timezone|America/Thule|
|timezone|America/Thunder_Bay|
|timezone|America/Tijuana|
|timezone|America/Toronto|
|timezone|America/Tortola|
|timezone|America/Vancouver|
|timezone|America/Whitehorse|
|timezone|America/Winnipeg|
|timezone|America/Yakutat|
|timezone|America/Yellowknife|
|timezone|Antarctica/Casey|
|timezone|Antarctica/Davis|
|timezone|Antarctica/DumontDUrville|
|timezone|Antarctica/Macquarie|
|timezone|Antarctica/Mawson|
|timezone|Antarctica/McMurdo|
|timezone|Antarctica/Palmer|
|timezone|Antarctica/Rothera|
|timezone|Antarctica/Syowa|
|timezone|Antarctica/Troll|
|timezone|Antarctica/Vostok|
|timezone|Arctic/Longyearbyen|
|timezone|Asia/Aden|
|timezone|Asia/Almaty|
|timezone|Asia/Amman|
|timezone|Asia/Anadyr|
|timezone|Asia/Aqtau|
|timezone|Asia/Aqtobe|
|timezone|Asia/Ashgabat|
|timezone|Asia/Atyrau|
|timezone|Asia/Baghdad|
|timezone|Asia/Bahrain|
|timezone|Asia/Baku|
|timezone|Asia/Bangkok|
|timezone|Asia/Barnaul|
|timezone|Asia/Beirut|
|timezone|Asia/Bishkek|
|timezone|Asia/Brunei|
|timezone|Asia/Chita|
|timezone|Asia/Choibalsan|
|timezone|Asia/Colombo|
|timezone|Asia/Damascus|
|timezone|Asia/Dhaka|
|timezone|Asia/Dili|
|timezone|Asia/Dubai|
|timezone|Asia/Dushanbe|
|timezone|Asia/Famagusta|
|timezone|Asia/Gaza|
|timezone|Asia/Hebron|
|timezone|Asia/Ho_Chi_Minh|
|timezone|Asia/Hong_Kong|
|timezone|Asia/Hovd|
|timezone|Asia/Irkutsk|
|timezone|Asia/Jakarta|
|timezone|Asia/Jayapura|
|timezone|Asia/Jerusalem|
|timezone|Asia/Kabul|
|timezone|Asia/Kamchatka|
|timezone|Asia/Karachi|
|timezone|Asia/Kathmandu|
|timezone|Asia/Khandyga|
|timezone|Asia/Kolkata|
|timezone|Asia/Krasnoyarsk|
|timezone|Asia/Kuala_Lumpur|
|timezone|Asia/Kuching|
|timezone|Asia/Kuwait|
|timezone|Asia/Macau|
|timezone|Asia/Magadan|
|timezone|Asia/Makassar|
|timezone|Asia/Manila|
|timezone|Asia/Muscat|
|timezone|Asia/Nicosia|
|timezone|Asia/Novokuznetsk|
|timezone|Asia/Novosibirsk|
|timezone|Asia/Omsk|
|timezone|Asia/Oral|
|timezone|Asia/Phnom_Penh|
|timezone|Asia/Pontianak|
|timezone|Asia/Pyongyang|
|timezone|Asia/Qatar|
|timezone|Asia/Qostanay|
|timezone|Asia/Qyzylorda|
|timezone|Asia/Riyadh|
|timezone|Asia/Sakhalin|
|timezone|Asia/Samarkand|
|timezone|Asia/Seoul|
|timezone|Asia/Shanghai|
|timezone|Asia/Singapore|
|timezone|Asia/Srednekolymsk|
|timezone|Asia/Taipei|
|timezone|Asia/Tashkent|
|timezone|Asia/Tbilisi|
|timezone|Asia/Tehran|
|timezone|Asia/Thimphu|
|timezone|Asia/Tokyo|
|timezone|Asia/Tomsk|
|timezone|Asia/Ulaanbaatar|
|timezone|Asia/Urumqi|
|timezone|Asia/Ust-Nera|
|timezone|Asia/Vientiane|
|timezone|Asia/Vladivostok|
|timezone|Asia/Yakutsk|
|timezone|Asia/Yangon|
|timezone|Asia/Yekaterinburg|
|timezone|Asia/Yerevan|
|timezone|Atlantic/Azores|
|timezone|Atlantic/Bermuda|
|timezone|Atlantic/Canary|
|timezone|Atlantic/Cape_Verde|
|timezone|Atlantic/Faroe|
|timezone|Atlantic/Madeira|
|timezone|Atlantic/Reykjavik|
|timezone|Atlantic/South_Georgia|
|timezone|Atlantic/St_Helena|
|timezone|Atlantic/Stanley|
|timezone|Australia/Adelaide|
|timezone|Australia/Brisbane|
|timezone|Australia/Broken_Hill|
|timezone|Australia/Darwin|
|timezone|Australia/Eucla|
|timezone|Australia/Hobart|
|timezone|Australia/Lindeman|
|timezone|Australia/Lord_Howe|
|timezone|Australia/Melbourne|
|timezone|Australia/Perth|
|timezone|Australia/Sydney|
|timezone|Canada/Atlantic|
|timezone|Canada/Central|
|timezone|Canada/Eastern|
|timezone|Canada/Mountain|
|timezone|Canada/Newfoundland|
|timezone|Canada/Pacific|
|timezone|Europe/Amsterdam|
|timezone|Europe/Andorra|
|timezone|Europe/Astrakhan|
|timezone|Europe/Athens|
|timezone|Europe/Belgrade|
|timezone|Europe/Berlin|
|timezone|Europe/Bratislava|
|timezone|Europe/Brussels|
|timezone|Europe/Bucharest|
|timezone|Europe/Budapest|
|timezone|Europe/Busingen|
|timezone|Europe/Chisinau|
|timezone|Europe/Copenhagen|
|timezone|Europe/Dublin|
|timezone|Europe/Gibraltar|
|timezone|Europe/Guernsey|
|timezone|Europe/Helsinki|
|timezone|Europe/Isle_of_Man|
|timezone|Europe/Istanbul|
|timezone|Europe/Jersey|
|timezone|Europe/Kaliningrad|
|timezone|Europe/Kiev|
|timezone|Europe/Kirov|
|timezone|Europe/Lisbon|
|timezone|Europe/Ljubljana|
|timezone|Europe/London|
|timezone|Europe/Luxembourg|
|timezone|Europe/Madrid|
|timezone|Europe/Malta|
|timezone|Europe/Mariehamn|
|timezone|Europe/Minsk|
|timezone|Europe/Monaco|
|timezone|Europe/Moscow|
|timezone|Europe/Oslo|
|timezone|Europe/Paris|
|timezone|Europe/Podgorica|
|timezone|Europe/Prague|
|timezone|Europe/Riga|
|timezone|Europe/Rome|
|timezone|Europe/Samara|
|timezone|Europe/San_Marino|
|timezone|Europe/Sarajevo|
|timezone|Europe/Saratov|
|timezone|Europe/Simferopol|
|timezone|Europe/Skopje|
|timezone|Europe/Sofia|
|timezone|Europe/Stockholm|
|timezone|Europe/Tallinn|
|timezone|Europe/Tirane|
|timezone|Europe/Ulyanovsk|
|timezone|Europe/Uzhgorod|
|timezone|Europe/Vaduz|
|timezone|Europe/Vatican|
|timezone|Europe/Vienna|
|timezone|Europe/Vilnius|
|timezone|Europe/Volgograd|
|timezone|Europe/Warsaw|
|timezone|Europe/Zagreb|
|timezone|Europe/Zaporozhye|
|timezone|Europe/Zurich|
|timezone|GMT|
|timezone|Indian/Antananarivo|
|timezone|Indian/Chagos|
|timezone|Indian/Christmas|
|timezone|Indian/Cocos|
|timezone|Indian/Comoro|
|timezone|Indian/Kerguelen|
|timezone|Indian/Mahe|
|timezone|Indian/Maldives|
|timezone|Indian/Mauritius|
|timezone|Indian/Mayotte|
|timezone|Indian/Reunion|
|timezone|Pacific/Apia|
|timezone|Pacific/Auckland|
|timezone|Pacific/Bougainville|
|timezone|Pacific/Chatham|
|timezone|Pacific/Chuuk|
|timezone|Pacific/Easter|
|timezone|Pacific/Efate|
|timezone|Pacific/Enderbury|
|timezone|Pacific/Fakaofo|
|timezone|Pacific/Fiji|
|timezone|Pacific/Funafuti|
|timezone|Pacific/Galapagos|
|timezone|Pacific/Gambier|
|timezone|Pacific/Guadalcanal|
|timezone|Pacific/Guam|
|timezone|Pacific/Honolulu|
|timezone|Pacific/Kiritimati|
|timezone|Pacific/Kosrae|
|timezone|Pacific/Kwajalein|
|timezone|Pacific/Majuro|
|timezone|Pacific/Marquesas|
|timezone|Pacific/Midway|
|timezone|Pacific/Nauru|
|timezone|Pacific/Niue|
|timezone|Pacific/Norfolk|
|timezone|Pacific/Noumea|
|timezone|Pacific/Pago_Pago|
|timezone|Pacific/Palau|
|timezone|Pacific/Pitcairn|
|timezone|Pacific/Pohnpei|
|timezone|Pacific/Port_Moresby|
|timezone|Pacific/Rarotonga|
|timezone|Pacific/Saipan|
|timezone|Pacific/Tahiti|
|timezone|Pacific/Tarawa|
|timezone|Pacific/Tongatapu|
|timezone|Pacific/Wake|
|timezone|Pacific/Wallis|
|timezone|US/Alaska|
|timezone|US/Arizona|
|timezone|US/Central|
|timezone|US/Eastern|
|timezone|US/Hawaii|
|timezone|US/Mountain|
|timezone|US/Pacific|
|timezone|UTC|
|effective_membership_level|1|
|effective_membership_level|8|
|effective_membership_level|15|

<h2 id="tocS_TeamBasic">TeamBasic</h2>
<!-- backwards compatibility -->
<a id="schemateambasic"></a>
<a id="schema_TeamBasic"></a>
<a id="tocSteambasic"></a>
<a id="tocsteambasic"></a>

```json
{
  "id": 0,
  "uuid": "095be615-a8ad-4c33-8e9c-c7612fbf6c9f",
  "organization": "452c1a86-a0af-475b-b03f-724878b0f387",
  "api_token": "stringstri",
  "name": "string",
  "completed_snippet_onboarding": true,
  "ingested_event": true,
  "is_demo": true,
  "timezone": "Africa/Abidjan",
  "access_control": true,
  "effective_membership_level": 1
}

```

Serializer for `Team` model with minimal attributes to speeed up loading and transfer times.
Also used for nested serializers.

### Properties

|Name|Type|Required|Restrictions|Description|
|---|---|---|---|---|
|id|integer|true|read-only|none|
|uuid|string(uuid)|true|read-only|none|
|organization|string(uuid)|true|none|none|
|api_token|string|false|none|none|
|name|string|false|none|none|
|completed_snippet_onboarding|boolean|false|none|none|
|ingested_event|boolean|false|none|none|
|is_demo|boolean|false|none|none|
|timezone|string|false|none|none|
|access_control|boolean|false|none|none|
|effective_membership_level|integer¦null|true|read-only|none|

#### Enumerated Values

|Property|Value|
|---|---|
|timezone|Africa/Abidjan|
|timezone|Africa/Accra|
|timezone|Africa/Addis_Ababa|
|timezone|Africa/Algiers|
|timezone|Africa/Asmara|
|timezone|Africa/Bamako|
|timezone|Africa/Bangui|
|timezone|Africa/Banjul|
|timezone|Africa/Bissau|
|timezone|Africa/Blantyre|
|timezone|Africa/Brazzaville|
|timezone|Africa/Bujumbura|
|timezone|Africa/Cairo|
|timezone|Africa/Casablanca|
|timezone|Africa/Ceuta|
|timezone|Africa/Conakry|
|timezone|Africa/Dakar|
|timezone|Africa/Dar_es_Salaam|
|timezone|Africa/Djibouti|
|timezone|Africa/Douala|
|timezone|Africa/El_Aaiun|
|timezone|Africa/Freetown|
|timezone|Africa/Gaborone|
|timezone|Africa/Harare|
|timezone|Africa/Johannesburg|
|timezone|Africa/Juba|
|timezone|Africa/Kampala|
|timezone|Africa/Khartoum|
|timezone|Africa/Kigali|
|timezone|Africa/Kinshasa|
|timezone|Africa/Lagos|
|timezone|Africa/Libreville|
|timezone|Africa/Lome|
|timezone|Africa/Luanda|
|timezone|Africa/Lubumbashi|
|timezone|Africa/Lusaka|
|timezone|Africa/Malabo|
|timezone|Africa/Maputo|
|timezone|Africa/Maseru|
|timezone|Africa/Mbabane|
|timezone|Africa/Mogadishu|
|timezone|Africa/Monrovia|
|timezone|Africa/Nairobi|
|timezone|Africa/Ndjamena|
|timezone|Africa/Niamey|
|timezone|Africa/Nouakchott|
|timezone|Africa/Ouagadougou|
|timezone|Africa/Porto-Novo|
|timezone|Africa/Sao_Tome|
|timezone|Africa/Tripoli|
|timezone|Africa/Tunis|
|timezone|Africa/Windhoek|
|timezone|America/Adak|
|timezone|America/Anchorage|
|timezone|America/Anguilla|
|timezone|America/Antigua|
|timezone|America/Araguaina|
|timezone|America/Argentina/Buenos_Aires|
|timezone|America/Argentina/Catamarca|
|timezone|America/Argentina/Cordoba|
|timezone|America/Argentina/Jujuy|
|timezone|America/Argentina/La_Rioja|
|timezone|America/Argentina/Mendoza|
|timezone|America/Argentina/Rio_Gallegos|
|timezone|America/Argentina/Salta|
|timezone|America/Argentina/San_Juan|
|timezone|America/Argentina/San_Luis|
|timezone|America/Argentina/Tucuman|
|timezone|America/Argentina/Ushuaia|
|timezone|America/Aruba|
|timezone|America/Asuncion|
|timezone|America/Atikokan|
|timezone|America/Bahia|
|timezone|America/Bahia_Banderas|
|timezone|America/Barbados|
|timezone|America/Belem|
|timezone|America/Belize|
|timezone|America/Blanc-Sablon|
|timezone|America/Boa_Vista|
|timezone|America/Bogota|
|timezone|America/Boise|
|timezone|America/Cambridge_Bay|
|timezone|America/Campo_Grande|
|timezone|America/Cancun|
|timezone|America/Caracas|
|timezone|America/Cayenne|
|timezone|America/Cayman|
|timezone|America/Chicago|
|timezone|America/Chihuahua|
|timezone|America/Costa_Rica|
|timezone|America/Creston|
|timezone|America/Cuiaba|
|timezone|America/Curacao|
|timezone|America/Danmarkshavn|
|timezone|America/Dawson|
|timezone|America/Dawson_Creek|
|timezone|America/Denver|
|timezone|America/Detroit|
|timezone|America/Dominica|
|timezone|America/Edmonton|
|timezone|America/Eirunepe|
|timezone|America/El_Salvador|
|timezone|America/Fort_Nelson|
|timezone|America/Fortaleza|
|timezone|America/Glace_Bay|
|timezone|America/Goose_Bay|
|timezone|America/Grand_Turk|
|timezone|America/Grenada|
|timezone|America/Guadeloupe|
|timezone|America/Guatemala|
|timezone|America/Guayaquil|
|timezone|America/Guyana|
|timezone|America/Halifax|
|timezone|America/Havana|
|timezone|America/Hermosillo|
|timezone|America/Indiana/Indianapolis|
|timezone|America/Indiana/Knox|
|timezone|America/Indiana/Marengo|
|timezone|America/Indiana/Petersburg|
|timezone|America/Indiana/Tell_City|
|timezone|America/Indiana/Vevay|
|timezone|America/Indiana/Vincennes|
|timezone|America/Indiana/Winamac|
|timezone|America/Inuvik|
|timezone|America/Iqaluit|
|timezone|America/Jamaica|
|timezone|America/Juneau|
|timezone|America/Kentucky/Louisville|
|timezone|America/Kentucky/Monticello|
|timezone|America/Kralendijk|
|timezone|America/La_Paz|
|timezone|America/Lima|
|timezone|America/Los_Angeles|
|timezone|America/Lower_Princes|
|timezone|America/Maceio|
|timezone|America/Managua|
|timezone|America/Manaus|
|timezone|America/Marigot|
|timezone|America/Martinique|
|timezone|America/Matamoros|
|timezone|America/Mazatlan|
|timezone|America/Menominee|
|timezone|America/Merida|
|timezone|America/Metlakatla|
|timezone|America/Mexico_City|
|timezone|America/Miquelon|
|timezone|America/Moncton|
|timezone|America/Monterrey|
|timezone|America/Montevideo|
|timezone|America/Montserrat|
|timezone|America/Nassau|
|timezone|America/New_York|
|timezone|America/Nipigon|
|timezone|America/Nome|
|timezone|America/Noronha|
|timezone|America/North_Dakota/Beulah|
|timezone|America/North_Dakota/Center|
|timezone|America/North_Dakota/New_Salem|
|timezone|America/Nuuk|
|timezone|America/Ojinaga|
|timezone|America/Panama|
|timezone|America/Pangnirtung|
|timezone|America/Paramaribo|
|timezone|America/Phoenix|
|timezone|America/Port-au-Prince|
|timezone|America/Port_of_Spain|
|timezone|America/Porto_Velho|
|timezone|America/Puerto_Rico|
|timezone|America/Punta_Arenas|
|timezone|America/Rainy_River|
|timezone|America/Rankin_Inlet|
|timezone|America/Recife|
|timezone|America/Regina|
|timezone|America/Resolute|
|timezone|America/Rio_Branco|
|timezone|America/Santarem|
|timezone|America/Santiago|
|timezone|America/Santo_Domingo|
|timezone|America/Sao_Paulo|
|timezone|America/Scoresbysund|
|timezone|America/Sitka|
|timezone|America/St_Barthelemy|
|timezone|America/St_Johns|
|timezone|America/St_Kitts|
|timezone|America/St_Lucia|
|timezone|America/St_Thomas|
|timezone|America/St_Vincent|
|timezone|America/Swift_Current|
|timezone|America/Tegucigalpa|
|timezone|America/Thule|
|timezone|America/Thunder_Bay|
|timezone|America/Tijuana|
|timezone|America/Toronto|
|timezone|America/Tortola|
|timezone|America/Vancouver|
|timezone|America/Whitehorse|
|timezone|America/Winnipeg|
|timezone|America/Yakutat|
|timezone|America/Yellowknife|
|timezone|Antarctica/Casey|
|timezone|Antarctica/Davis|
|timezone|Antarctica/DumontDUrville|
|timezone|Antarctica/Macquarie|
|timezone|Antarctica/Mawson|
|timezone|Antarctica/McMurdo|
|timezone|Antarctica/Palmer|
|timezone|Antarctica/Rothera|
|timezone|Antarctica/Syowa|
|timezone|Antarctica/Troll|
|timezone|Antarctica/Vostok|
|timezone|Arctic/Longyearbyen|
|timezone|Asia/Aden|
|timezone|Asia/Almaty|
|timezone|Asia/Amman|
|timezone|Asia/Anadyr|
|timezone|Asia/Aqtau|
|timezone|Asia/Aqtobe|
|timezone|Asia/Ashgabat|
|timezone|Asia/Atyrau|
|timezone|Asia/Baghdad|
|timezone|Asia/Bahrain|
|timezone|Asia/Baku|
|timezone|Asia/Bangkok|
|timezone|Asia/Barnaul|
|timezone|Asia/Beirut|
|timezone|Asia/Bishkek|
|timezone|Asia/Brunei|
|timezone|Asia/Chita|
|timezone|Asia/Choibalsan|
|timezone|Asia/Colombo|
|timezone|Asia/Damascus|
|timezone|Asia/Dhaka|
|timezone|Asia/Dili|
|timezone|Asia/Dubai|
|timezone|Asia/Dushanbe|
|timezone|Asia/Famagusta|
|timezone|Asia/Gaza|
|timezone|Asia/Hebron|
|timezone|Asia/Ho_Chi_Minh|
|timezone|Asia/Hong_Kong|
|timezone|Asia/Hovd|
|timezone|Asia/Irkutsk|
|timezone|Asia/Jakarta|
|timezone|Asia/Jayapura|
|timezone|Asia/Jerusalem|
|timezone|Asia/Kabul|
|timezone|Asia/Kamchatka|
|timezone|Asia/Karachi|
|timezone|Asia/Kathmandu|
|timezone|Asia/Khandyga|
|timezone|Asia/Kolkata|
|timezone|Asia/Krasnoyarsk|
|timezone|Asia/Kuala_Lumpur|
|timezone|Asia/Kuching|
|timezone|Asia/Kuwait|
|timezone|Asia/Macau|
|timezone|Asia/Magadan|
|timezone|Asia/Makassar|
|timezone|Asia/Manila|
|timezone|Asia/Muscat|
|timezone|Asia/Nicosia|
|timezone|Asia/Novokuznetsk|
|timezone|Asia/Novosibirsk|
|timezone|Asia/Omsk|
|timezone|Asia/Oral|
|timezone|Asia/Phnom_Penh|
|timezone|Asia/Pontianak|
|timezone|Asia/Pyongyang|
|timezone|Asia/Qatar|
|timezone|Asia/Qostanay|
|timezone|Asia/Qyzylorda|
|timezone|Asia/Riyadh|
|timezone|Asia/Sakhalin|
|timezone|Asia/Samarkand|
|timezone|Asia/Seoul|
|timezone|Asia/Shanghai|
|timezone|Asia/Singapore|
|timezone|Asia/Srednekolymsk|
|timezone|Asia/Taipei|
|timezone|Asia/Tashkent|
|timezone|Asia/Tbilisi|
|timezone|Asia/Tehran|
|timezone|Asia/Thimphu|
|timezone|Asia/Tokyo|
|timezone|Asia/Tomsk|
|timezone|Asia/Ulaanbaatar|
|timezone|Asia/Urumqi|
|timezone|Asia/Ust-Nera|
|timezone|Asia/Vientiane|
|timezone|Asia/Vladivostok|
|timezone|Asia/Yakutsk|
|timezone|Asia/Yangon|
|timezone|Asia/Yekaterinburg|
|timezone|Asia/Yerevan|
|timezone|Atlantic/Azores|
|timezone|Atlantic/Bermuda|
|timezone|Atlantic/Canary|
|timezone|Atlantic/Cape_Verde|
|timezone|Atlantic/Faroe|
|timezone|Atlantic/Madeira|
|timezone|Atlantic/Reykjavik|
|timezone|Atlantic/South_Georgia|
|timezone|Atlantic/St_Helena|
|timezone|Atlantic/Stanley|
|timezone|Australia/Adelaide|
|timezone|Australia/Brisbane|
|timezone|Australia/Broken_Hill|
|timezone|Australia/Darwin|
|timezone|Australia/Eucla|
|timezone|Australia/Hobart|
|timezone|Australia/Lindeman|
|timezone|Australia/Lord_Howe|
|timezone|Australia/Melbourne|
|timezone|Australia/Perth|
|timezone|Australia/Sydney|
|timezone|Canada/Atlantic|
|timezone|Canada/Central|
|timezone|Canada/Eastern|
|timezone|Canada/Mountain|
|timezone|Canada/Newfoundland|
|timezone|Canada/Pacific|
|timezone|Europe/Amsterdam|
|timezone|Europe/Andorra|
|timezone|Europe/Astrakhan|
|timezone|Europe/Athens|
|timezone|Europe/Belgrade|
|timezone|Europe/Berlin|
|timezone|Europe/Bratislava|
|timezone|Europe/Brussels|
|timezone|Europe/Bucharest|
|timezone|Europe/Budapest|
|timezone|Europe/Busingen|
|timezone|Europe/Chisinau|
|timezone|Europe/Copenhagen|
|timezone|Europe/Dublin|
|timezone|Europe/Gibraltar|
|timezone|Europe/Guernsey|
|timezone|Europe/Helsinki|
|timezone|Europe/Isle_of_Man|
|timezone|Europe/Istanbul|
|timezone|Europe/Jersey|
|timezone|Europe/Kaliningrad|
|timezone|Europe/Kiev|
|timezone|Europe/Kirov|
|timezone|Europe/Lisbon|
|timezone|Europe/Ljubljana|
|timezone|Europe/London|
|timezone|Europe/Luxembourg|
|timezone|Europe/Madrid|
|timezone|Europe/Malta|
|timezone|Europe/Mariehamn|
|timezone|Europe/Minsk|
|timezone|Europe/Monaco|
|timezone|Europe/Moscow|
|timezone|Europe/Oslo|
|timezone|Europe/Paris|
|timezone|Europe/Podgorica|
|timezone|Europe/Prague|
|timezone|Europe/Riga|
|timezone|Europe/Rome|
|timezone|Europe/Samara|
|timezone|Europe/San_Marino|
|timezone|Europe/Sarajevo|
|timezone|Europe/Saratov|
|timezone|Europe/Simferopol|
|timezone|Europe/Skopje|
|timezone|Europe/Sofia|
|timezone|Europe/Stockholm|
|timezone|Europe/Tallinn|
|timezone|Europe/Tirane|
|timezone|Europe/Ulyanovsk|
|timezone|Europe/Uzhgorod|
|timezone|Europe/Vaduz|
|timezone|Europe/Vatican|
|timezone|Europe/Vienna|
|timezone|Europe/Vilnius|
|timezone|Europe/Volgograd|
|timezone|Europe/Warsaw|
|timezone|Europe/Zagreb|
|timezone|Europe/Zaporozhye|
|timezone|Europe/Zurich|
|timezone|GMT|
|timezone|Indian/Antananarivo|
|timezone|Indian/Chagos|
|timezone|Indian/Christmas|
|timezone|Indian/Cocos|
|timezone|Indian/Comoro|
|timezone|Indian/Kerguelen|
|timezone|Indian/Mahe|
|timezone|Indian/Maldives|
|timezone|Indian/Mauritius|
|timezone|Indian/Mayotte|
|timezone|Indian/Reunion|
|timezone|Pacific/Apia|
|timezone|Pacific/Auckland|
|timezone|Pacific/Bougainville|
|timezone|Pacific/Chatham|
|timezone|Pacific/Chuuk|
|timezone|Pacific/Easter|
|timezone|Pacific/Efate|
|timezone|Pacific/Enderbury|
|timezone|Pacific/Fakaofo|
|timezone|Pacific/Fiji|
|timezone|Pacific/Funafuti|
|timezone|Pacific/Galapagos|
|timezone|Pacific/Gambier|
|timezone|Pacific/Guadalcanal|
|timezone|Pacific/Guam|
|timezone|Pacific/Honolulu|
|timezone|Pacific/Kiritimati|
|timezone|Pacific/Kosrae|
|timezone|Pacific/Kwajalein|
|timezone|Pacific/Majuro|
|timezone|Pacific/Marquesas|
|timezone|Pacific/Midway|
|timezone|Pacific/Nauru|
|timezone|Pacific/Niue|
|timezone|Pacific/Norfolk|
|timezone|Pacific/Noumea|
|timezone|Pacific/Pago_Pago|
|timezone|Pacific/Palau|
|timezone|Pacific/Pitcairn|
|timezone|Pacific/Pohnpei|
|timezone|Pacific/Port_Moresby|
|timezone|Pacific/Rarotonga|
|timezone|Pacific/Saipan|
|timezone|Pacific/Tahiti|
|timezone|Pacific/Tarawa|
|timezone|Pacific/Tongatapu|
|timezone|Pacific/Wake|
|timezone|Pacific/Wallis|
|timezone|US/Alaska|
|timezone|US/Arizona|
|timezone|US/Central|
|timezone|US/Eastern|
|timezone|US/Hawaii|
|timezone|US/Mountain|
|timezone|US/Pacific|
|timezone|UTC|
|effective_membership_level|1|
|effective_membership_level|8|
|effective_membership_level|15|

<h2 id="tocS_Trend">Trend</h2>
<!-- backwards compatibility -->
<a id="schematrend"></a>
<a id="schema_Trend"></a>
<a id="tocStrend"></a>
<a id="tocstrend"></a>

```json
{
  "events": [
    {
      "id": "string",
      "properties": [
        {
          "key": "string",
          "value": "string",
          "operator": "exact",
          "type": "event"
        }
      ]
    }
  ],
  "actions": [
    {
      "id": "string",
      "properties": [
        {
          "key": "string",
          "value": "string",
          "operator": "exact",
          "type": "event"
        }
      ]
    }
  ],
  "properties": [
    {
      "key": "string",
      "value": "string",
      "operator": "exact",
      "type": "event"
    }
  ],
  "filter_test_accounts": false,
  "date_from": "-7d",
  "date_to": "-7d",
  "breakdown": "string",
  "breakdown_type": "event",
  "display": "ActionsLineGraphLinear",
  "formula": "string",
  "compare": true
}

```

### Properties

|Name|Type|Required|Restrictions|Description|
|---|---|---|---|---|
|events|[[FilterEvent](#schemafilterevent)]|false|none|Events to filter on. One of `events` or `actions` is required.|
|actions|[[FilterAction](#schemafilteraction)]|false|none|Actions to filter on. One of `events` or `actions` is required.|
|properties|[[Property](#schemaproperty)]|false|none|none|
|filter_test_accounts|boolean|false|none|Whether to filter out internal and test accounts. See "project settings" in your PostHog account for the filters.|
|date_from|string|false|none|What date to filter the results from. Can either be a date `2021-01-01`, or a relative date, like `-7d` for last seven days, `-1m` for last month, `mStart` for start of the month or `yStart` for the start of the year.|
|date_to|string|false|none|What date to filter the results to. Can either be a date `2021-01-01`, or a relative date, like `-7d` for last seven days, `-1m` for last month, `mStart` for start of the month or `yStart` for the start of the year.|
|breakdown|string|false|none|A property to break down on. You can select the type of the property with breakdown_type.|
|breakdown_type|string|false|none|Type of property to break down on.|
|display|string|false|none|How to display the data. Will change how the data is returned.|
|formula|string|false|none|Combine the result of events or actions into a single number. For example `A + B` or `(A-B)/B`. The letters correspond to the order of the `events` or `actions` lists.|
|compare|boolean|false|none|For each returned result show the current period and the previous period. The result will contain `compare:true` and a `compare_label` with either `current` or `previous`.|

#### Enumerated Values

|Property|Value|
|---|---|
|breakdown_type|event|
|breakdown_type|person|
|breakdown_type|cohort|
|breakdown_type|group|
|display|ActionsLineGraphLinear|
|display|ActionsLineGraphCumulative|
|display|ActionsTable|
|display|ActionsPie|
|display|ActionsBar|
|display|ActionsBarValue|
|display|ActionsBarValue|

<h2 id="tocS_TrendResult">TrendResult</h2>
<!-- backwards compatibility -->
<a id="schematrendresult"></a>
<a id="schema_TrendResult"></a>
<a id="tocStrendresult"></a>
<a id="tocstrendresult"></a>

```json
{
  "data": [
    0
  ],
  "days": [
    "2019-08-24"
  ],
  "labels": [
    "string"
  ],
  "filter": {
    "events": [
      {
        "id": "string",
        "properties": [
          {
            "key": "string",
            "value": "string",
            "operator": "exact",
            "type": "event"
          }
        ]
      }
    ],
    "actions": [
      {
        "id": "string",
        "properties": [
          {
            "key": "string",
            "value": "string",
            "operator": "exact",
            "type": "event"
          }
        ]
      }
    ],
    "properties": [
      {
        "key": "string",
        "value": "string",
        "operator": "exact",
        "type": "event"
      }
    ],
    "filter_test_accounts": false,
    "date_from": "-7d",
    "date_to": "-7d"
  },
  "label": "string"
}

```

### Properties

|Name|Type|Required|Restrictions|Description|
|---|---|---|---|---|
|data|[integer]|true|none|The requested counts.|
|days|[string]|true|none|The dates corresponding to the data field above.|
|labels|[string]|true|none|The dates corresponding to the data field above.|
|filter|[GenericInsights](#schemagenericinsights)|true|none|The insight that's being returned.|
|label|string|true|none|A label describing this result. Will include<br>- The event or action<br>- Breakdown value<br>- If `compare:true`, whether it's `current` or `previous`|

<h2 id="tocS_TrendResults">TrendResults</h2>
<!-- backwards compatibility -->
<a id="schematrendresults"></a>
<a id="schema_TrendResults"></a>
<a id="tocStrendresults"></a>
<a id="tocstrendresults"></a>

```json
{
  "is_cached": true,
  "last_refresh": "2019-08-24T14:15:22Z",
  "result": [
    {
      "data": [
        0
      ],
      "days": [
        "2019-08-24"
      ],
      "labels": [
        "string"
      ],
      "filter": {
        "events": [
          {
            "id": "string",
            "properties": [
              {
                "key": "string",
                "value": "string",
                "operator": "exact",
                "type": "event"
              }
            ]
          }
        ],
        "actions": [
          {
            "id": "string",
            "properties": [
              {
                "key": "string",
                "value": "string",
                "operator": "exact",
                "type": "event"
              }
            ]
          }
        ],
        "properties": [
          {
            "key": "string",
            "value": "string",
            "operator": "exact",
            "type": "event"
          }
        ],
        "filter_test_accounts": false,
        "date_from": "-7d",
        "date_to": "-7d"
      },
      "label": "string"
    }
  ]
}

```

### Properties

|Name|Type|Required|Restrictions|Description|
|---|---|---|---|---|
|is_cached|boolean|true|none|Whether the result is cached. To force a refresh, pass ?refresh=true|
|last_refresh|string(date-time)|true|none|If the result is cached, when it was last refreshed.|
|result|[[TrendResult](#schematrendresult)]|true|none|none|

<h2 id="tocS_UserBasic">UserBasic</h2>
<!-- backwards compatibility -->
<a id="schemauserbasic"></a>
<a id="schema_UserBasic"></a>
<a id="tocSuserbasic"></a>
<a id="tocsuserbasic"></a>

```json
{
  "id": 0,
  "uuid": "095be615-a8ad-4c33-8e9c-c7612fbf6c9f",
  "distinct_id": "string",
  "first_name": "string",
  "email": "user@example.com"
}

```

### Properties

|Name|Type|Required|Restrictions|Description|
|---|---|---|---|---|
|id|integer|true|read-only|none|
|uuid|string(uuid)|true|read-only|none|
|distinct_id|string¦null|false|none|none|
|first_name|string|false|none|none|
|email|string(email)|true|none|none|

