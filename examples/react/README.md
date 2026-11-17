# React example

`ContactForm.jsx` is a self-contained contact form that calls the public
`POST /api/v1/contact` endpoint with the project's **slug**. There are no secrets in the browser.

To send transactional email (welcome, password reset, and so on) from a React
app, call Personal Mail API from **your backend** (Node/Express, a serverless
function, or similar) with the private project key. See `../nextjs/lib/personal-mail.ts`
or `../python/personal_mail_client.py` for server-side clients.
