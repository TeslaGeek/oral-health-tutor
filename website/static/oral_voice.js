(function () {
  let mode = "text";
  let recognition = null;
  let listening = false;

  function setMode(newMode) {
    mode = newMode;
    window.ORAL_INPUT_MODE = newMode;

    if (mode === "text" && recognition && listening) {
      try { recognition.stop(); } catch (e) {}
    }

    const textBtn = document.getElementById("mode-text");
    const voiceBtn = document.getElementById("mode-voice");
    if (textBtn && voiceBtn) {
      textBtn.className = mode === "text" ? "btn btn-primary btn-sm" : "btn btn-outline-primary btn-sm";
      voiceBtn.className = mode === "voice" ? "btn btn-primary btn-sm" : "btn btn-outline-primary btn-sm";
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

        if (status) status.textContent = `Heard: "${transcript}"`;

        listening = false;
        if (btn) btn.textContent = "🎤 Push to talk";

        await chat.send(transcript, { source: "voice" });

        if (status) status.textContent = "Voice idle";
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
      try { recognition.stop(); } catch (e) {}
    }
  }

  document.addEventListener("DOMContentLoaded", () => {
    const textBtn = document.getElementById("mode-text");
    const voiceBtn = document.getElementById("mode-voice");
    const micBtn = document.getElementById("voice-btn");

    if (textBtn) textBtn.addEventListener("click", () => setMode("text"));
    if (voiceBtn) voiceBtn.addEventListener("click", () => setMode("voice"));
    if (micBtn) micBtn.addEventListener("click", toggleVoice);

    setMode("text");
  });
})();
