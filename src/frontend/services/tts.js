class BrowserTTS {
  constructor() {
    this.active = null;
    this.listeners = new Set();
  }

  subscribe(listener) {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  isPlaying(turnId) {
    return this.active?.turnId === turnId && !this.active.paused;
  }

  isActive(turnId) {
    return this.active?.turnId === turnId;
  }

  isSeekable(turnId) {
    return this.isActive(turnId)
      && Boolean(this.active.audio)
      && Number.isFinite(this.active.audio.duration)
      && this.active.audio.duration > 0;
  }

  snapshot(turnId) {
    if (!this.isActive(turnId)) return { playing: false, progress: 0 };
    return {
      playing: !this.active.paused,
      progress: this.active.duration
        ? Math.min(1, this.active.currentTime / this.active.duration)
        : 0,
    };
  }

  emit() {
    for (const listener of this.listeners) {
      listener(this.active?.turnId || null, Boolean(this.active && !this.active.paused));
    }
  }

  stop(turnId) {
    if (!this.active || (turnId && this.active.turnId !== turnId)) return;
    const active = this.active;
    this.active = null;
    if (active.audio) {
      active.audio.pause();
      try {
        active.audio.currentTime = 0;
      } catch (error) {
        console.warn("Could not reset slide audio.", error);
      }
      active.audio.onended = null;
      active.audio.ontimeupdate = null;
      active.audio.onerror = null;
    }
    this.emit();
  }

  toggle(turnId) {
    if (!this.isActive(turnId)) return;
    const active = this.active;
    if (active.paused) {
      active.paused = false;
      if (active.audio) active.audio.play().catch((error) => {
        this.fail(active, error);
      });
    } else {
      active.paused = true;
      if (active.audio) active.audio.pause();
    }
    this.emit();
  }

  playTurn(turn, slideIndex, onSlideChange) {
    const playAt = (index) => {
      if (index >= turn.slides.length) return;
      this.play(turn.id, turn.slides[index], () => {
        const next = index + 1;
        if (next < turn.slides.length) {
          onSlideChange(next);
          playAt(next);
        }
      });
    };
    playAt(slideIndex);
  }

  play(turnId, slide, onEnded) {
    this.stop();
    const active = {
      turnId,
      onEnded,
      audio: null,
      currentTime: 0,
      duration: 0,
      paused: false,
    };
    this.active = active;
    this.emit();

    const finish = () => {
      if (this.active !== active || active.paused) return;
      this.active = null;
      this.emit();
      onEnded();
    };

    this.createAudio(active, slide, finish);
  }

  async createAudio(active, slide, finish) {
    try {
      let audio;
      if (slide.audioUrl) {
        audio = new Audio(slide.audioUrl);
      } else {
        const puter = globalThis.puter;
        if (typeof puter?.ai?.txt2speech !== "function") {
          throw new Error("Puter TTS did not load. Check your internet connection and reload EduVibe.");
        }
        if (slide.say.length >= 3000) {
          throw new Error("Puter supports fewer than 3,000 characters per narration. Try a shorter topic.");
        }
        const language = slide.language === "hi-IN"
          ? { language: "hi-IN", voice: "Aditi" }
          : { language: "en-US", voice: "Joanna" };
        audio = await puter.ai.txt2speech(slide.say, {
          provider: "aws-polly",
          ...language,
        });
      }

      if (this.active !== active) {
        audio.pause();
        return;
      }
      active.audio = audio;
      audio.onended = finish;
      audio.ontimeupdate = () => {
        if (this.active !== active) return;
        active.currentTime = audio.currentTime || 0;
        active.duration = Number.isFinite(audio.duration) ? audio.duration : 0;
        this.emit();
      };
      audio.onerror = () => this.fail(active, new Error("The generated narration audio could not be loaded."));
      this.emit();
      if (!active.paused) await audio.play();
    } catch (error) {
      this.fail(active, error);
    }
  }

  fail(active, error) {
    if (this.active !== active) return;
    console.error("Could not play Puter narration.", error);
    this.stop(active.turnId);
    const code = error?.error?.code;
    const message = code === "auth_canceled"
      ? "Puter sign-in was canceled. Complete sign-in in the Puter prompt and try again."
      : error?.error?.message || error?.message || "Puter could not generate narration. Please try again.";
    window.dispatchEvent(new CustomEvent("eduvibe:tts-error", { detail: { message } }));
  }

  seek(turnId, progress) {
    if (!this.isSeekable(turnId)) return;
    const active = this.active;
    active.audio.currentTime = active.audio.duration * progress;
  }
}

export const tts = new BrowserTTS();
