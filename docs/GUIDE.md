# Usage guide

How to put Personal Mail API online and connect your websites and apps to it.
Every step is short, and you can stop after step 3 if all you need is a
contact form.

1. [Deploy it](#1-deploy-it)
2. [Create a project](#2-create-a-project)
3. [Add a contact form to your website](#3-add-a-contact-form-to-your-website)
4. [Send emails from your app](#4-send-emails-from-your-app)
5. [Send alerts to yourself](#5-send-alerts-to-yourself)
6. [Track deliveries (optional)](#6-track-deliveries-optional)
7. [When something goes wrong](#when-something-goes-wrong)

---

## 1. Deploy it

You need three free accounts: **[Resend](https://resend.com)** (sends the
email), **[Supabase](https://supabase.com)** (stores your data) and
**[Render](https://render.com)** (runs the service).

**Resend**
- Create an API key under **API Keys**.
- To email anyone, verify a domain you own under **Domains**, ideally a
  subdomain such as `mail.yourdomain.com`. Without a domain you can use
  `onboarding@resend.dev`, but Resend then only delivers to your own Resend
  account email.

**Supabase**
- Create a project and click **Connect** → **Session pooler**.
- Copy the connection string and put your database password in it. Use a
  password made of letters and numbers only, so it needs no escaping.

**Render**
- Fork this repository, then go to **New → Blueprint** and select it.
- Fill in these values when asked:

| Setting | What to put |
|---|---|
| `DATABASE_URL` | The Supabase session pooler string |
| `RESEND_API_KEY` | Your Resend key |
| `DEFAULT_FROM_EMAIL` | e.g. `noreply@mail.yourdomain.com`, or `onboarding@resend.dev` |
| `ADMIN_EMAIL` / `ADMIN_PASSWORD` | Your sign-in for the admin page (password 12+ characters) |

Everything else has a sensible default. When the deploy is live, open
`https://<your-service>.onrender.com/health`. You should see `"database":"ok"`.

> On Render's free plan the service sleeps after about 15 idle minutes, so the
> first request after a quiet period takes up to a minute.

## 2. Create a project

Open `https://<your-service>.onrender.com` and sign in with your admin email
and password. Click **+ New**:

- **Name**: anything, e.g. `Portfolio`.
- **Slug**: the public id your website will use, e.g. `portfolio`.
- **Send messages to**: your inbox.
- **Websites allowed to use the contact form**: your site's address, e.g.
  `mysite.vercel.app`. Add `localhost:3000` while you test locally.

The project comes with an **API key** (`pmk_...`), shown only once. You only
need it for steps 4 and 5; a contact form does not use it.

## 3. Add a contact form to your website

Your form sends a request straight from the browser. No key is needed: only the
websites you allowed in step 2 are accepted.

```js
await fetch("https://<your-service>.onrender.com/api/v1/contact", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({
    project: "portfolio",   // your project's slug
    name: "Jane",
    email: "jane@example.com",
    subject: "Hello",       // optional
    message: "I'd like to work with you.",
    website: "",            // hidden anti-bot field, always empty
  }),
});
```

That's it. The message arrives in your inbox, and **Reply** answers the visitor.

Ready-made forms with loading and error states:
[React](../examples/react/ContactForm.jsx) ·
[Next.js](../examples/nextjs/components/ContactForm.tsx)

## 4. Send emails from your app

For emails to your users (welcome, password reset, verification), call the API
from your **server** with the project's key.

1. In the admin page, tick **Transactional email** on the project.
2. Store the key in your server's environment, e.g. `MAIL_API_KEY`. Never put
   it in browser code.

```bash
curl -X POST https://<your-service>.onrender.com/api/v1/emails/send \
  -H "Authorization: Bearer $MAIL_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"to": "user@example.com", "template": "welcome", "variables": {"name": "Jane"}}'
```

**Built-in templates:**

| Template | Variables |
|---|---|
| `welcome` | `name`, `message`, `action_url`, `action_text` (all optional) |
| `password_reset` | `reset_url` (required), `name`, `expires_in_minutes` |
| `email_verification` | `verification_url` or `code`, `name`, `expires_in_minutes` |

Prefer your own content? Send `"subject"` with `"html"` and/or `"text"`
instead of `"template"`.

Ready-made clients: [Next.js](../examples/nextjs/lib/personal-mail.ts) ·
[Python](../examples/python/personal_mail_client.py)

## 5. Send alerts to yourself

Let your app tell you when something happens. Alerts always go to the
project's "Send messages to" address.

```bash
curl -X POST https://<your-service>.onrender.com/api/v1/notifications \
  -H "Authorization: Bearer $MAIL_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"type": "user.registered", "subject": "New sign-up", "message": "Jane just joined.", "details": {"Plan": "Pro"}}'
```

## 6. Track deliveries (optional)

To see **delivered** or **bounced** instead of just **accepted**:

1. In Resend, open **Webhooks** → **Add endpoint** and enter
   `https://<your-service>.onrender.com/api/v1/webhooks/resend`.
2. Select the `email.*` events.
3. Copy the signing secret (`whsec_...`) into Render as `RESEND_WEBHOOK_SECRET`.

Statuses then update on the admin page automatically.

---

## When something goes wrong

| You see | What to do |
|---|---|
| `ORIGIN_NOT_ALLOWED` | Add the site's exact address (as shown in the browser bar) to the project's allowed websites. |
| `PROJECT_NOT_FOUND` | The `project` value must be the slug, e.g. `portfolio`. |
| `401` | The API key is wrong or was revoked. Generate a new one on the admin page. |
| `403` when sending | Turn on **Transactional email** for the project. |
| `429` | A rate limit or daily quota was reached. Raise it on the admin page or wait. |
| "domain is not verified" | Verify your domain in Resend, or use `onboarding@resend.dev` (only delivers to your own Resend email). |
| First request is slow | The free server was asleep. It wakes within a minute. |

The full API, with every endpoint and field, is at
`https://<your-service>.onrender.com/docs`.

<details>
<summary><strong>Run it on your own computer</strong></summary>

```bash
cp .env.example .env    # fill in RESEND_API_KEY, DEFAULT_FROM_EMAIL, ADMIN_EMAIL, ADMIN_PASSWORD
docker compose up --build
```

Open <http://localhost:8000>. Run the tests with `pytest` (needs the database
from `docker compose up -d db`).

</details>

<details>
<summary><strong>All settings</strong></summary>

| Setting | Default | Meaning |
|---|---|---|
| `DATABASE_URL` | required | PostgreSQL connection string |
| `RESEND_API_KEY` | required in production | Resend API key |
| `DEFAULT_FROM_EMAIL` / `DEFAULT_FROM_NAME` | required / Personal Mail API | Default sender |
| `ALLOWED_SENDER_DOMAINS` | the sender's domain | Extra email domains projects may send from |
| `RESEND_WEBHOOK_SECRET` | none | Enables delivery tracking |
| `JWT_SECRET_KEY` | required | 32+ random characters (Render generates it) |
| `ADMIN_EMAIL` / `ADMIN_PASSWORD` | none | Admin account, created or updated on start |
| `TURNSTILE_SECRET_KEY` | none | For projects using Cloudflare Turnstile |
| `CONTACT_RATE_LIMIT_PER_IP` | 5 | Contact messages per visitor per hour |
| `TRUSTED_PROXY_COUNT` | 0 (Render: 1) | Proxies in front of the service |
| `ADMIN_UI_ENABLED` / `DOCS_ENABLED` | true / true | Admin page and `/docs` |

The complete list, with comments, is in [`.env.example`](../.env.example).

</details>
