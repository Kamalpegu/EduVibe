const STORAGE_KEY = "eduvibe.slide-search.history.v1";
const accountWrites = new Map();

async function accountRequest(url, options = {}) {
  const response = await fetch(url, {
    credentials: "same-origin",
    ...options,
    headers: {
      ...(options.body ? { "Content-Type": "application/json" } : {}),
      ...options.headers,
    },
  });
  if (!response.ok) {
    let message = `Could not save account chat history (${response.status}).`;
    try {
      const body = await response.json();
      message = body.detail || message;
    } catch (error) {
      console.warn("Could not read the chat history error response.", error);
    }
    throw new Error(message);
  }
  return response.status === 204 ? null : response.json();
}

function queueAccountWrite(chatId, operation) {
  const previous = accountWrites.get(chatId) || Promise.resolve();
  const current = previous.catch(() => {}).then(operation);
  accountWrites.set(chatId, current);
  current.finally(() => {
    if (accountWrites.get(chatId) === current) accountWrites.delete(chatId);
  }).catch(() => {});
  return current;
}

export class LocalHistoryStore {
  load() {
    try {
      const parsed = JSON.parse(localStorage.getItem(STORAGE_KEY) || "[]");
      return Array.isArray(parsed) ? parsed : [];
    } catch (error) {
      console.error("Could not read saved chat history.", error);
      return [];
    }
  }

  save(chats) {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(chats));
    } catch (error) {
      console.error("Could not save chat history.", error);
      throw new Error("Your browser could not save chat history. Check available storage.");
    }
  }

  upsert(chats, chat) {
    const next = chats.filter((item) => item.id !== chat.id);
    next.unshift(chat);
    this.save(next);
    return next;
  }

  remove(chats, chatId) {
    const next = chats.filter((item) => item.id !== chatId);
    this.save(next);
    return next;
  }

  loadAccount() {
    return accountRequest("/api/history");
  }

  saveAccount(chat) {
    const snapshot = JSON.stringify(chat);
    return queueAccountWrite(chat.id, () => accountRequest(
      `/api/history/${encodeURIComponent(chat.id)}`,
      { method: "PUT", body: snapshot },
    ));
  }

  removeAccount(chatId) {
    return queueAccountWrite(chatId, () => accountRequest(
      `/api/history/${encodeURIComponent(chatId)}`,
      { method: "DELETE" },
    ));
  }

  flushAccountWrites() {
    return Promise.allSettled([...accountWrites.values()]);
  }
}

export const historyStore = new LocalHistoryStore();
