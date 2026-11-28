"use strict";

const statusMessage = document.getElementById("status");
const signIn = document.getElementById("sign-in");
const onboarding = document.getElementById("onboarding");
const signOut = document.getElementById("sign-out");
let csrfToken;

async function request(path, options) {
  return fetch("/api/v1/auth/" + path, { cache: "no-store", ...options });
}

async function load() {
  if (location.pathname === "/auth/error") {
    statusMessage.textContent = "Sign-in could not complete. Start a fresh sign-in.";
    signIn.hidden = false;
    return;
  }
  const pending = await request("onboarding");
  if (pending.ok) {
    csrfToken = (await pending.json()).csrf_token;
    statusMessage.textContent = "Confirm your profile to finish signing in.";
    onboarding.hidden = false;
    return;
  }
  const session = await request("session");
  if (session.ok) {
    csrfToken = (await session.json()).csrf_token;
    statusMessage.textContent = "Signed in.";
    signOut.hidden = false;
  } else if (session.status === 401) {
    statusMessage.textContent = "Sign in to verify the local flow.";
    signIn.hidden = false;
  } else {
    statusMessage.textContent = "Authentication is unavailable.";
  }
}

async function submit(path, payload, button) {
  button.disabled = true;
  try {
    const headers = { "X-CSRF-Token": csrfToken };
    if (payload) headers["Content-Type"] = "application/json";
    const result = await request(path, {
      method: "POST",
      headers,
      body: payload ? JSON.stringify(payload) : undefined,
    });
    if (result.ok) {
      location.replace("/");
      return;
    }
    statusMessage.textContent = "The request could not complete. Reload to try again.";
  } catch {
    statusMessage.textContent = "Authentication is unavailable.";
  } finally {
    button.disabled = false;
  }
}

onboarding.addEventListener("submit", (event) => {
  event.preventDefault();
  const values = Object.fromEntries(new FormData(onboarding));
  submit("onboarding", values, onboarding.querySelector("button"));
});
signOut.addEventListener("click", () => submit("logout", null, signOut));
load().catch(() => {
  statusMessage.textContent = "Authentication is unavailable.";
});
