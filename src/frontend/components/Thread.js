import { Turn } from "./Turn.js";

export function Thread(container, chat, callbacks) {
  for (const child of container.children) {
    child.querySelector(".audio-card")?._unsubscribe?.();
  }
  container.replaceChildren();
  if (!chat?.turns?.length) return;
  const fragment = document.createDocumentFragment();
  for (const turn of chat.turns) {
    fragment.append(Turn(
      turn,
      (index) => callbacks.onSlideChange(chat.id, turn.id, index),
      callbacks.onUseTurn,
      () => callbacks.onDownload(turn),
    ));
  }
  container.append(fragment);
  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  requestAnimationFrame(() => container.scrollTo({
    top: container.scrollHeight,
    behavior: reducedMotion ? "auto" : "smooth",
  }));
}
