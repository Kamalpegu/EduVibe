export async function generateSlides(query, narrationLanguage = "en") {
  const response = await fetch("/api/generate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query, lang: narrationLanguage }),
  });

  if (!response.ok) {
    let message = `Slide generation failed (${response.status}).`;
    try {
      const body = await response.json();
      message = body.detail || message;
    } catch (error) {
      console.warn("Could not read the slide-generation error response.", error);
    }
    throw new Error(message);
  }

  const slides = await response.json();
  if (!Array.isArray(slides) || slides.length === 0) {
    throw new Error("The server returned no slides. Please try a different search.");
  }

  return slides.map((slide) => ({
    title: String(slide.title || "Untitled slide"),
    bullets: Array.isArray(slide.bullets) ? slide.bullets.map(String) : [],
    say: String(slide.say || slide.title || ""),
    language: narrationLanguage === "hi" ? "hi-IN" : "en-US",
    audioUrl: slide.audioUrl ? String(slide.audioUrl) : undefined,
    svgUrl: slide.svgUrl ? String(slide.svgUrl) : undefined,
  }));
}
