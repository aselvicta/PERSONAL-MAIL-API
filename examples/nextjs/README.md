# Next.js example

| File | Runs in | Uses |
|---|---|---|
| `components/ContactForm.tsx` | Browser | Public `POST /api/v1/contact` with the project **slug** (no secret) |
| `lib/personal-mail.ts` | Server only | Private API key from `MAIL_API_KEY` |
| `app/api/send-welcome/route.ts` | Server only | Transactional email + owner notification |

1. Copy `.env.local.example` to `.env.local` and fill it in.
2. Add your site origin (for example `https://myportfolio.com` and
   `http://localhost:3000`) to the project's `allowed_origins`.
3. To send transactional email, enable `transactional_enabled` on the project.

> Never put the `pmk_...` key in a `NEXT_PUBLIC_` variable or in client components.
> `import "server-only"` makes the build fail if that ever happens.
