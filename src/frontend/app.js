import { Composer } from "./components/Composer.js";
import { Sidebar } from "./components/Sidebar.js";
import { Thread } from "./components/Thread.js";
import { TopBar } from "./components/TopBar.js";
import { generateSlides } from "./services/generate.js";
import { downloadPresentation, downloadSlide } from "./services/download.js";
import { historyStore } from "./services/history.js";
import { tts } from "./services/tts.js";
import {
  exchangeGoogleCredential,
  getCurrentAccount,
  getGoogleAuthConfig,
  renderGoogleSignInButton,
  signOutGoogle,
} from "./services/googleAuth.js";

const root = document.querySelector("#app");
const examples = [
  "How do solar panels work?",
  "The basics of SQL",
  "What causes the northern lights?",
];
let chats = historyStore.load().map((chat) => ({
  ...chat,
  turns: (chat.turns || []).map((turn) => turn.status === "loading"
    ? { ...turn, status: "error", error: "This search was interrupted when the app was closed." }
    : turn),
}));
const chatOwners = new Map(chats.map((chat) => [chat.id, null]));

let activeChatId = chats[0]?.id || null;
let drawerOpen = false;
let accountMenuOpen = false;
let accountUser = null;
let googleAuthConfig = null;
let accountLoading = false;
let accountHistoryLoading = false;
let accountLoadGeneration = 0;
let pptDownloadBusy = false;
let notice = "";
let theme = null;
let narrationLanguage = "en";
try {
  theme = localStorage.getItem("eduvibe.theme");
  narrationLanguage = localStorage.getItem("eduvibe.language") || "en";
} catch (error) {
  console.warn("Could not read saved display preferences.", error);
}
function newestReadyTurnId(chatList) {
  for (const chat of chatList) {
    const turn = [...chat.turns].reverse().find((item) => item.status === "ready" && item.slides?.length);
    if (turn) return turn.id;
  }
  return null;
}

let lastReadyTurn = newestReadyTurnId(chats);
let lastUsedTurnId = lastReadyTurn;

function activeChat() {
  return chats.find((chat) => chat.id === activeChatId) || null;
}

function findTurn(turnId) {
  for (const chat of chats) {
    const turn = chat.turns.find((item) => item.id === turnId);
    if (turn) return { chat, turn };
  }
  return null;
}

function persistChat(chat) {
  const owner = chatOwners.get(chat.id);
  if (owner !== undefined && owner !== null) {
    if (accountUser?.email !== owner) return;
    chats = [chat, ...chats.filter((item) => item.id !== chat.id)]
      .sort((left, right) => right.updatedAt - left.updatedAt);
    historyStore.saveAccount(chat).catch((error) => {
      console.error("Signed-in chat history could not be saved.", error);
      setNotice(error.message || "Could not save your account chat history.");
    });
    return;
  }
  try {
    const guestChats = historyStore.upsert(historyStore.load(), chat);
    if (!accountUser) chats = guestChats;
  } catch (error) {
    if (!accountUser && !chats.some((item) => item.id === chat.id)) chats.unshift(chat);
    notice = error.message;
    const noticeNode = document.querySelector(".notice");
    if (noticeNode) {
      noticeNode.textContent = notice;
      noticeNode.hidden = false;
    }
    console.error("Chat changes could not be persisted.", error);
  }
}

function installAccountHistory(user, savedChats) {
  chats = savedChats.map((chat) => ({
    ...chat,
    turns: (chat.turns || []).map((turn) => turn.status === "loading"
      ? { ...turn, status: "error", error: "This search was interrupted when the app was closed." }
      : turn),
  }));
  chatOwners.clear();
  for (const chat of chats) chatOwners.set(chat.id, user.email);
  activeChatId = chats[0]?.id || null;
  lastReadyTurn = newestReadyTurnId(chats);
  lastUsedTurnId = lastReadyTurn;
}

async function loadAccountHistory(user) {
  const generation = ++accountLoadGeneration;
  accountUser = user;
  accountHistoryLoading = true;
  chats = [];
  chatOwners.clear();
  activeChatId = null;
  lastReadyTurn = null;
  lastUsedTurnId = null;
  render();
  try {
    const savedChats = await historyStore.loadAccount();
    if (generation !== accountLoadGeneration || accountUser?.email !== user.email) return;
    installAccountHistory(user, savedChats);
  } catch (error) {
    if (generation !== accountLoadGeneration) return;
    accountUser = user;
    chats = [];
    chatOwners.clear();
    activeChatId = null;
    lastReadyTurn = null;
    lastUsedTurnId = null;
    throw error;
  } finally {
    if (generation === accountLoadGeneration) {
      accountHistoryLoading = false;
      render();
    }
  }
}

function setNotice(message) {
  notice = message;
  render();
  window.setTimeout(() => {
    if (notice === message) {
      notice = "";
      render();
    }
  }, 5000);
}

function restoreAccount() {
  getGoogleAuthConfig().then((config) => {
    googleAuthConfig = config;
    if (accountMenuOpen) renderTopBar();
  }).catch((error) => {
    console.error("Could not load Google sign-in configuration.", error);
    setNotice(error.message || "Could not load Google sign-in configuration.");
  });
  getCurrentAccount().then(async (user) => {
    if (user) await loadAccountHistory(user);
  }).catch((error) => {
    console.error("Could not restore the signed-in account history.", error);
    setNotice(error.message || "Could not restore your account chat history.");
  });
}

window.addEventListener("eduvibe:tts-error", (event) => {
  setNotice(event.detail?.message || "Puter could not generate narration. Please try again.");
});

function useTurn(turnId) {
  lastUsedTurnId = turnId;
}

function renderThread() {
  const chat = activeChat();
  const thread = document.querySelector(".thread");
  Thread(thread, chat, {
    onSlideChange: (chatId, turnId, index) => {
      const targetChat = chats.find((item) => item.id === chatId);
      const turn = targetChat?.turns.find((item) => item.id === turnId);
      if (!turn) return;
      turn.currentSlide = index;
      persistChat(targetChat);
      if (activeChatId === chatId) renderThread();
    },
    onDownload: (turn) => downloadCurrentSlide(turn.id),
    onUseTurn: useTurn,
  });
  const emptyState = document.querySelector(".empty-state");
  emptyState.hidden = Boolean(chat?.turns?.length);
}

function renderSidebar() {
  const workspace = document.querySelector(".workspace");
  const host = document.querySelector(".sidebar-host");
  host.replaceChildren(Sidebar(chats, activeChatId, {
    onNewChat: () => {
      tts.stop();
      activeChatId = null;
      drawerOpen = false;
      render();
      document.querySelector("#slide-search-input")?.focus();
    },
    onOpenChat: (chatId) => {
      activeChatId = chatId;
      drawerOpen = false;
      const ready = [...(chats.find((item) => item.id === chatId)?.turns || [])]
        .reverse().find((turn) => turn.status === "ready");
      if (ready) lastUsedTurnId = ready.id;
      render();
    },
    onDeleteChat: (chatId) => {
      const deleted = chats.find((chat) => chat.id === chatId);
      for (const turn of deleted?.turns || []) tts.stop(turn.id);
      const restoreDeletedChat = (error) => {
        chats.unshift(deleted);
        chatOwners.set(deleted.id, accountUser?.email || null);
        if (activeChatId === chatId) activeChatId = chatId;
        render();
        setNotice(error.message || "Could not delete this chat.");
      };
      if (accountUser) {
        chats = chats.filter((item) => item.id !== chatId);
        chatOwners.delete(chatId);
        if (activeChatId === chatId) activeChatId = chats[0]?.id || null;
        if (deleted?.turns.some((turn) => turn.id === lastUsedTurnId)) {
          lastReadyTurn = newestReadyTurnId(chats);
          lastUsedTurnId = lastReadyTurn;
        }
        render();
        historyStore.removeAccount(chatId).catch(restoreDeletedChat);
        return;
      }
      try {
        chats = historyStore.remove(chats, chatId);
        chatOwners.delete(chatId);
      } catch (error) {
        setNotice(error.message);
        return;
      }
      if (activeChatId === chatId) activeChatId = chats[0]?.id || null;
      if (deleted?.turns.some((turn) => turn.id === lastUsedTurnId)) {
        lastReadyTurn = newestReadyTurnId(chats);
        lastUsedTurnId = lastReadyTurn;
      }
      render();
    },
  }));
  host.id = "chat-history-drawer";
  host.inert = !drawerOpen;
  host.setAttribute("aria-hidden", String(!drawerOpen));
  workspace.classList.toggle("drawer-open", drawerOpen);
}

function downloadCurrentSlide(turnId = lastUsedTurnId) {
  const found = turnId ? findTurn(turnId) : null;
  if (!found || found.turn.status !== "ready" || !found.turn.slides?.length) return;
  const index = Math.min(found.turn.currentSlide || 0, found.turn.slides.length - 1);
  downloadSlide(found.turn.slides[index], index, found.turn.slides.length);
}

async function downloadCurrentPresentation() {
  const found = lastUsedTurnId ? findTurn(lastUsedTurnId) : null;
  if (!found || found.turn.status !== "ready" || !found.turn.slides?.length || pptDownloadBusy) return;
  pptDownloadBusy = true;
  notice = "Preparing your PowerPoint presentation…";
  render();
  try {
    await downloadPresentation(found.turn.query, found.turn.lang);
    notice = "PowerPoint presentation downloaded.";
  } catch (error) {
    notice = error.message || "Could not download the PowerPoint presentation.";
    console.error("PowerPoint export failed.", error);
  } finally {
    pptDownloadBusy = false;
    render();
    const currentNotice = notice;
    window.setTimeout(() => {
      if (notice === currentNotice) {
        notice = "";
        render();
      }
    }, 5000);
  }
}

function renderTopBar() {
  const host = document.querySelector(".topbar-host");
  const topbar = TopBar({
    hasSlides: chats.some((chat) => chat.turns.some((turn) => turn.status === "ready" && turn.slides?.length)),
    user: accountUser,
    narrationLanguage,
    sidebarOpen: drawerOpen,
    theme,
    onDownload: downloadCurrentPresentation,
    downloadBusy: pptDownloadBusy,
    onNarrationLanguageChange: (nextLanguage) => {
      if (nextLanguage !== "en" && nextLanguage !== "hi") return;
      narrationLanguage = nextLanguage;
      try {
        localStorage.setItem("eduvibe.language", narrationLanguage);
      } catch (error) {
        console.warn("Could not save the language preference.", error);
      }
      renderTopBar();
    },
    onToggleAccount: () => {
      accountMenuOpen = !accountMenuOpen;
      renderTopBar();
    },
    onToggleTheme: toggleTheme,
    onToggleSidebar: () => {
      drawerOpen = !drawerOpen;
      renderSidebar();
      renderTopBar();
      if (drawerOpen) {
        document.querySelector(".new-chat-button")?.focus();
      } else {
        document.querySelector(".history-toggle-button")?.focus();
      }
    },
  });
  host.replaceChildren(topbar.element);
  if (accountMenuOpen) {
    const menu = document.createElement("div");
    menu.className = "account-menu";
    menu.setAttribute("role", "dialog");
    menu.setAttribute("aria-label", "Google account");
    if (accountUser) {
      const profile = document.createElement("div");
      profile.className = "account-profile";
      const identity = document.createElement("div");
      identity.className = "account-identity";
      if (accountUser.picture) {
        const picture = document.createElement("img");
        picture.className = "account-picture";
        picture.src = accountUser.picture;
        picture.alt = "";
        picture.referrerPolicy = "no-referrer";
        identity.append(picture);
      }
      const details = document.createElement("div");
      details.className = "account-details";
      const name = document.createElement("strong");
      name.textContent = accountUser.name || "Google user";
      const email = document.createElement("span");
      email.textContent = accountUser.email;
      details.append(name, email);
      identity.append(details);
      const signOut = document.createElement("button");
      signOut.type = "button";
      signOut.className = "account-action";
      signOut.textContent = "Sign out";
      signOut.addEventListener("click", async () => {
        signOut.disabled = true;
        try {
          accountLoadGeneration += 1;
          accountHistoryLoading = false;
          tts.stop();
          await historyStore.flushAccountWrites();
          await signOutGoogle();
          accountUser = null;
          chats = historyStore.load().map((chat) => ({
            ...chat,
            turns: (chat.turns || []).map((turn) => turn.status === "loading"
              ? { ...turn, status: "error", error: "This search was interrupted when the app was closed." }
              : turn),
          }));
          chatOwners.clear();
          for (const chat of chats) chatOwners.set(chat.id, null);
          activeChatId = chats[0]?.id || null;
          lastReadyTurn = newestReadyTurnId(chats);
          lastUsedTurnId = lastReadyTurn;
          accountMenuOpen = false;
          render();
        } catch (error) {
          signOut.disabled = false;
          setNotice(error.message || "Could not sign out. Please try again.");
        }
      });
      const historyNote = document.createElement("p");
      historyNote.className = "account-menu-copy";
      historyNote.textContent = "Your chat history is saved separately for this account. Guest chats stay on this device.";
      profile.append(identity, historyNote, signOut);
      menu.append(profile);
    } else {
      const title = document.createElement("strong");
      title.className = "account-menu-title";
      title.textContent = "Welcome to EduVibe";
      const description = document.createElement("p");
      description.className = "account-menu-copy";
      description.textContent = "Sign in or create an account with Google.";
      menu.append(title, description);
      if (accountLoading) {
        const loading = document.createElement("span");
        loading.className = "account-loading";
        loading.textContent = "Signing in with Google…";
        menu.append(loading);
      } else if (googleAuthConfig?.clientId) {
        const googleButton = document.createElement("div");
        googleButton.className = "google-signin-button";
        googleButton.setAttribute("aria-label", "Continue with Google");
        const loading = document.createElement("span");
        loading.className = "account-loading";
        loading.textContent = "Loading Google sign-in…";
        menu.append(googleButton, loading);
        renderGoogleSignInButton(googleButton, googleAuthConfig.clientId, async (credential, callbackError) => {
          if (callbackError) {
            setNotice(callbackError.message);
            return;
          }
          accountLoading = true;
          renderTopBar();
          try {
            const result = await exchangeGoogleCredential(credential);
            accountMenuOpen = false;
            await loadAccountHistory(result.user);
            accountLoading = false;
            render();
            setNotice(result.isNewAccount
              ? `Google account created. Welcome, ${accountUser.name || accountUser.email}!`
              : `Signed in as ${accountUser.email}.`);
          } catch (error) {
            accountLoading = false;
            setNotice(error.message || "Google sign-in failed. Please try again.");
          }
        }).then(() => {
          loading.remove();
        }).catch((error) => {
          loading.textContent = error.message || "Google sign-in could not be loaded.";
          console.error("Google sign-in button could not be rendered.", error);
        });
      } else {
        const setup = document.createElement("p");
        setup.className = "account-menu-copy";
        setup.textContent = googleAuthConfig
          ? "Google sign-in is not configured. Set GOOGLE_CLIENT_ID in the project .env file and restart EduVibe."
          : "Checking Google sign-in configuration…";
        menu.append(setup);
      }
    }
    topbar.element.querySelector(".topbar-actions").append(menu);
    topbar.avatar.setAttribute("aria-expanded", "true");
  }
}

function toggleTheme() {
  const currentlyDark = theme === "dark" || (!theme && window.matchMedia("(prefers-color-scheme: dark)").matches);
  theme = currentlyDark ? "light" : "dark";
  try {
    localStorage.setItem("eduvibe.theme", theme);
  } catch (error) {
    console.warn("Could not save the theme preference.", error);
  }
  document.documentElement.dataset.theme = theme;
  renderTopBar();
}

window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => {
  if (!theme) renderTopBar();
});

function render() {
  document.documentElement.dataset.theme = theme || "system";
  const host = document.querySelector(".workspace");
  if (host) {
    renderSidebar();
    renderTopBar();
    renderThread();
    const noticeNode = document.querySelector(".notice");
    if (noticeNode) {
      noticeNode.textContent = notice;
      noticeNode.hidden = !notice;
    }
    return;
  }

  root.replaceChildren();
  const topbarHost = document.createElement("div");
  topbarHost.className = "topbar-host";
  const workspace = document.createElement("div");
  workspace.className = "workspace";
  const sidebarHost = document.createElement("div");
  sidebarHost.className = "sidebar-host";
  const backdrop = document.createElement("button");
  backdrop.type = "button";
  backdrop.className = "drawer-backdrop";
  backdrop.setAttribute("aria-label", "Dismiss chat history overlay");
  backdrop.addEventListener("click", () => {
    drawerOpen = false;
    renderSidebar();
    renderTopBar();
    document.querySelector(".history-toggle-button")?.focus();
  });
  const main = document.createElement("main");
  main.className = "main-panel";
  main.setAttribute("aria-label", "EduVibe conversation");
  const thread = document.createElement("div");
  thread.className = "thread";
  thread.setAttribute("aria-live", "polite");
  thread.setAttribute("aria-relevant", "additions text");
  thread.setAttribute("role", "log");
  const empty = document.createElement("section");
  empty.className = "empty-state";
  empty.append(
    Object.assign(document.createElement("span"), { className: "empty-mark", textContent: "✦" }),
    Object.assign(document.createElement("h1"), { textContent: "What would you like to learn?" }),
    Object.assign(document.createElement("p"), { textContent: "Search a topic and explore it one narrated slide at a time." }),
  );
  const chips = document.createElement("div");
  chips.className = "example-chips";
  for (const example of examples) {
    const chip = document.createElement("button");
    chip.type = "button";
    chip.className = "example-chip";
    chip.textContent = example;
    chip.addEventListener("click", () => submitQuery(example));
    chips.append(chip);
  }
  empty.append(chips);
  const composer = Composer(submitQuery);
  const composerDock = document.createElement("div");
  composerDock.className = "composer-dock";
  composerDock.append(composer.element);
  const noticeNode = document.createElement("div");
  noticeNode.className = "notice";
  noticeNode.setAttribute("role", "status");
  noticeNode.hidden = !notice;
  noticeNode.textContent = notice;
  main.append(thread, empty, noticeNode, composerDock);
  workspace.append(sidebarHost, backdrop, main);
  root.append(topbarHost, workspace);
  document.documentElement.dataset.theme = theme || "system";
  renderSidebar();
  renderTopBar();
  renderThread();
}

async function submitQuery(query) {
  if (accountHistoryLoading) {
    setNotice("Please wait while your account chat history loads.");
    return;
  }
  tts.stop();
  let chat = activeChat();
  if (!chat) {
    chat = { id: crypto.randomUUID(), title: query.slice(0, 48), updatedAt: Date.now(), turns: [] };
    chatOwners.set(chat.id, accountUser?.email || null);
    activeChatId = chat.id;
  }
  const turn = {
    id: crypto.randomUUID(),
    query,
    lang: narrationLanguage,
    status: "loading",
    slides: [],
    currentSlide: 0,
  };
  chat.turns.push(turn);
  chat.updatedAt = Date.now();
  persistChat(chat);
  render();

  try {
    const slides = await generateSlides(query, turn.lang);
    turn.slides = slides;
    turn.status = "ready";
    turn.currentSlide = 0;
    lastUsedTurnId = turn.id;
    lastReadyTurn = turn.id;
  } catch (error) {
    turn.status = "error";
    turn.error = error.message || "Something went wrong while generating slides.";
  }
  chat.updatedAt = Date.now();
  persistChat(chat);
  if (activeChatId === chat.id) render();
}

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") {
    let shouldRestoreHistoryFocus = false;
    if (accountMenuOpen) {
      accountMenuOpen = false;
    }
    if (drawerOpen) {
      drawerOpen = false;
      renderSidebar();
      shouldRestoreHistoryFocus = true;
    }
    renderTopBar();
    if (shouldRestoreHistoryFocus) document.querySelector(".history-toggle-button")?.focus();
    return;
  }
  const target = event.target;
  if (target instanceof HTMLElement && (
    target.isContentEditable
    || target.closest("input, textarea, button, a, select, [role='menu']")
  )) return;

  const found = lastUsedTurnId ? findTurn(lastUsedTurnId) : null;
  if (!found || found.turn.status !== "ready") return;
  const index = found.turn.currentSlide || 0;
  if (event.key === "ArrowRight" || event.key === "ArrowLeft") {
    event.preventDefault();
    const next = Math.max(0, Math.min(found.turn.slides.length - 1, index + (event.key === "ArrowRight" ? 1 : -1)));
    if (next !== index) {
      found.turn.currentSlide = next;
      persistChat(found.chat);
      if (tts.isPlaying(found.turn.id)) tts.playTurn(found.turn, next, (slideIndex) => {
        found.turn.currentSlide = slideIndex;
        persistChat(found.chat);
        if (activeChatId === found.chat.id) render();
      });
      if (activeChatId === found.chat.id) render();
    }
  } else if (event.code === "Space") {
    event.preventDefault();
    if (tts.isActive(found.turn.id)) tts.toggle(found.turn.id);
    else tts.playTurn(found.turn, index, (slideIndex) => {
      found.turn.currentSlide = slideIndex;
      persistChat(found.chat);
      if (activeChatId === found.chat.id) render();
    });
  }
});

render();
restoreAccount();
