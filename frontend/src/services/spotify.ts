const CLIENT_ID = import.meta.env.VITE_SPOTIFY_CLIENT_ID as string | undefined;
// Must exactly match a URI registered in your Spotify app's dashboard
const REDIRECT_URI =
  (import.meta.env.VITE_SPOTIFY_REDIRECT_URI as string | undefined) ?? window.location.origin;
const SCOPES = "playlist-modify-private playlist-modify-public";

function generateRandomString(length: number): string {
  const array = new Uint8Array(length);
  crypto.getRandomValues(array);
  return btoa(String.fromCharCode(...array))
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=/g, "")
    .slice(0, length);
}

async function sha256(plain: string): Promise<ArrayBuffer> {
  return crypto.subtle.digest("SHA-256", new TextEncoder().encode(plain));
}

function base64urlEncode(buffer: ArrayBuffer): string {
  return btoa(String.fromCharCode(...new Uint8Array(buffer)))
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=/g, "");
}

export function getStoredToken(): string | null {
  const token = localStorage.getItem("spotify_access_token");
  const expiresAt = Number(localStorage.getItem("spotify_expires_at") ?? 0);
  if (!token || Date.now() > expiresAt) return null;
  return token;
}

export function clearSpotifyToken(): void {
  localStorage.removeItem("spotify_access_token");
  localStorage.removeItem("spotify_refresh_token");
  localStorage.removeItem("spotify_expires_at");
  localStorage.removeItem("spotify_code_verifier");
}

export async function exchangeCodeForToken(code: string): Promise<void> {
  if (!CLIENT_ID) throw new Error("VITE_SPOTIFY_CLIENT_ID is not configured");

  const verifier = localStorage.getItem("spotify_code_verifier");
  if (!verifier) throw new Error("No code verifier — try authenticating again");

  const res = await fetch("https://accounts.spotify.com/api/token", {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({
      client_id: CLIENT_ID,
      grant_type: "authorization_code",
      code,
      redirect_uri: REDIRECT_URI,
      code_verifier: verifier,
    }),
  });

  if (!res.ok) {
    const body = await res.text();
    throw new Error(`Token exchange failed (${res.status}): ${body}`);
  }

  const data = await res.json();
  localStorage.setItem("spotify_access_token", data.access_token);
  if (data.refresh_token) localStorage.setItem("spotify_refresh_token", data.refresh_token);
  localStorage.setItem("spotify_expires_at", String(Date.now() + data.expires_in * 1000));
  localStorage.removeItem("spotify_code_verifier");
}

// Opens a popup and resolves when the user finishes authenticating.
export function openSpotifyAuth(): Promise<void> {
  return new Promise(async (resolve, reject) => {
    if (!CLIENT_ID) {
      reject(new Error("Spotify is not configured — set VITE_SPOTIFY_CLIENT_ID"));
      return;
    }

    const verifier = generateRandomString(64);
    const challenge = base64urlEncode(await sha256(verifier));
    // localStorage is shared across same-origin windows, so the popup can read this
    localStorage.setItem("spotify_code_verifier", verifier);

    const params = new URLSearchParams({
      client_id: CLIENT_ID,
      response_type: "code",
      redirect_uri: REDIRECT_URI,
      scope: SCOPES,
      code_challenge_method: "S256",
      code_challenge: challenge,
      show_dialog: "true", // force re-consent so the token always carries current scopes
    });

    const popup = window.open(
      `https://accounts.spotify.com/authorize?${params}`,
      "spotify-auth",
      "width=480,height=700,left=200,top=100",
    );

    if (!popup) {
      reject(new Error("Popup was blocked — allow popups for this site and try again"));
      return;
    }

    let settled = false;

    const sameOrigin = (o: string) =>
      o === window.location.origin ||
      o.replace("127.0.0.1", "localhost") === window.location.origin ||
      o.replace("localhost", "127.0.0.1") === window.location.origin;

    const handler = (event: MessageEvent) => {
      if (!sameOrigin(event.origin)) return;
      if (event.data?.type === "spotify_auth_done") {
        settled = true;
        window.removeEventListener("message", handler);
        clearInterval(closePoll);
        resolve();
      } else if (event.data?.type === "spotify_auth_error") {
        settled = true;
        window.removeEventListener("message", handler);
        clearInterval(closePoll);
        reject(new Error(event.data.error ?? "Authentication failed"));
      }
    };

    window.addEventListener("message", handler);

    const closePoll = setInterval(() => {
      if (popup.closed && !settled) {
        settled = true;
        clearInterval(closePoll);
        window.removeEventListener("message", handler);
        reject(new Error("Authentication cancelled"));
      }
    }, 500);
  });
}

async function spotifyFetch<T>(token: string, path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`https://api.spotify.com/v1${path}`, {
    ...init,
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
  });
  if (res.status === 401) {
    clearSpotifyToken();
    throw new Error("Spotify session expired — please reconnect");
  }
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`Spotify API error ${res.status}: ${body}`);
  }
  return res.json();
}

export async function getSpotifyUserId(token: string): Promise<string> {
  const data = await spotifyFetch<{ id: string }>(token, "/me");
  return data.id;
}

export async function searchSpotifyTrack(
  token: string,
  artist: string,
  name: string,
): Promise<string | null> {
  const q = `track:"${name}" artist:"${artist}"`;
  const params = new URLSearchParams({ q, type: "track", limit: "1" });
  const data = await spotifyFetch<{ tracks: { items: Array<{ uri: string }> } }>(
    token,
    `/search?${params}`,
  );
  return data.tracks.items[0]?.uri ?? null;
}

export async function createSpotifyPlaylist(
  token: string,
  userId: string,
  name: string,
  trackUris: string[],
): Promise<string> {
  const playlist = await spotifyFetch<{ id: string; external_urls: { spotify: string } }>(
    token,
    `/users/${userId}/playlists`,
    {
      method: "POST",
      body: JSON.stringify({ name, public: false, description: "Exported from pyo" }),
    },
  );

  for (let i = 0; i < trackUris.length; i += 100) {
    await spotifyFetch(token, `/playlists/${playlist.id}/tracks`, {
      method: "POST",
      body: JSON.stringify({ uris: trackUris.slice(i, i + 100) }),
    });
  }

  return playlist.external_urls.spotify;
}
