const GOOGLE_IDENTITY_SCRIPT = "https://accounts.google.com/gsi/client";
let identitySdkPromise;
let initializedClientId = null;
let credentialHandler = null;

async function apiRequest(url, options = {}) {
  const response = await fetch(url, {
    credentials: "same-origin",
    ...options,
    headers: {
      ...(options.body ? { "Content-Type": "application/json" } : {}),
      ...options.headers,
    },
  });
  if (!response.ok) {
    let message = `Account request failed (${response.status}).`;
    try {
      const body = await response.json();
      message = body.detail || message;
    } catch (error) {
      console.warn("Could not read the account error response.", error);
    }
    throw new Error(message);
  }
  return response.status === 204 ? null : response.json();
}

export function getGoogleAuthConfig() {
  return apiRequest("/api/auth/config");
}

export async function getCurrentAccount() {
  const response = await fetch("/api/auth/me", { credentials: "same-origin" });
  if (response.status === 204) return null;
  if (!response.ok) throw new Error(`Could not restore account session (${response.status}).`);
  return response.json();
}

export function exchangeGoogleCredential(credential) {
  return apiRequest("/api/auth/google", {
    method: "POST",
    body: JSON.stringify({ credential }),
  });
}

export function signOutGoogle() {
  return apiRequest("/api/auth/logout", { method: "POST" });
}

function loadIdentitySdk() {
  if (globalThis.google?.accounts?.id) return Promise.resolve(globalThis.google);
  if (identitySdkPromise) return identitySdkPromise;
  identitySdkPromise = new Promise((resolve, reject) => {
    const existing = document.querySelector(`script[src="${GOOGLE_IDENTITY_SCRIPT}"]`);
    const script = existing || document.createElement("script");
    const fail = () => {
      identitySdkPromise = null;
      script.remove();
      reject(new Error("Google sign-in could not load. Check your internet connection and content blockers."));
    };
    script.addEventListener("load", () => {
      if (globalThis.google?.accounts?.id) resolve(globalThis.google);
      else fail();
    }, { once: true });
    script.addEventListener("error", fail, { once: true });
    if (!existing) {
      script.src = GOOGLE_IDENTITY_SCRIPT;
      script.async = true;
      script.defer = true;
      document.head.append(script);
    }
    if (globalThis.google?.accounts?.id) resolve(globalThis.google);
  });
  return identitySdkPromise;
}

export async function renderGoogleSignInButton(container, clientId, onCredential) {
  const google = await loadIdentitySdk();
  credentialHandler = onCredential;
  if (initializedClientId !== clientId) {
    google.accounts.id.initialize({
      client_id: clientId,
      callback: (response) => {
        if (!response.credential) {
          credentialHandler?.(null, new Error("Google did not return a sign-in credential."));
          return;
        }
        credentialHandler?.(response.credential, null);
      },
      cancel_on_tap_outside: true,
    });
    initializedClientId = clientId;
  }
  google.accounts.id.renderButton(container, {
    type: "standard",
    theme: document.documentElement.dataset.theme === "dark" ? "filled_black" : "outline",
    size: "large",
    text: "continue_with",
    shape: "pill",
    width: Math.min(280, container.clientWidth),
    logo_alignment: "left",
  });
}
