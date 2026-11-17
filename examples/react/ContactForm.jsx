/**
 * Portfolio contact form for React (Vite, CRA, or any bundler).
 *
 * Talks to the PUBLIC contact endpoint, so no secret is needed in the browser.
 * Set in .env:
 *   VITE_MAIL_API_URL=https://your-mail-api.onrender.com
 *   VITE_MAIL_PROJECT=portfolio
 *
 * Add your site's origin to the project's `allowed_origins`.
 * NEVER put a project API key (pmk_...) in frontend code or VITE_ variables.
 */
import { useState } from "react";

const API_URL = import.meta.env.VITE_MAIL_API_URL;
const PROJECT = import.meta.env.VITE_MAIL_PROJECT;

const initial = { name: "", email: "", subject: "", message: "", website: "" };

export default function ContactForm() {
  const [values, setValues] = useState(initial);
  const [state, setState] = useState({ status: "idle", message: "" });

  const update = (event) =>
    setValues((v) => ({ ...v, [event.target.name]: event.target.value }));

  async function handleSubmit(event) {
    event.preventDefault();
    setState({ status: "sending", message: "" });
    try {
      const response = await fetch(`${API_URL}/api/v1/contact`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          project: PROJECT,
          ...values,
          subject: values.subject || undefined,
        }),
      });
      const body = await response.json();
      if (!response.ok || !body.success) {
        throw new Error(body.message || "Could not send your message.");
      }
      setValues(initial);
      setState({ status: "sent", message: "Thanks! I'll get back to you soon." });
    } catch (error) {
      setState({ status: "error", message: error.message });
    }
  }

  return (
    <form onSubmit={handleSubmit}>
      <input name="name" placeholder="Your name" value={values.name} onChange={update} required maxLength={100} />
      <input name="email" type="email" placeholder="you@example.com" value={values.email} onChange={update} required />
      <input name="subject" placeholder="Subject (optional)" value={values.subject} onChange={update} maxLength={200} />
      <textarea name="message" placeholder="Your message" value={values.message} onChange={update} required maxLength={5000} rows={6} />

      {/* Honeypot: keep it hidden and empty. */}
      <input
        name="website"
        value={values.website}
        onChange={update}
        tabIndex={-1}
        autoComplete="off"
        aria-hidden="true"
        style={{ position: "absolute", left: "-10000px" }}
      />

      <button type="submit" disabled={state.status === "sending"}>
        {state.status === "sending" ? "Sending..." : "Send"}
      </button>
      {state.message && <p role="status">{state.message}</p>}
    </form>
  );
}
