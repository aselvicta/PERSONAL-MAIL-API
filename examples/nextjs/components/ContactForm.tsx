"use client";

/**
 * Portfolio contact form for Next.js (App Router).
 *
 * Calls the PUBLIC contact endpoint straight from the browser. No secret is
 * involved: the project is identified by its public slug, and the API protects
 * the endpoint with origin checks, rate limits, a honeypot and (optionally)
 * Cloudflare Turnstile. Add your site's origin to the project's
 * `allowed_origins`.
 */
import { FormEvent, useState } from "react";

const API_URL = process.env.NEXT_PUBLIC_MAIL_API_URL!;
const PROJECT = process.env.NEXT_PUBLIC_MAIL_PROJECT!;

type Status = { kind: "idle" | "sending" | "sent" | "error"; message?: string };

export default function ContactForm() {
  const [status, setStatus] = useState<Status>({ kind: "idle" });

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setStatus({ kind: "sending" });

    try {
      const response = await fetch(`${API_URL}/api/v1/contact`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          project: PROJECT,
          name: form.get("name"),
          email: form.get("email"),
          subject: form.get("subject") || undefined,
          message: form.get("message"),
          website: form.get("website"), // honeypot: must stay empty
          // With Turnstile enabled, the widget adds this hidden field:
          turnstile_token: form.get("cf-turnstile-response") || undefined,
        }),
      });
      const body = await response.json();
      if (!response.ok || !body.success) {
        throw new Error(
          response.status === 429
            ? "Too many messages. Please try again later."
            : body.message ?? "Something went wrong.",
        );
      }
      setStatus({ kind: "sent", message: "Thanks! Your message has been sent." });
      event.currentTarget.reset();
    } catch (error) {
      setStatus({ kind: "error", message: (error as Error).message });
    }
  }

  return (
    <form onSubmit={onSubmit}>
      <label>
        Name
        <input name="name" required maxLength={100} />
      </label>
      <label>
        Email
        <input name="email" type="email" required />
      </label>
      <label>
        Subject
        <input name="subject" maxLength={200} />
      </label>
      <label>
        Message
        <textarea name="message" required maxLength={5000} rows={6} />
      </label>

      {/* Honeypot: hidden from humans, irresistible to bots. */}
      <input
        name="website"
        tabIndex={-1}
        autoComplete="off"
        aria-hidden="true"
        style={{ position: "absolute", left: "-10000px" }}
      />

      {/* Optional Turnstile widget (load https://challenges.cloudflare.com/turnstile/v0/api.js):
          <div className="cf-turnstile" data-sitekey={process.env.NEXT_PUBLIC_TURNSTILE_SITE_KEY} /> */}

      <button type="submit" disabled={status.kind === "sending"}>
        {status.kind === "sending" ? "Sending..." : "Send message"}
      </button>
      {status.message && <p role="status">{status.message}</p>}
    </form>
  );
}
