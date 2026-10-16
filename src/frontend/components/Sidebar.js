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

export function Sidebar(chats, activeId, { onNewChat, onOpenChat, onDeleteChat }) {
  const aside = document.createElement("aside");
  aside.className = "sidebar";
  aside.setAttribute("aria-label", "Chat history");

  const newChat = document.createElement("button");
  newChat.type = "button";
  newChat.className = "new-chat-button";
  newChat.append(document.createTextNode("+  New chat"));
  newChat.addEventListener("click", onNewChat);
  aside.append(newChat);

  const heading = document.createElement("h2");
  heading.className = "history-heading";
  heading.textContent = "History";
  aside.append(heading);
  const list = document.createElement("div");
  list.className = "history-list";
  list.setAttribute("role", "list");
  for (const chat of chats) {
    const row = document.createElement("div");
    row.className = `history-row${chat.id === activeId ? " active" : ""}`;
    row.setAttribute("role", "listitem");
    const open = document.createElement("button");
    open.type = "button";
    open.className = "history-open";
    open.textContent = chat.title || "New conversation";
    open.setAttribute("aria-label", `Open chat: ${chat.title || "New conversation"}`);
    open.addEventListener("click", () => onOpenChat(chat.id));
    const remove = iconButton("Delete chat", "×", "delete-chat-button", () => onDeleteChat(chat.id));
    row.append(open, remove);
    list.append(row);
  }
  if (!chats.length) {
    const empty = document.createElement("p");
    empty.className = "history-empty";
    empty.textContent = "Your chats will appear here.";
    list.append(empty);
  }
  aside.append(list);
  return aside;
}
