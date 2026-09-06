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
  "timezone": null,
  "created_at": "2026-08-15T08:48:38.919908Z",
  "updated_at": "2026-08-15T08:48:38.919908Z",
  "assistant_enabled": false
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

### `PATCH /api/shopping-session-items/{session_item_id}`

Edit an item that is already in the basket. Active session only.

**Request** (all optional)

```json
{
  "name": "Oat milk",
  "quantity": 2,
  "unit": "L",
  "category": "Dairy",
  "location_id": null
}
```

`quantity` must be greater than zero. `location_id` must belong to the same family; set it to `null` to clear the store. Basket items carry a denormalized `location_name`, which the API keeps in step with `location_id`.

**Response `200`** — `ShoppingSessionItemOut`. Broadcasts `shopping.session.item.updated`.

**Response `400`** — the session is already completed, or the store belongs to another family.

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

Prefer `GET /api/families/{family_id}/spend` for Expenses (all categories).

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

Household spend ledger. Completing a shopping trip inserts a `Shopping` expense (`source_type: "shopping_session"`). Manual entries use `source_type: "manual"`. Assistant-confirmed entries use `source_type: "assistant"` and stay editable like manual rows. Receipt scans use `source_type: "receipt"` and link to a `Receipt` via `source_id`.

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
| `source_type` | Optional, `manual` (default) or `assistant` |

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

**Query:** exactly one of:

| Param | Notes |
|-------|--------|
| `period_id` | UUID of a budget period for this family. Filters by that cycle’s `start_date`–`end_date` (family timezone, half-open bounds — same window as budget `used`). |
| `month` | `YYYY-MM` in the family timezone (calendar-month list, kept for compatibility). |

**Response `200`** — `ExpenseOut[]` newest `occurred_at` first.

**Response `400`** — neither or both params, or `month` is not a valid `YYYY-MM`.

**Response `404`** — `period_id` does not exist or belongs to another family.

### `GET /api/families/{family_id}/spend`

Monthly household spend for Insights-style charts. Totals come from the expense ledger (outflow groups). Months are bucketed in the family timezone. Zero-spend months are included so the window is contiguous. The Spend screen and Dashboard headline do **not** use these month buckets — they follow the selected/current pay cycle.

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

When a household budget exists for the **current pay cycle**, the response includes:

```json
"budget": {
  "period_id": "...",
  "label_month": "2026-09",
  "start_date": "2026-08-27",
  "end_date": "2026-09-26",
  "amount": "600.00",
  "used": "480.00",
  "remaining": "120.00",
  "percent_used": 80,
  "state": "warning"
}
```

`state` is `ok` below 80% used, `warning` at 80–99%, and `over` at 100% or above. `null` when no period covers today or the current period has no household (overall) limit. Calendar month totals in `months` remain for Insights-style charts — the Spend UI and Dashboard headline use cycle bounds, not these month buckets.

---

## Budgets

Dated **pay-cycle periods** with Expected amounts per family-defined **subcategory** under six fixed groups: Income, Fixed Expense, Variable Expense, Debt, Savings, Investment. Parents and owners write; all members read.

A period has explicit `start_date` / `end_date` (inclusive, family-local dates). `label_month` is the destination month (`YYYY-MM`), defaulting to the month of `end_date`. Periods for a family must not overlap. New cycles default to the calendar month. Ledger Actuals roll up by `subcategory_id`; Income is excluded from `/spend`.

### Subcategories

- `GET /api/families/{family_id}/budget-subcategories` — grouped list (auto-seeds defaults on first read)
- `POST /api/families/{family_id}/budget-subcategories` — `{ group, name }`
- `PATCH /api/budget-subcategories/{id}` — rename / move / reorder
- `DELETE /api/budget-subcategories/{id}` — soft-archive (Groceries/`role=groceries` cannot be archived)

### Periods

### `GET /api/families/{family_id}/budget-periods/current`

Auth + membership. Current cycle covering today in the family timezone.

**Response `200`** — `BudgetPeriodOut` or `null`.

```json
{
  "id": "...",
  "family_id": "...",
  "start_date": "2026-08-27",
  "end_date": "2026-09-26",
  "label_month": "2026-09",
  "currency": "EUR",
  "groups": [
    {
      "group": "Fixed Expense",
      "direction": "outflow",
      "expected": "1370.30",
      "actual": "0.00",
      "lines": [
        {
          "id": "...",
          "subcategory_id": "...",
          "subcategory_name": "Rent",
          "group": "Fixed Expense",
          "amount": "1370.30",
          "used": "0.00",
          "settled": false,
          "percent_used": 0,
          "state": "ok"
        }
      ]
    }
  ],
  "summary": {
    "income_expected": "10910.32",
    "income_actual": "0.00",
    "total_expenses_expected": "8563.79",
    "total_expenses_actual": "0.00",
    "left_over_expected": "2346.53",
    "left_over_actual": "0.00"
  },
  "created_at": "...",
  "updated_at": "..."
}
```

### `POST /api/families/{family_id}/budget-periods`

Body: `{ start_date, end_date, label_month?, currency?, budgets: [{ subcategory_id, amount }] }`

### `POST /api/families/{family_id}/budget-periods/copy`

Clone lines from the previous (or specified) period into a new date range.

### `POST /api/budgets/{budget_id}/settle` / `DELETE .../settle`

Create or remove the settlement ledger entry (`source_type=budget_line`) equal to Expected.

### `GET /api/families/{family_id}/budget-insights?months=12`

Per-month group expected/actual, income, outflow, and net for charts.

### Expenses

Expense create/update take `subcategory_id` instead of `category`. Responses include `subcategory_id`, `subcategory_name`, `group`, and `direction`.

---

### `POST /api/families/{family_id}/budget-periods`

Auth + parent or owner.

**Request**

```json
{
  "start_date": "2026-08-27",
  "end_date": "2026-09-26",
  "label_month": "2026-09",
  "currency": "EUR",
  "budgets": [
    { "category": null, "amount": "1500.00" },
    { "category": "Shopping", "amount": "600.00" }
  ]
}
```

`label_month` optional (defaults from `end_date`). Overlap with an existing period → `400`.

**Response `201`** — `BudgetPeriodOut`. Broadcasts `budget.updated` with `{ period }`.

### `PATCH /api/budget-periods/{period_id}`

Auth + parent or owner. Any of `start_date`, `end_date`, `label_month`, `budgets` (full replace of limit rows when `budgets` is sent).

**Response `200`** — `BudgetPeriodOut`. Broadcasts `budget.updated`.

### `DELETE /api/budget-periods/{period_id}`

**Response `204`**. Broadcasts `{ "type": "budget.deleted", "period_id": "..." }`.

### `PATCH /api/budgets/{budget_id}`

Update a single category/overall row amount.

**Request:** `{ "amount": "150.00" }`

**Response `200`** — `BudgetOut`. Also broadcasts `budget.updated` with the full period.

### `DELETE /api/budgets/{budget_id}`

**Response `204`**. Broadcasts `{ "type": "budget.deleted", "budget_id": "..." }`.

When spend crosses 80% or 100% of a limit in a cycle, members receive notifications if `budget_alerts` is enabled. Alerts fire at most once per threshold per budget row per period.

---

### `PATCH /api/expenses/{expense_id}`

Update a **manual** or **receipt** expense. Shopping-sourced rows return `400`.

**Request** — any subset of `amount`, `category`, `merchant`, `note`, `occurred_at`.

**Response `200`** — `ExpenseOut`. Broadcasts `expense.updated`.

**Response `400`** — expense was created from a shopping trip.

### `DELETE /api/expenses/{expense_id}`

**Response `204`**. Broadcasts `{ "type": "expense.deleted", "expense_id": "..." }`. Manual and receipt expenses only; shopping-sourced rows return `400`. Deleting a receipt expense also removes the linked receipt image.

---

## Personal expenses

Private, user-owned ledger. Not family-scoped. Other members — including the family Owner — cannot see these accounts. Leaving or deleting a family does not delete them.

Categories: `Dining`, `Transport`, `Shopping`, `Health`, `Entertainment`, `Travel`, `Subscriptions`, `Other`.

Month bounds use `users.timezone` (IANA), falling back to `UTC`. Creating a family or accepting an invite sets `users.timezone` from the family timezone when it is still null. Creating an account may pass `timezone` to fill a still-null user timezone.

`GET` does not auto-create an account.

Unknown ids return `404` (not `403`) so existence is not leaked.

### `GET /api/me/expense-accounts`

Auth required. Empty `accounts` is valid.

**Response `200`**

```json
{
  "timezone": "Europe/Berlin",
  "current_month": "2026-08",
  "current_month_total": "86.00",
  "current_month_count": 4,
  "currency": "EUR",
  "accounts": [
    {
      "id": "...",
      "name": "Coffee money",
      "currency": "EUR",
      "sort_order": 0,
      "current_month_total": "42.00",
      "current_month_count": 3,
      "created_at": "...",
      "updated_at": "..."
    }
  ]
}
```

`current_month_*` on the envelope is the sum across all accounts for the current calendar month in the user's timezone.

### `POST /api/me/expense-accounts`

**Request**

```json
{
  "name": "Coffee money",
  "currency": "EUR",
  "timezone": "Europe/Berlin"
}
```

| Field | Notes |
|-------|--------|
| `name` | Required, 1–40 chars after trim |
| `currency` | Optional, 3-letter code, default `EUR` |
| `timezone` | Optional IANA string; stored on the user when `users.timezone` is still null |

**Response `200`** — `PersonalAccountOut` (`current_month_total` is `0.00`).

**Response `409`** — same user already has an account with that name.

### `PATCH /api/me/expense-accounts/{account_id}`

**Request** — any subset of `name`, `currency`.

**Response `200`** — `PersonalAccountOut`.

**Response `404`** — not found or not owned by the caller.

**Response `409`** — rename collides with another of the caller's accounts.

### `DELETE /api/me/expense-accounts/{account_id}`

Deletes the account and all of its expenses.

**Response `204`**.

**Response `404`** — not found or not owned by the caller.

### `GET /api/me/expense-accounts/{account_id}/expenses`

**Query:** `month` (required `YYYY-MM` in the user's timezone).

**Response `200`** — `PersonalExpenseOut[]` newest `occurred_at` first.

**Response `400`** — `month` is not a valid `YYYY-MM`.

**Response `404`** — account not found or not owned by the caller.

### `POST /api/me/expense-accounts/{account_id}/expenses`

Create a personal expense. Rows default to `source_type: "manual"`. Assistant-confirmed entries use `source_type: "assistant"` and stay editable like manual rows. Other members cannot read these rows.

**Request**

```json
{
  "amount": "12.50",
  "category": "Dining",
  "merchant": "Café",
  "note": "Lunch",
  "occurred_at": "2026-08-29T12:00:00Z",
  "source_type": "manual"
}
```

| Field | Notes |
|-------|--------|
| `amount` | Required, greater than zero |
| `category` | One of the categories above; default `Other` |
| `merchant` | Optional, max 120 |
| `note` | Optional, max 500 |
| `occurred_at` | Optional ISO datetime; defaults to now |
| `currency` | Optional, 3-letter code; defaults to the account currency |
| `source_type` | Optional, `manual` (default) or `assistant` |

**Response `200`** — `PersonalExpenseOut`.

**Response `422`** — unknown category.

### `PATCH /api/personal-expenses/{expense_id}`

**Request** — any subset of `amount`, `category`, `merchant`, `note`, `occurred_at`.

**Response `200`** — `PersonalExpenseOut`.

**Response `404`** — not found or not owned by the caller.

### `DELETE /api/personal-expenses/{expense_id}`

**Response `204`**.

**Response `404`** — not found or not owned by the caller.

---

## Assistant

A private, ephemeral turn. The client holds the thread and resends it each time. The Assistant proposes only; it never writes a spend row, Task, or expense change. Closing the panel discards the thread — nothing is stored as a server conversation.

Requires `OPENAI_API_KEY`. When missing or `ASSISTANT_ENABLED=false`, the turn route returns `503` with `code: assistant_unavailable`, and `GET /api/auth/me` has `assistant_enabled: false`.

Accepts only `user` and `assistant` roles (`system` and other roles are dropped). Each message is capped at 500 characters; the thread is capped at 20 messages. Oversize is `422`. Rate limit: 30 turns per user per hour (`429`, `code: assistant_rate_limited`). Child members can call this route.

### `POST /api/families/{family_id}/assistant/turns`

Auth + family membership.

**Request**

```json
{
  "messages": [
    { "role": "user", "content": "I spent €12 at Tesco" }
  ],
  "destination_hint": "household"
}
```

`destination_hint` is optional (`"household"` | `"personal"`). It does not change add-expense Destination or `destination_explicit`. Omit it when the open screen has no spend context.

**Response `200`**

```json
{
  "assistant_text": "I drafted a Family expense.",
  "proposal": {
    "destination": "household",
    "account_id": null,
    "amount": "12.00",
    "subcategory_id": "...",
    "category": null,
    "merchant": "Tesco",
    "note": null,
    "occurred_on": null,
    "destination_explicit": false,
    "account_id_explicit": false,
    "amount_explicit": true,
    "subcategory_id_explicit": false,
    "category_explicit": false,
    "merchant_explicit": true,
    "note_explicit": false,
    "occurred_on_explicit": false
  },
  "task_proposal": null,
  "expense_list": null,
  "change_proposal": null
}
```

`proposal` is an Expense proposal or `null`. `task_proposal`, `expense_list`, and `change_proposal` are structured siblings; at most one of the four is non-null. A completed turn never creates, patches, or deletes a Family expense, Personal expense, or Task. Proposed ids that are not in this Family’s catalog (Subcategories, the caller’s Personal accounts, this Family’s members, this Family’s budget periods) are stripped. Other-family member and period ids are not included in the catalog. `*_explicit` is decided by a phrase check on the latest user message, not by the model. Confirming a Family proposal uses `POST /api/families/{family_id}/expenses` with `source_type=assistant`. Confirming a Personal proposal uses `POST /api/me/expense-accounts/{account_id}/expenses` with `source_type=assistant`. Confirming a Task proposal uses `POST /api/families/{family_id}/tasks` as the signed-in member (due 17:00 Family timezone; `medium` → `normal`; weekly recurrence or none). No Task provenance field.

When the member described a Task, `task_proposal` is a draft. Title must be non-empty after strip or there is no card. Unknown assignee names ask who; unknown assignee ids are stripped. Defaults when not named: assignee is the caller, due today, priority medium, category Household, recurrence off. Due on the card is only `today` or `tomorrow`. Empty model text with a Task proposal uses `I’ve drafted a task below. Check it and tap Add task.` and is never the refuse fallback.

```json
{
  "assistant_text": "I’ve drafted a task below. Check it and tap Add task.",
  "proposal": null,
  "task_proposal": {
    "title": "Take bins out",
    "assignee_id": "...",
    "due": "tomorrow",
    "priority": "high",
    "category": "Household",
    "recurring": true,
    "title_explicit": true,
    "assignee_id_explicit": true,
    "due_explicit": true,
    "priority_explicit": true,
    "category_explicit": true,
    "recurring_explicit": true
  },
  "expense_list": null,
  "change_proposal": null
}
```

When the member asked for a Household Expense list, `expense_list` is the Family outflows for one budget period (current when unnamed). The server loads the rows; `rows` in tool args are ignored. `count` and `total` match those outflow rows. Empty windows still return the card (`count` 0, `total` `"0.00"`). Assistant text names Household and the period and never includes amounts or totals.

When the member asked for a Personal Expense list, `expense_list` is every row on one of the caller’s Personal accounts for one calendar month (current month in the Family timezone when unnamed). A named month (`YYYY-MM` or an English month name) selects that month. Destination follows the same rules as add-expense, including `destination_hint` from the open screen (never `destination_explicit`). Unspecified Destination with Personal accounts and no hint asks Household or Personal and returns no list. One Personal account is used without asking; several without a named account asks which. A partner cannot attach another member’s Personal rows. Assistant text names the Personal account and month and never includes amounts or totals. Empty windows still return the card. Each row includes `subcategory_id` (Family) and `note` so a writable row can open an Expense change proposal without a new turn. `writable` is true only for `manual` and `assistant`.

```json
{
  "assistant_text": "Here are the household expenses for 2026-09.",
  "proposal": null,
  "task_proposal": null,
  "expense_list": {
    "destination": "household",
    "account_id": null,
    "account_name": null,
    "month": null,
    "period_id": "...",
    "period_label": "2026-09",
    "count": 2,
    "total": "20.00",
    "currency": "EUR",
    "rows": [
      {
        "id": "...",
        "occurred_on": "2026-09-06",
        "merchant": "Tesco",
        "amount": "12.00",
        "category_or_subcategory_label": "Transport",
        "source_type": "assistant",
        "writable": true,
        "subcategory_id": "...",
        "note": "Weekly shop"
      }
    ]
  },
  "change_proposal": null
}
```

No current budget period returns text that Budget is not set up, `expense_list` null, and does not create a period. Named Personal with zero accounts uses the existing Personal-unavailable copy. “Last week” or a date range asks for one month or one period and returns no list.

When the member asked to change or delete an existing expense, `change_proposal` is the current writable row plus any named patch fields. Identity is merchant (case-insensitive substring), amount, and/or date in one window — never a model-supplied expense id. A unique writable match returns `change_proposal` and writes nothing. Several matches return `expense_list` of those rows (`change_proposal` null). Zero matches or a unique shopping-trip, budget-line, or receipt row return no card. Empty model text with a change proposal uses `I found this expense. Check the card to save or delete.` and is never the refuse fallback. Empty model text with no result uses `I can only help you add an expense, show expenses, add a task, or change an expense.`

```json
{
  "assistant_text": "I found this expense. Check the card to save or delete.",
  "proposal": null,
  "task_proposal": null,
  "expense_list": null,
  "change_proposal": {
    "expense_id": "...",
    "destination": "household",
    "account_id": null,
    "amount": "15.00",
    "subcategory_id": "...",
    "category": null,
    "merchant": "Tesco",
    "note": "Weekly shop",
    "occurred_on": "2026-09-06",
    "amount_explicit": true,
    "subcategory_id_explicit": false,
    "category_explicit": false,
    "merchant_explicit": false,
    "note_explicit": false,
    "occurred_on_explicit": false,
    "destination_explicit": false,
    "account_id_explicit": false,
    "writable": true
  }
}
```

Confirming Save uses the existing Family or Personal PATCH. Delete uses the existing DELETE. The turn itself never patches or deletes.

**Errors:** `401` unauthenticated, `404` not a member, `422` validation, `429` rate limited, `503` unavailable.

---

## Receipts

Upload a receipt photo, extract merchant / line items / total with OpenAI vision, then confirm to create an itemized expense (`source_type: "receipt"`).

Requires `OPENAI_API_KEY`. When missing or `RECEIPT_SCANNING_ENABLED=false`, upload returns `503` with `code: receipt_scanning_unavailable`.

Accepted images: JPEG, PNG, WebP (validated by magic bytes). Max size: `RECEIPT_MAX_BYTES` (default 10 MB).

### `POST /api/families/{family_id}/receipts`

Multipart form: `file` (required), `category_hint` (optional string).

**Response `202`** — `ReceiptOut` with `status: "processing"`. Extraction runs in a background task. Broadcasts `receipt.ready` or `receipt.failed` when finished.

### `GET /api/families/{family_id}/receipts`

Optional query: `status` (`processing` | `ready` | `failed` | `confirmed`).

**Response `200`** — `ReceiptOut[]` (newest first), including `items` when ready.

### `GET /api/receipts/{receipt_id}`

Poll target while status is `processing`.

**Response `200`** — `ReceiptOut`.

### `GET /api/receipts/{receipt_id}/image`

Auth-checked binary image (`FileResponse`). Use an authenticated fetch; do not put the JWT in an `<img src>`.

### `POST /api/receipts/{receipt_id}/confirm`

Create (or return existing) expense from a ready/failed receipt. Edits are submitted once here — there is no `PATCH /receipts/{id}`.

**Request**

```json
{
  "category": "Shopping",
  "merchant": "REWE",
  "note": "Weekly shop",
  "occurred_at": "2026-08-22T14:36:56Z",
  "currency": "EUR",
  "total": "52.10",
  "items": [
    {
      "name": "OLIVENOEL",
      "quantity": "2",
      "unit": "Stk",
      "unit_price": "5.99",
      "total_price": "11.98",
      "tax_code": "B",
      "is_included": true
    }
  ]
}
```

**Response `200`** — `ExpenseOut`. Idempotent if already confirmed. Broadcasts `expense.created`.

When **`category` is `Shopping`**: also creates a completed **shopping session** from included line items. The expense uses `source_type: "shopping_session"` and `source_id` = session id (same as completing a basket trip). The receipt row is linked via `expense_id` and `shopping_session_id`. Broadcasts `shopping.session.completed` and `expense.created`. Requires at least one included item. Merchant and note from the confirm payload are stored on the expense.

When **category is anything else**: expense uses `source_type: "receipt"` and `source_id` = receipt id (unchanged).

**Response `400`** — still processing (`code: receipt_not_ready`), invalid state, or Shopping confirm with no included items.

### `DELETE /api/receipts/{receipt_id}`

Discard a draft (not yet confirmed). Deletes the stored image.

**Response `204`**. Broadcasts `{ "type": "receipt.deleted", "receipt_id": "..." }`.

### `GET /api/expenses/{expense_id}/receipt`

**Response `200`** — `ReceiptOut` linked via `receipt.expense_id` (works for both `receipt`- and `shopping_session`-sourced expenses created from a receipt).

### `ReceiptOut` shape

```json
{
  "id": "...",
  "family_id": "...",
  "uploaded_by": "...",
  "status": "ready",
  "mime_type": "image/jpeg",
  "byte_size": 184320,
  "original_filename": "receipt.jpg",
  "category_hint": null,
  "suggested_category": "Shopping",
  "merchant": "REWE",
  "purchased_at": "2026-08-22T14:36:56Z",
  "currency": "EUR",
  "subtotal": "47.33",
  "tax_total": "4.77",
  "total": "52.10",
  "totals_mismatch": false,
  "model_name": "gpt-5.6-luna",
  "error_message": null,
  "expense_id": null,
  "shopping_session_id": null,
  "items": [
    {
      "id": "...",
      "receipt_id": "...",
      "position": 0,
      "name": "PILZ CHAMP.BRAUN",
      "quantity": "0.142",
      "unit": "kg",
      "unit_price": "6.90",
      "total_price": "0.98",
      "tax_code": "B",
      "is_included": true,
      "created_at": "...",
      "updated_at": "..."
    }
  ],
  "created_at": "...",
  "updated_at": "..."
}
```

`totals_mismatch` is `true` when the sum of line totals differs from the printed total by more than €0.02. The printed total is never overwritten.

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
  "budget_alerts": true,
  "quiet_hours_start": null,
  "quiet_hours_end": null
}
```

---

### `PATCH /api/notification-preferences`

**Request** — any subset of the preference booleans / quiet hours strings.

Quiet hours use `HH:MM` (24h) in the **family timezone**. When both `quiet_hours_start` and `quiet_hours_end` are set, Web Push is skipped during that window; in-app notifications and WebSocket `notification.created` still fire. Overnight windows (e.g. `22:00`–`07:00`) are supported.

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

**Budgets**

```json
{ "type": "budget.updated", "period": { } }
```

`period` matches `BudgetPeriodOut` from `GET /api/families/{family_id}/budget-periods/current`.

```json
{ "type": "budget.deleted", "period_id": "..." }
```

or `{ "type": "budget.deleted", "budget_id": "..." }` when a single limit row is removed.

**Receipts**

```json
{ "type": "receipt.ready", "receipt": { } }
```

```json
{ "type": "receipt.failed", "receipt": { } }
```

```json
{ "type": "receipt.deleted", "receipt_id": "..." }
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
| PATCH | `/api/shopping-session-items/{id}` | Yes |
| DELETE | `/api/shopping-session-items/{id}` | Yes |
| POST | `/api/families/{family_id}/shopping-sessions/active/complete` | Yes |
| GET | `/api/families/{family_id}/shopping-sessions` | Yes |
| GET | `/api/families/{family_id}/shopping-spend` | Yes |
| GET | `/api/shopping-sessions/{session_id}` | Yes |
| POST | `/api/families/{family_id}/expenses` | Yes |
| GET | `/api/families/{family_id}/expenses` | Yes |
| GET | `/api/families/{family_id}/spend` | Yes |
| GET | `/api/me/expense-accounts` | Yes |
| POST | `/api/me/expense-accounts` | Yes |
| PATCH | `/api/me/expense-accounts/{id}` | Yes |
| DELETE | `/api/me/expense-accounts/{id}` | Yes |
| GET | `/api/me/expense-accounts/{id}/expenses` | Yes |
| POST | `/api/me/expense-accounts/{id}/expenses` | Yes |
| PATCH | `/api/personal-expenses/{expense_id}` | Yes |
| DELETE | `/api/personal-expenses/{expense_id}` | Yes |
| GET | `/api/families/{family_id}/budget-periods/current` | Yes |
| GET | `/api/families/{family_id}/budget-periods` | Yes |
| POST | `/api/families/{family_id}/budget-periods` | Yes (Parent/Owner) |
| PATCH | `/api/budget-periods/{period_id}` | Yes (Parent/Owner) |
| DELETE | `/api/budget-periods/{period_id}` | Yes (Parent/Owner) |
| PATCH | `/api/budgets/{budget_id}` | Yes (Parent/Owner) |
| DELETE | `/api/budgets/{budget_id}` | Yes (Parent/Owner) |
| PATCH | `/api/expenses/{expense_id}` | Yes |
| DELETE | `/api/expenses/{expense_id}` | Yes |
| POST | `/api/families/{family_id}/assistant/turns` | Yes |
| POST | `/api/families/{family_id}/receipts` | Yes |
| GET | `/api/families/{family_id}/receipts` | Yes |
| GET | `/api/receipts/{receipt_id}` | Yes |
| GET | `/api/receipts/{receipt_id}/image` | Yes |
| POST | `/api/receipts/{receipt_id}/confirm` | Yes |
| DELETE | `/api/receipts/{receipt_id}` | Yes |
| GET | `/api/expenses/{expense_id}/receipt` | Yes |
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
