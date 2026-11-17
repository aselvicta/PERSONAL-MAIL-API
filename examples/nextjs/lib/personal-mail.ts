import "server-only"; // build fails if this module is ever imported by client code

/**
 * Minimal server-side client for Personal Mail API.
 * The private project API key is read from a server-only environment variable.
 */
const API_URL = process.env.MAIL_API_URL!;
const API_KEY = process.env.MAIL_API_KEY!;

export class PersonalMailError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
  ) {
    super(message);
  }
}

async function call<T>(path: string, body: unknown): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${API_KEY}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify(body),
    cache: "no-store",
  });
  const json = await response.json();
  if (!response.ok || !json.success) {
    throw new PersonalMailError(response.status, json.error?.code ?? "UNKNOWN", json.message);
  }
  return json.data as T;
}

type Accepted = { id: string; message_id: string | null; status: string };

export function sendEmail(params: {
  to: string;
  subject?: string;
  html?: string;
  text?: string;
  reply_to?: string;
  sender_name?: string;
  template?: "welcome" | "password_reset" | "email_verification" | "notification";
  variables?: Record<string, string | number | boolean | null>;
}) {
  return call<Accepted>("/api/v1/emails/send", params);
}

export function notify(params: {
  type: string;
  subject: string;
  message: string;
  details?: Record<string, string | number | boolean | null>;
}) {
  return call<Accepted>("/api/v1/notifications", params);
}
