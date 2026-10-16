export function Composer(onSubmit) {
  const form = document.createElement("form");
  form.className = "composer";
  const label = document.createElement("label");
  label.className = "sr-only";
  label.htmlFor = "slide-search-input";
  label.textContent = "Search a topic";
  const textarea = document.createElement("textarea");
  textarea.id = "slide-search-input";
  textarea.rows = 1;
  textarea.maxLength = 4000;
  textarea.placeholder = "Ask anything to start learning…";
  textarea.setAttribute("aria-describedby", "composer-hint");

  const send = document.createElement("button");
  send.className = "send-button";
  send.type = "submit";
  send.setAttribute("aria-label", "Send search");
  send.title = "Send search";
  send.textContent = "↑";

  const hint = document.createElement("span");
  hint.className = "composer-hint";
  hint.id = "composer-hint";
  hint.textContent = "Enter to send · Shift + Enter for a new line";

  const resize = () => {
    textarea.style.height = "auto";
    textarea.style.height = `${Math.min(textarea.scrollHeight, 180)}px`;
  };
  textarea.addEventListener("input", resize);
  textarea.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      form.requestSubmit();
    }
  });
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const value = textarea.value.trim();
    if (!value) return;
    textarea.value = "";
    resize();
    onSubmit(value);
  });
  form.append(label, textarea, send, hint);
  return { element: form, input: textarea, send };
}
