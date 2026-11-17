/**
 * Example server route: send a welcome email after sign-up and notify yourself.
 * Runs on the server, so the private API key never reaches the browser.
 *
 * In a real app, call these helpers from your sign-up logic instead of
 * exposing an open endpoint. An unauthenticated route like this could be abused.
 */
import { NextResponse } from "next/server";
import { notify, PersonalMailError, sendEmail } from "@/lib/personal-mail";

export async function POST(request: Request) {
  const { email, name } = await request.json();

  try {
    const result = await sendEmail({
      to: email,
      template: "welcome",
      variables: {
        name,
        action_url: "https://careerdocs.example.com/dashboard",
        action_text: "Open your dashboard",
      },
    });
    await notify({
      type: "user.registered",
      subject: "New user registration",
      message: `${name} just created an account.`,
      details: { Email: email },
    });
    return NextResponse.json({ ok: true, emailId: result.id });
  } catch (error) {
    if (error instanceof PersonalMailError) {
      return NextResponse.json({ ok: false, code: error.code }, { status: 502 });
    }
    throw error;
  }
}
