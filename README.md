# Instagram Private Replies

Keyword-triggered Instagram private replies. When someone comments a keyword on one of your reels, they automatically receive a private reply through the official Instagram Messaging API.

## Quick start

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure the Instagram API

```bash
cp .env.example .env
```

Edit `.env`:

```
INTEGRATION_MODE=official
INSTAGRAM_PAGE_ID=your_page_id
INSTAGRAM_PAGE_ACCESS_TOKEN=your_page_access_token
INSTAGRAM_IG_USER_ID=your_instagram_business_account_id
INSTAGRAM_WEBHOOK_VERIFY_TOKEN=your_webhook_verify_token
```

Set `INTEGRATION_MODE=legacy` only if you want to keep the old browser automation path.

### 3. Get the required credentials

You need an Instagram Professional account connected to a Facebook Page. The official private-reply flow requires Meta app credentials, not your Instagram password.

1. Create a Meta developer app at [developers.facebook.com](https://developers.facebook.com/).
2. Add the Instagram product and the Webhooks product to the app.
3. Convert your Instagram account to a Professional account if it is still personal.
4. Link that Instagram Professional account to a Facebook Page.
5. In your app, generate a Page access token with the permissions required for Instagram messaging and comment handling, including `instagram_manage_comments` and `pages_messaging` where available.
6. Find the Instagram Professional account ID and put it in `INSTAGRAM_IG_USER_ID`.
7. Set a webhook verify token string of your choice and put the same value in `INSTAGRAM_WEBHOOK_VERIFY_TOKEN`.
8. If you want webhook signature validation, copy your app secret from the Meta app dashboard into `INSTAGRAM_APP_SECRET`.

What each value means:

| Variable | Where to get it |
|----------|-----------------|
| `INSTAGRAM_PAGE_ID` | The Facebook Page linked to your Instagram account |
| `INSTAGRAM_PAGE_ACCESS_TOKEN` | Page access token from Meta developer tools or Graph API Explorer |
| `INSTAGRAM_IG_USER_ID` | Instagram Professional account ID from Graph API lookup |
| `INSTAGRAM_WEBHOOK_VERIFY_TOKEN` | Any secret string you choose for webhook verification |
| `INSTAGRAM_APP_SECRET` | Meta app dashboard > App Settings > Basic |

For local development, expose your app with a public HTTPS URL and configure the Instagram webhook callback to:

`https://YOUR_DOMAIN/api/webhooks/instagram`

If you are testing locally, a tunnel such as ngrok or Cloudflare Tunnel is usually the easiest way to get a public HTTPS endpoint.

### 4. Run

```bash
python run.py
```

Open **http://localhost:8000** in your browser.

---

## How it works

```
Every POLL_INTERVAL_SECONDS (default: 60s)
  └── Instagram webhook notifies the app about new comments
      └── For each active automation
          └── Match the keyword against the comment text
              ├── Skip if this comment was already processed
              ├── Send a private reply through the official API
              └── Log result + record lead
```

---

## Dashboard pages

| Page | Description |
|------|-------------|
| Dashboard | Stats overview + recent activity |
| Automations | Create / edit / toggle keyword→reply rules |
| Leads | All users who received a DM (CSV export) |
| DM Logs | Full processing history with status filter |

---

## Automation options

| Field | Description |
|-------|-------------|
| **Keyword** | Case-insensitive substring match (e.g. `FREE`, `send me`, `link`) |
| **DM Message** | Text to send. Use `{username}` for personalisation |
| **Require Follow** | Kept for legacy mode only |
| **Posts to Watch** | Specific media IDs, or leave blank to watch all recent media |

---

## Rate limiting & safety

- Official mode uses Instagram comment webhooks instead of polling.
- Each comment is deduplicated by `comment_id`, so the same comment will not be replied to twice.
- The supported flow requires an Instagram Professional account and the linked Facebook Page permissions.

> **Warning:** The official API can send private replies to eligible comment events, but it is not a general-purpose outbound DM API.

---

## Project structure

```
instagramautodm/
├── run.py                   # Entry point
├── requirements.txt
├── .env.example
├── data/                    # Created at runtime (DB + session)
└── app/
    ├── main.py              # FastAPI app + startup
    ├── config.py            # Settings (pydantic-settings)
    ├── database.py          # SQLAlchemy models + async engine
    ├── engine.py            # Legacy automation logic
    ├── instagram_service.py # Legacy Playwright-based Instagram automation
    ├── instagram_api_service.py # Official Instagram Graph API client
    ├── schemas.py           # Pydantic request/response models
    ├── routers/
    │   └── api.py           # REST API routes + webhook handlers
    ├── static/
    │   ├── css/style.css
    │   └── js/app.js
    └── templates/
        └── index.html
```

---

## API reference

All endpoints are under `/api`.

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/automations` | List all automations |
| POST | `/api/automations` | Create automation |
| PATCH | `/api/automations/{id}` | Update automation |
| DELETE | `/api/automations/{id}` | Delete automation |
| GET | `/api/leads` | List leads (filterable, paginated) |
| GET | `/api/leads/count` | Total lead count |
| GET | `/api/logs` | DM log history |
| GET | `/api/posts` | Your recent media (official API) or legacy recent posts |
| GET | `/api/status` | Integration + scheduler status |
| POST | `/api/poll/trigger` | Manually run a poll cycle in legacy mode |
| GET | `/api/webhooks/instagram` | Meta webhook verification |
| POST | `/api/webhooks/instagram` | Receive Instagram comment events |

Interactive docs: **http://localhost:8000/docs**

---

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `INTEGRATION_MODE` | `official` | `official` uses webhooks/private replies; `legacy` keeps browser automation |
| `INSTAGRAM_USERNAME` | — | Optional display name for the dashboard |
| `INSTAGRAM_PASSWORD` | — | Legacy browser login only |
| `INSTAGRAM_GRAPH_API_VERSION` | `v20.0` | Graph API version |
| `INSTAGRAM_PAGE_ID` | — | Facebook Page linked to your Instagram professional account |
| `INSTAGRAM_PAGE_ACCESS_TOKEN` | — | Page access token with messaging permissions |
| `INSTAGRAM_IG_USER_ID` | — | Instagram professional account ID used to list media |
| `INSTAGRAM_WEBHOOK_VERIFY_TOKEN` | — | Shared secret used to verify the webhook challenge |
| `INSTAGRAM_APP_SECRET` | — | Optional webhook signature verification secret |
| `POLL_INTERVAL_SECONDS` | `60` | Legacy polling interval |
| `DM_DELAY_MIN_SECONDS` | `8` | Min delay between DMs |
| `DM_DELAY_MAX_SECONDS` | `20` | Max delay between DMs |
| `MAX_DMS_PER_HOUR` | `30` | Hard hourly DM cap |
| `DATABASE_URL` | `sqlite+aiosqlite:///./data/automations.db` | Database connection string |
| `SESSION_FILE` | `./data/session.json` | Legacy browser session storage |
| `DASHBOARD_SECRET` | `changeme123` | (Reserved for future auth) |
