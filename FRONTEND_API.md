# FamilyOS Frontend API Guide

How the client connects to the Family API (v0.1).

Interactive OpenAPI UI: [http://localhost:8001/docs](http://localhost:8001/docs)

---

## Base URL

| Environment | Base URL |
|-------------|----------|
| Local Docker / default | `http://localhost:8001` |
| Local uvicorn (same port) | `http://localhost:8001` |

All REST paths below are relative to the base URL (e.g. `POST http://localhost:8001/api/auth/login`).

CORS allows `http://localhost:3000` and `http://127.0.0.1:3000` by default (`CORS_ORIGINS` in backend `.env`).

Suggested Vite env:

```env
VITE_API_BASE_URL=http://localhost:8001
```

```ts
const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8001";
```

---

## Conventions

### Headers

| Header | When |
|--------|------|
| `Content-Type: application/json` | All JSON request bodies |
| `Authorization: Bearer <access_token>` | All authenticated routes (everything except register, login, refresh, health) |

### IDs and times

- IDs are UUIDs (strings in JSON).
- Datetimes are ISO-8601 with timezone, e.g. `"2026-08-15T14:30:00Z"`.
- Roles: `"Owner"` \| `"Parent"` \| `"Child"`.

### Error shape

Non-2xx responses typically look like:

```json
{
  "detail": "Human-readable message",
  "code": "error_code"
}
```

Validation errors (`422`):

```json
{
  "detail": [ { "loc": ["body", "email"], "msg": "...", "type": "..." } ],
  "code": "validation_error"
}
```

Common status codes: `400`, `401`, `403`, `404`, `409`, `422`.

### Auth tokens

Register/login/refresh return:

```json
{
  "access_token": "<jwt>",
  "refresh_token": "<jwt>",
  "token_type": "bearer"
}
```

Store both. Send `access_token` on API calls. When you get `401`, call refresh and retry.

### Demo accounts (after seed)

| Email | Password |
|-------|----------|
| `kayode@familyos.app` | `password123` |
| `ade@familyos.app` | `password123` |

---

## Health

### `GET /health`

No auth.

**Response `200`**

```json
{ "status": "ok" }
```

---

## Auth

### `POST /api/auth/register`

No auth.

**Request**

```json
{
  "email": "parent@example.com",
  "password": "password123",
  "name": "Kayode"
}
```

| Field | Rules |
|-------|--------|
| `email` | Valid email |
| `password` | 8–128 chars |
| `name` | 1–120 chars |

**Response `200`** — token pair (see above).

**Errors:** `409` `{ "detail": "Email already registered", "code": "email_taken" }`

---

### `POST /api/auth/login`

No auth.

**Request**

```json
{
  "email": "kayode@familyos.app",
  "password": "password123"
}
```

**Response `200`** — token pair.

**Errors:** `401` invalid credentials.

---

### `POST /api/auth/refresh`

No auth (uses refresh token in body).

**Request**

```json
{
  "refresh_token": "<jwt>"
}
```

**Response `200`** — new token pair.

---

### `GET /api/auth/me`

Auth required.

**Response `200`**

```json
{
  "id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "email": "kayode@familyos.app",
  "name": "Kayode",
  "avatar_url": null,
  "created_at": "2026-08-15T08:48:38.919908Z",
  "updated_at": "2026-08-15T08:48:38.919908Z"
}
```

---

## Families

### `POST /api/families`

Auth required. Creates family, adds caller as `Owner`, creates default shopping list **Groceries**, and seeds default shopping locations (REWE, LIDL, ALDI, Rossmann, DM, African store).

**Request**

```json
{
  "name": "Ayelegun Family",
  "timezone": "Europe/Berlin"
}
```

| Field | Default | Notes |
|-------|---------|--------|
| `name` | — | Required |
| `timezone` | `"UTC"` | IANA timezone string |

**Response `200`**

```json
{
  "id": "ad7fe72f-7fb0-4ea1-95fc-e0bdd1bdd585",
  "name": "Ayelegun Family",
  "timezone": "Europe/Berlin",
  "created_at": "2026-08-15T08:48:38.919908Z",
  "updated_at": "2026-08-15T08:48:38.919911Z"
}
```

---

### `GET /api/me/families`

Auth required.

**Response `200`** — `FamilyOut[]` (same shape as create).

---

### `GET /api/families/{family_id}`

Auth + family membership required.

**Response `200`** — `FamilyOut`.

**Errors:** `404` if not a member (no cross-family leak).

---

### `PATCH /api/families/{family_id}`

Auth + membership. Owner/Parent only for updates.

**Request** (all fields optional)

```json
{
  "name": "Ayelegun Household",
  "timezone": "UTC"
}
```

**Response `200`** — `FamilyOut`.

---

### `GET /api/families/{family_id}/members`

Auth + membership.

**Response `200`**

```json
[
  {
    "id": "11111111-1111-1111-1111-111111111111",
    "family_id": "ad7fe72f-7fb0-4ea1-95fc-e0bdd1bdd585",
    "user_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
    "name": "Kayode",
    "role": "Owner",
    "avatar_url": null,
    "created_at": "2026-08-15T08:48:38.919908Z",
    "updated_at": "2026-08-15T08:48:38.919908Z"
  },
  {
    "id": "22222222-2222-2222-2222-222222222222",
    "family_id": "ad7fe72f-7fb0-4ea1-95fc-e0bdd1bdd585",
    "user_id": null,
    "name": "Kita",
    "role": "Child",
    "avatar_url": null,
    "created_at": "2026-08-15T08:48:38.919908Z",
    "updated_at": "2026-08-15T08:48:38.919908Z"
  }
]
```

`user_id` is `null` for members without an account (e.g. children).

---

### `POST /api/families/{family_id}/members`

Auth + membership. Owner/Parent only. Adds a member **without** a user account.

**Request**

```json
{
  "name": "Kita",
  "role": "Child",
  "avatar_url": null
}
```

| Field | Default |
|-------|---------|
| `role` | `"Child"` |
| `avatar_url` | `null` |

**Response `200`** — `MemberOut`.

---

### `DELETE /api/families/{family_id}/members/{member_id}`

Auth + membership. **Owner only.** Removes another member from the family.

Cannot remove yourself (use leave) or the Owner.

**Response `204`** — empty body.

If the removed member had a linked account, their WebSocket for this family is closed (`4403`).

---

### `DELETE /api/families/{family_id}`

Auth + membership. **Owner only.** Permanently deletes the family and all associated data (members, invitations, events, tasks, shopping, notifications).

**Response `204`** — empty body.

All WebSocket clients for the family are disconnected (`4403`).

---

### `POST /api/families/{family_id}/invitations`

Auth + membership. Owner/Parent only.

**Request**

```json
{
  "email": "ade@example.com"
}
```

`email` is optional. Accepted members always join as **Parent** (partner invites). Add children via `POST /api/families/{family_id}/members` instead.

**Response `200`**

```json
{
  "id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
  "family_id": "ad7fe72f-7fb0-4ea1-95fc-e0bdd1bdd585",
  "email": "ade@example.com",
  "expires_at": "2026-08-22T08:48:38.919908Z",
  "invite_token": "<raw-token-show-once>",
  "invite_url": "http://localhost:3000/invite/<raw-token-show-once>"
}
```

Show `invite_token` / `invite_url` to the user once. The server stores only a hash.

`invite_url` is built from `PUBLIC_APP_URL` + `/invite/{token}`. If `email` is provided it is stored and a stub mailer may log the message; **email is not delivered** until a real `EMAIL_PROVIDER` is configured. Always share the link.

---

### `POST /api/invitations/{token}/accept`

Auth required. `{token}` is the raw `invite_token` from the invitation response.

**Request body:** none.

**Response `200`**

```json
{
  "family": { "id": "...", "name": "...", "timezone": "...", "created_at": "...", "updated_at": "..." },
  "member": { "id": "...", "family_id": "...", "user_id": "...", "name": "...", "role": "Parent", "avatar_url": null, "created_at": "...", "updated_at": "..." }
}
```

**Errors:** `404` invalid token, `409` already used, `400` expired.

---

### `POST /api/families/{family_id}/leave`

Auth + membership. Removes the current user from the family.

If the leaver is the sole Owner and another linked Parent exists, the earliest-joined linked Parent is promoted to Owner.

If no linked adult (Owner/Parent with an account) would remain after leaving, the **family is deleted** (including children and all family data) instead of blocking the leave.

**Response `204`** — empty body. The family may no longer exist; clients should re-list `/api/me/families` and switch or show onboarding.

---

## Dashboard

### `GET /api/families/{family_id}/dashboard`

Auth + membership. Timezone-aware “today” based on family timezone.

**Response `200`**

```json
{
  "family_id": "ad7fe72f-7fb0-4ea1-95fc-e0bdd1bdd585",
  "family_name": "Ayelegun Family",
  "timezone": "Europe/Berlin",
  "member_name": "Kayode",
  "date": "2026-08-15",
  "today_events": [ /* EventOut[] */ ],
  "open_tasks": [ /* TaskOut[] */ ],
  "shopping_preview": [ /* ShoppingItemOut[] incomplete items */ ],
  "upcoming_events": [ /* EventOut[] after today */ ]
}
```

---

## Calendar (events)

### `GET /api/families/{family_id}/events`

Auth + membership.

**Query**

| Param | Type | Default |
|-------|------|---------|
| `from` | ISO datetime | ~1 day ago |
| `to` | ISO datetime | ~365 days ahead |

`to` must be after `from`. Maximum window span is **366 days** (`400` if exceeded).

Example: `/api/families/{family_id}/events?from=2026-08-15T00:00:00Z&to=2026-08-22T00:00:00Z`

**Response `200`** — `EventOut[]` (recurring events may appear multiple times with `occurrence_starts_at` set).

---

### `POST /api/families/{family_id}/events`

Auth + membership.

**Request**

```json
{
  "title": "School pickup",
  "description": null,
  "location": "Primary School",
  "starts_at": "2026-08-15T15:00:00Z",
  "ends_at": "2026-08-15T16:00:00Z",
  "all_day": false,
  "recurrence_rule": "weekly",
  "member_ids": ["11111111-1111-1111-1111-111111111111"],
  "reminder_minutes": [30, 1440]
}
```

| Field | Notes |
|-------|--------|
| `title` | Required; max **200** characters |
| `description` | Optional; max **5000** characters (`422` if exceeded) |
| `location` | Optional; max **200** characters (`422` if exceeded) |
| `member_ids` | Family member UUIDs; empty = whole family |
| `recurrence_rule` | e.g. `"daily"`, `"weekly"`, `"monthly"`, `"weekdays:mon,wed,fri"`, or iCal-like `FREQ=...` |
| `reminder_minutes` | Minutes before start; each value `0`–`10080` (7 days); max **10** entries; duplicates are dropped. Examples: `5`, `15`, `30`, `60`, `1440` |

**Response `200`** — `EventOut`:

```json
{
  "id": "...",
  "family_id": "...",
  "title": "School pickup",
  "description": null,
  "location": "Primary School",
  "starts_at": "2026-08-15T15:00:00Z",
  "ends_at": "2026-08-15T16:00:00Z",
  "all_day": false,
  "recurrence_rule": "weekly",
  "created_by": "...",
  "member_ids": ["..."],
  "reminder_minutes": [30, 1440],
  "created_at": "...",
  "updated_at": "...",
  "occurrence_starts_at": null
}
```

Also broadcasts WebSocket `event.created` on the family channel.

---

### `PATCH /api/events/{event_id}`

Auth + membership in the event’s family.

**Request** — any subset of create fields (`member_ids`, `reminder_minutes`, etc.). Same length limits as create (`description` max 5000, `location` max 200).

**Response `200`** — `EventOut`. Also broadcasts WebSocket `event.updated`.

---

### `DELETE /api/events/{event_id}`

**Response `204`**. Broadcasts `{ "type": "event.deleted", "event_id": "..." }`.

---

## Tasks

### `GET /api/families/{family_id}/tasks`

Auth + membership.

**Query**

| Param | Values | Default |
|-------|--------|---------|
| `filter` | `all` \| `mine` \| `completed` \| `open` | `all` |

`mine` = incomplete tasks assigned to the current user’s family member.

**Response `200`** — `TaskOut[]`.

---

### `POST /api/families/{family_id}/tasks`

**Request**

```json
{
  "title": "Pack school bags",
  "description": null,
  "due_at": "2026-08-15T14:00:00Z",
  "priority": "high",
  "category": "Child",
  "recurrence_rule": "weekly",
  "assignee_ids": ["11111111-1111-1111-1111-111111111111"]
}
```

| Field | Default / notes |
|-------|-----------------|
| `priority` | `"normal"` (also `"high"`, `"low"`, etc.) |
| `category` | e.g. Household, Child, Shopping, Personal, Admin, Other |
| `assignee_ids` | Family member UUIDs |

**Response `200`** — `TaskOut`:

```json
{
  "id": "...",
  "family_id": "...",
  "title": "Pack school bags",
  "description": null,
  "due_at": "2026-08-15T14:00:00Z",
  "priority": "high",
  "category": "Child",
  "recurrence_rule": "weekly",
  "completed_at": null,
  "created_by": "...",
  "assignee_ids": ["..."],
  "created_at": "...",
  "updated_at": "..."
}
```

Incomplete ⇒ `completed_at: null`. Completed ⇒ ISO timestamp.

Also broadcasts WebSocket `task.created` on the family channel.

---

### `PATCH /api/tasks/{task_id}`

**Request** — optional fields from create, plus `completed_at`.

**Response `200`** — `TaskOut`. Also broadcasts WebSocket `task.updated`.

---

### `POST /api/tasks/{task_id}/complete`

No body. Sets `completed_at`. If `recurrence_rule` is set, creates the **next** occurrence as a new open task.

**Response `200`** — completed `TaskOut`. Broadcasts `task.updated` for the completed row, and `task.created` for the next occurrence when one is created.

---

### `DELETE /api/tasks/{task_id}`

**Response `204`**. Broadcasts `{ "type": "task.deleted", "task_id": "..." }`.

---

## Shopping

### `GET /api/families/{family_id}/shopping-lists`

**Response `200`**

```json
[
  {
    "id": "...",
    "family_id": "...",
    "name": "Groceries",
    "created_at": "...",
    "updated_at": "..."
  }
]
```

---

### `POST /api/families/{family_id}/shopping-lists`

**Request**

```json
{ "name": "Pharmacy" }
```

**Response `200`** — `ShoppingListOut`.

---

### `GET /api/families/{family_id}/shopping-locations`

**Response `200`** — `ShoppingLocationOut[]` ordered by `sort_order`, then name:

```json
[
  {
    "id": "...",
    "family_id": "...",
    "name": "REWE",
    "sort_order": 0,
    "created_at": "...",
    "updated_at": "..."
  }
]
```

---

### `POST /api/families/{family_id}/shopping-locations`

**Request**

```json
{ "name": "JC Penney" }
```

**Response `200`** — `ShoppingLocationOut`. Duplicate names in the same family return `409`.

---

### `PATCH /api/shopping-locations/{location_id}`

**Request** (all optional)

```json
{ "name": "Rossmann Express", "sort_order": 3 }
```

**Response `200`** — `ShoppingLocationOut`.

---

### `DELETE /api/shopping-locations/{location_id}`

**Response `204`**. Items that referenced this location get `location_id` set to `null`.

---

### `GET /api/shopping-lists/{list_id}/items`

**Response `200`** — `ShoppingItemOut[]`:

```json
[
  {
    "id": "...",
    "shopping_list_id": "...",
    "name": "Milk",
    "quantity": "2",
    "unit": "L",
    "category": "Dairy",
    "location_id": "...",
    "completed_at": null,
    "created_by": "...",
    "completed_by": null,
    "created_at": "...",
    "updated_at": "..."
  }
]
```

---

### `POST /api/shopping-lists/{list_id}/items`

**Request**

```json
{
  "name": "Milk",
  "quantity": 2,
  "unit": "L",
  "category": "Dairy",
  "location_id": "..."
}
```

`location_id` is optional. It must belong to the same family as the shopping list.

**Response `200`** — `ShoppingItemOut`. Also broadcasts WebSocket `shopping.item.created`.

---

### `PATCH /api/shopping-items/{item_id}`

**Request** (all optional)

```json
{
  "name": "Oat milk",
  "quantity": 1,
  "unit": "L",
  "category": "Dairy",
  "location_id": null,
  "completed": true
}
```

`completed: true` checks the item off; `completed: false` unchecks it. Set `location_id` to `null` to clear the store.

**Response `200`** — `ShoppingItemOut`. Broadcasts `shopping.item.updated` or `shopping.item.completed`.

---

### `DELETE /api/shopping-items/{item_id}`

**Response `204`**. Broadcasts delete-style update on the family channel.

---

## Shopping sessions (basket)

Family-shared active basket. Marking an item as purchased moves it from the list into the active session. Completing the session archives items and records total cost.

### `GET /api/families/{family_id}/shopping-sessions/active`

**Response `200`** — `ShoppingSessionOut` with nested `items`, or `null` if no active session.

### `POST /api/families/{family_id}/shopping-sessions/active/items`

**Request**

```json
{ "item_id": "..." }
```

Creates the active session if needed, snapshots the list item into the basket, and removes it from the shopping list.

**Response `200`**

```json
{
  "session": { /* ShoppingSessionOut */ },
  "item": { /* ShoppingSessionItemOut */ }
}
```

Broadcasts `shopping.session.started` (first item only), `shopping.session.item.added`, and `shopping.item.updated` with `{ item_id, deleted: true }`.

### `DELETE /api/shopping-session-items/{session_item_id}`

Undo: restores the item to the family groceries list and removes it from the basket. Active session only.

**Response `200`**

```json
{
  "session_id": "...",
  "item_id": "...",
  "restored_item": { /* ShoppingItemOut */ }
}
```

### `POST /api/families/{family_id}/shopping-sessions/active/complete`

**Request**

```json
{ "total_cost": "42.50" }
```

`total_cost` must be greater than zero. Session must contain at least one item.

**Response `200`** — completed `ShoppingSessionOut`. Broadcasts `shopping.session.completed` and `expense.created` (a `Shopping` ledger row for the trip total).

### `GET /api/families/{family_id}/shopping-sessions`

**Query:** `limit` (default 20, max 200), `offset` (default 0), `month` (optional `YYYY-MM`, family timezone)

**Response `200`** — completed `ShoppingSessionOut[]` (newest first, `item_count` only; no nested items). When `month` is set, only trips completed in that calendar month (family timezone) are returned.

**Response `400`** — `month` is not a valid `YYYY-MM`.

### `GET /api/families/{family_id}/shopping-spend`

Monthly **grocery** spend (`category=Shopping` on the household expense ledger). Completing a shopping trip writes that row. Months are bucketed in the family timezone. Zero-spend months are included so the window is contiguous.

Prefer `GET /api/families/{family_id}/spend` for Insights (all categories).

**Query:** `months` (default 12, min 1, max 36) — number of months ending at the current family month.

**Response `200`**

```json
{
  "currency": "EUR",
  "current_month": "2026-08",
  "year_to_date_total": "124.50",
  "months": [
    {
      "month": "2025-09",
      "total": "0.00",
      "trip_count": 0,
      "average": "0.00"
    },
    {
      "month": "2026-08",
      "total": "124.50",
      "trip_count": 3,
      "average": "41.50"
    }
  ]
}
```

`average` is `0.00` when `trip_count` is 0. `year_to_date_total` is the sum of Shopping expenses in the current calendar year (family timezone). `trip_count` is the number of Shopping expenses in that month.

### `GET /api/shopping-sessions/{session_id}`

**Response `200`** — `ShoppingSessionOut` with full `items` array.

---

## Expenses

Household spend ledger. Completing a shopping trip inserts a `Shopping` expense (`source_type: "shopping_session"`). Manual entries use `source_type: "manual"`.

Categories: `Shopping`, `Transportation`, `Housing`, `Utilities`, `Dining`, `Health`, `Childcare`, `Other`.

### `POST /api/families/{family_id}/expenses`

Create a manual expense.

**Request**

```json
{
  "amount": "89.00",
  "category": "Transportation",
  "merchant": "Miles Berlin",
  "note": "Weekend car rental",
  "occurred_at": "2026-08-18T12:00:00Z"
}
```

| Field | Notes |
|-------|--------|
| `amount` | Required, greater than zero |
| `category` | Required, one of the categories above |
| `merchant` | Optional, max 120 |
| `note` | Optional, max 500 |
| `occurred_at` | Optional ISO datetime; defaults to now |
| `currency` | Optional, 3-letter code, default `EUR` |

**Response `200`** — `ExpenseOut`. Broadcasts `expense.created`.

```json
{
  "id": "...",
  "family_id": "...",
  "amount": "89.00",
  "currency": "EUR",
  "category": "Transportation",
  "merchant": "Miles Berlin",
  "note": "Weekend car rental",
  "occurred_at": "2026-08-18T12:00:00Z",
  "created_by": "...",
  "source_type": "manual",
  "source_id": null,
  "source_item_count": null,
  "created_at": "...",
  "updated_at": "..."
}
```

`source_item_count` is the basket item count when `source_type` is `shopping_session`, otherwise `null`.

### `GET /api/families/{family_id}/expenses`

**Query:** `month` (required `YYYY-MM`, family timezone)

**Response `200`** — `ExpenseOut[]` newest `occurred_at` first.

**Response `400`** — `month` is not a valid `YYYY-MM`.

### `GET /api/families/{family_id}/spend`

Monthly household spend for Insights. Totals come from the expense ledger (all categories). Months are bucketed in the family timezone. Zero-spend months are included so the window is contiguous.

**Query:** `months` (default 12, min 1, max 36)

**Response `200`**

```json
{
  "currency": "EUR",
  "current_month": "2026-08",
  "year_to_date_total": "500.00",
  "months": [
    {
      "month": "2026-08",
      "total": "180.00",
      "entry_count": 4,
      "average": "45.00",
      "categories": [
        { "category": "Shopping", "total": "80.00", "count": 2 },
        { "category": "Transportation", "total": "100.00", "count": 2 }
      ]
    }
  ]
}
```

`average` is `0.00` when `entry_count` is 0. `year_to_date_total` is the sum of all expenses in the current calendar year (family timezone). Category rows are omitted when a month has no spend.

### `PATCH /api/expenses/{expense_id}`

Update a **manual** expense. Shopping-sourced rows return `400`.

**Request** — any subset of `amount`, `category`, `merchant`, `note`, `occurred_at`.

**Response `200`** — `ExpenseOut`. Broadcasts `expense.updated`.

**Response `400`** — expense was created from a shopping trip.

### `DELETE /api/expenses/{expense_id}`

**Response `204`**. Broadcasts `{ "type": "expense.deleted", "expense_id": "..." }`. Manual expenses only; shopping-sourced rows return `400`.

---

## Notifications

### `GET /api/notifications`

Auth required (current user’s notifications).

**Response `200`**

```json
[
  {
    "id": "...",
    "family_id": "...",
    "user_id": "...",
    "type": "task",
    "title": "Task assigned",
    "body": "Pack school bags",
    "entity_type": "task",
    "entity_id": "...",
    "read_at": null,
    "created_at": "..."
  }
]
```

`type` examples: `calendar`, `task`, `shopping`, `family`.

---

### `POST /api/notifications/{notification_id}/read`

**Response `200`** — notification with `read_at` set.

---

### `POST /api/notifications/read-all`

**Response `200`**

```json
{ "updated": 3 }
```

---

### `GET /api/notification-preferences`

**Response `200`**

```json
{
  "user_id": "...",
  "calendar_reminders": true,
  "task_assignments": true,
  "task_due_soon": true,
  "shopping_activity": true,
  "family_activity": true,
  "quiet_hours_start": null,
  "quiet_hours_end": null
}
```

---

### `PATCH /api/notification-preferences`

**Request** — any subset of the preference booleans / quiet hours strings.

Quiet hours use `HH:MM` (24h, UTC). When both `quiet_hours_start` and `quiet_hours_end` are set, Web Push is skipped during that window; in-app notifications and WebSocket `notification.created` still fire. Overnight windows (e.g. `22:00`–`07:00`) are supported.

**Response `200`** — full preferences object.

---

### `GET /api/push/vapid-public-key`

Auth required. Public VAPID key for `PushManager.subscribe`.

**Response `200`**

```json
{ "public_key": "<url-safe base64>" }
```

`public_key` is `null` when Web Push is not configured on the server.

---

### `POST /api/push/subscribe`

**Request** (from the browser Push API subscription)

```json
{
  "endpoint": "https://fcm.googleapis.com/fcm/send/...",
  "p256dh": "<key>",
  "auth": "<key>",
  "user_agent": "Mozilla/5.0 ..."
}
```

**Response `200`**

```json
{
  "id": "...",
  "endpoint": "https://fcm.googleapis.com/fcm/send/...",
  "user_agent": "Mozilla/5.0 ...",
  "created_at": "...",
  "last_used_at": "..."
}
```

---

### `DELETE /api/push/subscribe/{subscription_id}`

**Response `204`**.

---

### `POST /api/push/test`

Auth required. Sends a test web push to every stored subscription for the current user.

**Response `200`**

```json
{ "sent": 1, "subscriptions": 1, "error": null }
```

`sent` is the number of subscriptions that accepted the message. When `sent` is `0`, `error` explains why (missing subscription, malformed `VAPID_PRIVATE_KEY`, provider rejection, etc.).

---

## WebSocket (realtime family channel)

### `WS /api/ws/families/{family_id}?token=<access_token>`

Full URL example:

```text
ws://localhost:8001/api/ws/families/{family_id}?token=<access_token>
```

- Auth via query `token` (JWT access token). Invalid → close `4401`. Not a member → close `4403`.
- Clients should refresh the access token before connect (or on handshake failure), the same way REST retries after `401`.
- Server pushes JSON text frames after successful mutations. Client may send any text as keep-alive (ignored).
- Reconnect after a drop and refetch REST lists — frames are not replayed.

**Shopping**

```json
{
  "type": "shopping.item.created",
  "item": { }
}
```

`shopping.item.updated` and `shopping.item.completed` use the same `{ item }` shape.

```json
{
  "type": "shopping.item.updated",
  "item_id": "...",
  "deleted": true
}
```

**Shopping sessions**

```json
{ "type": "shopping.session.started", "session": { } }
```

```json
{
  "type": "shopping.session.item.added",
  "session": { },
  "item": { },
  "removed_item_id": "..."
}
```

```json
{
  "type": "shopping.session.item.removed",
  "session_id": "...",
  "item_id": "...",
  "restored_item": { }
}
```

```json
{ "type": "shopping.session.completed", "session": { } }
```

**Expenses**

```json
{ "type": "expense.created", "expense": { } }
```

`expense.updated` uses the same `{ expense }` shape.

```json
{ "type": "expense.deleted", "expense_id": "..." }
```

**Events**

```json
{
  "type": "event.created",
  "event": { }
}
```

`event.updated` uses the same `{ event }` shape (`occurrence_starts_at` is `null`; expand recurring series via `GET /events`).

```json
{
  "type": "event.deleted",
  "event_id": "..."
}
```

**Tasks**

```json
{
  "type": "task.created",
  "task": { }
}
```

`task.updated` uses the same `{ task }` shape.

```json
{
  "type": "task.deleted",
  "task_id": "..."
}
```

**Notifications**

Delivered only to the recipient’s WebSocket connection(s) for the family (not broadcast to every member).

```json
{
  "type": "notification.created",
  "notification": { }
}
```

`notification` matches `NotificationOut` from `GET /api/notifications`. Use it to update the in-app bell unread count without refetching.

Example client:

```ts
const ws = new WebSocket(
  `${WS_BASE}/api/ws/families/${familyId}?token=${accessToken}`
);
ws.onmessage = (ev) => {
  const msg = JSON.parse(ev.data);
  // upsert/delete local events, tasks, shopping, and notifications from msg.type
};
```

Use `ws://` locally and `wss://` in production.

---

## Suggested client flow

```text
1. POST /api/auth/register or /login  → store tokens
2. GET  /api/me/families
   - empty → POST /api/families (onboarding)
   - or POST /api/invitations/{token}/accept
3. Pick family_id; GET /api/families/{id}/dashboard
4. Wire screens:
   - Calendar → events + family WebSocket
   - Tasks → tasks (+ complete) + family WebSocket
   - Shopping → lists/items + family WebSocket
   - Notifications → notifications + preferences + `notification.created` on family WebSocket
5. On 401 → POST /api/auth/refresh → retry
```

Minimal fetch helper:

```ts
async function api<T>(
  path: string,
  options: RequestInit & { token?: string } = {}
): Promise<T> {
  const headers: HeadersInit = {
    "Content-Type": "application/json",
    ...(options.headers ?? {}),
  };
  if (options.token) {
    (headers as Record<string, string>)["Authorization"] =
      `Bearer ${options.token}`;
  }
  const res = await fetch(`${API_BASE}${path}`, { ...options, headers });
  if (res.status === 204) return undefined as T;
  const data = await res.json();
  if (!res.ok) throw data;
  return data as T;
}
```

---

## Quick reference

| Method | Path | Auth |
|--------|------|------|
| GET | `/health` | No |
| POST | `/api/auth/register` | No |
| POST | `/api/auth/login` | No |
| POST | `/api/auth/refresh` | No |
| GET | `/api/auth/me` | Yes |
| POST | `/api/families` | Yes |
| GET | `/api/me/families` | Yes |
| GET | `/api/families/{family_id}` | Yes |
| PATCH | `/api/families/{family_id}` | Yes |
| GET | `/api/families/{family_id}/members` | Yes |
| POST | `/api/families/{family_id}/members` | Yes |
| DELETE | `/api/families/{family_id}/members/{member_id}` | Yes (Owner) |
| DELETE | `/api/families/{family_id}` | Yes (Owner) |
| POST | `/api/families/{family_id}/invitations` | Yes |
| POST | `/api/invitations/{token}/accept` | Yes |
| POST | `/api/families/{family_id}/leave` | Yes |
| GET | `/api/families/{family_id}/dashboard` | Yes |
| GET | `/api/families/{family_id}/events` | Yes |
| POST | `/api/families/{family_id}/events` | Yes |
| PATCH | `/api/events/{event_id}` | Yes |
| DELETE | `/api/events/{event_id}` | Yes |
| GET | `/api/families/{family_id}/tasks` | Yes |
| POST | `/api/families/{family_id}/tasks` | Yes |
| PATCH | `/api/tasks/{task_id}` | Yes |
| POST | `/api/tasks/{task_id}/complete` | Yes |
| DELETE | `/api/tasks/{task_id}` | Yes |
| GET | `/api/families/{family_id}/shopping-lists` | Yes |
| POST | `/api/families/{family_id}/shopping-lists` | Yes |
| GET | `/api/shopping-lists/{list_id}/items` | Yes |
| POST | `/api/shopping-lists/{list_id}/items` | Yes |
| PATCH | `/api/shopping-items/{item_id}` | Yes |
| DELETE | `/api/shopping-items/{item_id}` | Yes |
| GET | `/api/families/{family_id}/shopping-sessions/active` | Yes |
| POST | `/api/families/{family_id}/shopping-sessions/active/items` | Yes |
| DELETE | `/api/shopping-session-items/{id}` | Yes |
| POST | `/api/families/{family_id}/shopping-sessions/active/complete` | Yes |
| GET | `/api/families/{family_id}/shopping-sessions` | Yes |
| GET | `/api/families/{family_id}/shopping-spend` | Yes |
| GET | `/api/shopping-sessions/{session_id}` | Yes |
| POST | `/api/families/{family_id}/expenses` | Yes |
| GET | `/api/families/{family_id}/expenses` | Yes |
| GET | `/api/families/{family_id}/spend` | Yes |
| PATCH | `/api/expenses/{expense_id}` | Yes |
| DELETE | `/api/expenses/{expense_id}` | Yes |
| GET | `/api/notifications` | Yes |
| POST | `/api/notifications/{id}/read` | Yes |
| POST | `/api/notifications/read-all` | Yes |
| GET | `/api/notification-preferences` | Yes |
| PATCH | `/api/notification-preferences` | Yes |
| GET | `/api/push/vapid-public-key` | Yes |
| POST | `/api/push/subscribe` | Yes |
| DELETE | `/api/push/subscribe/{id}` | Yes |
| POST | `/api/push/test` | Yes |
| WS | `/api/ws/families/{family_id}?token=...` | Token query |
