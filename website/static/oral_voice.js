(function () {
  if (window.__ORAL_VOICE_INITED) return;
  window.__ORAL_VOICE_INITED = true;

  function onReady(fn) {
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", fn);
    } else {
      fn();
    }
  }

  const cfg = (window.getOralConfig && window.getOralConfig()) || {};
  const ttsEndpoint = cfg.ttsEndpoint || window.ORAL_TTS_ENDPOINT;

  let mode = "text";
  let recognition = null;
  let listening = false;
  let stopTimer = null;
  let lastTranscript = "";

  function setMode(newMode) {
    mode = newMode;
    window.ORAL_INPUT_MODE = newMode;

    if (mode === "text" && recognition && listening) {
      try { recognition.stop(); } catch (e) {}
    }

    const textBtn = document.getElementById("mode-text");
    const voiceBtn = document.getElementById("mode-voice");
    if (textBtn && voiceBtn) {
      textBtn.className = mode === "text"
        ? "btn btn-primary btn-sm oral-toggle"
        : "btn btn-outline-dark btn-sm oral-toggle";
      voiceBtn.className = mode === "voice"
        ? "btn btn-primary btn-sm oral-toggle"
        : "btn btn-outline-dark btn-sm oral-toggle";
    }

    const micBtn = document.getElementById("voice-btn");
    const status = document.getElementById("voice-status");
    if (micBtn) micBtn.style.display = mode === "voice" ? "inline-block" : "none";
    if (status) status.style.display = mode === "voice" ? "block" : "none";

    const textControls = document.getElementById("text-chat-controls");
    if (textControls) textControls.style.display = mode === "voice" ? "none" : "flex";

    if (status && mode === "voice") status.textContent = "Voice idle";
    if (micBtn && mode === "voice") micBtn.textContent = "🎤 Push to talk";
  }

  function initRecognition() {
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SR) return null;

    const r = new SR();
    r.lang = "en-GB";
    r.continuous = true;
    r.interimResults = false;
    r.maxAlternatives = 1;
    return r;
  }

  async function toggleVoice() {
    const status = document.getElementById("voice-status");
    const btn = document.getElementById("voice-btn");
    const chat = window.OralChat;

    if (!chat || typeof chat.send !== "function") {
      if (status) status.textContent = "Chat not ready yet.";
      return;
    }

    if (!recognition) {
      recognition = initRecognition();
      if (!recognition) {
        if (status) status.textContent = "Voice not supported in this browser.";
        return;
      }

      recognition.onresult = async (e) => {
        const transcript = (e.results?.[0]?.[0]?.transcript || "").trim();
        if (!transcript) return;

        lastTranscript = transcript;
        if (status) status.textContent = `Heard: "${transcript}"`;

        if (stopTimer) {
          clearTimeout(stopTimer);
        }
        stopTimer = setTimeout(async () => {
          listening = false;
          if (btn) btn.textContent = "🎤 Push to talk";
          try { recognition.stop(); } catch (e) {}
          await chat.send(lastTranscript, { source: "voice" });
          if (status) status.textContent = "Voice idle";
          stopTimer = null;
          lastTranscript = "";
        }, 200);
      };

      recognition.onerror = (e) => {
        listening = false;
        if (btn) btn.textContent = "🎤 Push to talk";
        if (status) status.textContent = "Voice error: " + (e.error || "unknown");
      };

      recognition.onend = () => {
        listening = false;
        if (btn) btn.textContent = "🎤 Push to talk";
        if (status) status.textContent = "Voice idle";
      };
    }

    if (!listening) {
      listening = true;
      if (btn) btn.textContent = "🎤 Listening… (click to stop)";
      if (status) status.textContent = "Listening…";
      try {
        recognition.start();
      } catch (e) {
        listening = false;
        if (btn) btn.textContent = "🎤 Push to talk";
        if (status) status.textContent = "Voice busy — try again.";
      }
    } else {
      if (stopTimer) {
        clearTimeout(stopTimer);
        stopTimer = null;
        lastTranscript = "";
      }
      try { recognition.stop(); } catch (e) {}
    }
  }

  onReady(() => {
    const textBtn = document.getElementById("mode-text");
    const voiceBtn = document.getElementById("mode-voice");
    const micBtn = document.getElementById("voice-btn");
    const status = document.getElementById("voice-status");

    if (!textBtn || !voiceBtn || !micBtn) return;
    if (!ttsEndpoint) {
      voiceBtn.disabled = true;
      voiceBtn.title = "Voice is unavailable (TTS endpoint not configured).";
      if (status) status.textContent = "Voice unavailable.";
      return;
    }

    if (textBtn) textBtn.addEventListener("click", () => setMode("text"));
    if (voiceBtn) voiceBtn.addEventListener("click", () => setMode("voice"));
    if (micBtn) micBtn.addEventListener("click", toggleVoice);

    setMode("text");
  });
})();
