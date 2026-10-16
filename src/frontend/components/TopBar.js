function iconButton(label, symbol, className, onClick) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = className;
  button.setAttribute("aria-label", label);
  button.title = label;
  button.textContent = symbol;
  button.addEventListener("click", onClick);
  return button;
}

export function TopBar({
  hasSlides,
  user,
  narrationLanguage,
  sidebarOpen,
  theme,
  onDownload,
  downloadBusy,
  onNarrationLanguageChange,
  onToggleAccount,
  onToggleTheme,
  onToggleSidebar,
}) {
  const header = document.createElement("header");
  header.className = "topbar";
  const left = document.createElement("div");
  left.className = "topbar-brand";
  const sidebarToggle = iconButton(
    sidebarOpen ? "Close chat history" : "Open chat history",
    sidebarOpen ? "×" : "☰",
    "history-toggle-button",
    onToggleSidebar,
  );
  sidebarToggle.setAttribute("aria-expanded", String(sidebarOpen));
  sidebarToggle.setAttribute("aria-controls", "chat-history-drawer");
  left.append(sidebarToggle);
  const isDark = theme === "dark" || (!theme && window.matchMedia("(prefers-color-scheme: dark)").matches);
  const brandLogo = document.createElement("img");
  brandLogo.className = "brand-logo";
  brandLogo.src = isDark ? "/assets/eduvibe-dark.png" : "/assets/eduvibe-light.png";
  brandLogo.alt = "EduVibe";
  left.append(brandLogo);

  const right = document.createElement("div");
  right.className = "topbar-actions";
  const languageSwitch = document.createElement("select");
  languageSwitch.className = "language-switch";
  languageSwitch.setAttribute("aria-label", "Narration language");
  languageSwitch.title = "Choose narration language";
  for (const [value, label] of [["en", "EN"], ["hi", "हिंदी"]]) {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = label;
    option.selected = narrationLanguage === value;
    languageSwitch.append(option);
  }
  languageSwitch.addEventListener("change", () => onNarrationLanguageChange(languageSwitch.value));

  const themeButton = iconButton(
    isDark ? "Switch to light mode" : "Switch to dark mode",
    isDark ? "☀" : "☾",
    "theme-button",
    onToggleTheme,
  );
  const download = iconButton(
    downloadBusy ? "Preparing PowerPoint presentation" : "Download all slides as PowerPoint",
    "",
    "download-button",
    onDownload,
  );
  download.append(icon("download"));
  download.disabled = !hasSlides || downloadBusy;
  download.setAttribute("aria-disabled", String(download.disabled));
  const avatar = iconButton(
    user ? `Google account: ${user.name || user.email}` : "Sign in or sign up with Google",
    user ? (user.name || user.email || "G").charAt(0).toUpperCase() : "G",
    "avatar-button",
    onToggleAccount,
  );
  if (user?.picture) {
    const picture = document.createElement("img");
    picture.src = user.picture;
    picture.alt = "";
    picture.referrerPolicy = "no-referrer";
    avatar.replaceChildren(picture);
  }
  avatar.setAttribute("aria-expanded", "false");
  avatar.setAttribute("aria-haspopup", "dialog");
  right.append(languageSwitch, themeButton, download, avatar);
  header.append(left, right);
  return { element: header, avatar, sidebarToggle };
}

function icon(name) {
  const namespace = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(namespace, "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("aria-hidden", "true");
  svg.setAttribute("focusable", "false");
  const paths = name === "download"
    ? [
      ["path", "M12 3v11m0 0 4-4m-4 4-4-4"],
      ["path", "M5 16v4h14v-4"],
    ]
    : [];
  for (const [tag, d] of paths) {
    const path = document.createElementNS(namespace, tag);
    path.setAttribute("d", d);
    path.setAttribute("fill", "none");
    path.setAttribute("stroke", "currentColor");
    path.setAttribute("stroke-width", "1.8");
    path.setAttribute("stroke-linecap", "round");
    path.setAttribute("stroke-linejoin", "round");
    svg.append(path);
  }
  return svg;
}
