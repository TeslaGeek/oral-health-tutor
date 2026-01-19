(function () {
  if (window.__ORAL_CHAT_INITED) return;
  window.__ORAL_CHAT_INITED = true;

  function onReady(fn) {
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", fn);
    } else {
      fn();
    }
  }

  const cfg = (window.getOralConfig && window.getOralConfig()) || {};

  function getCsrfToken() {
    const el = document.querySelector('meta[name="csrf-token"]');
    return el ? el.getAttribute('content') : '';
  }

  let currentAudio = null;

  function isVoiceModeEnabled() {
    return (window.ORAL_INPUT_MODE || "text") === "voice";
  }

  async function playPatientAudio(text) {
    const endpoint = cfg.ttsEndpoint || window.ORAL_TTS_ENDPOINT;
    if (!endpoint) return;

    try {
      if (currentAudio) {
        currentAudio.pause();
        currentAudio.src = "";
        currentAudio = null;
      }
    } catch (e) {}

    const payload = {
      text,
      voice: cfg.ttsVoice || window.ORAL_TTS_VOICE || "marin",
    };
    if (cfg.ttsModel || window.ORAL_TTS_MODEL) {
      payload.model = cfg.ttsModel || window.ORAL_TTS_MODEL;
    }
    if (cfg.ttsInstructions || window.ORAL_TTS_INSTRUCTIONS) {
      payload.instructions = cfg.ttsInstructions || window.ORAL_TTS_INSTRUCTIONS;
    }

    console.log("TTS -> endpoint:", endpoint);
    console.log("TTS -> payload:", payload);
    console.log("TTS -> mode enabled:", isVoiceModeEnabled());

    const resp = await fetch(endpoint, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": getCsrfToken(),
        "X-CSRF-Token": getCsrfToken(),
      },
      body: JSON.stringify(payload),
    });

    if (!resp.ok) {
      console.warn("TTS request failed", resp.status);
      return;
    }

    const blob = await resp.blob();
    const url = URL.createObjectURL(blob);

    const audio = new Audio(url);
    currentAudio = audio;
    audio.onended = () => {
      URL.revokeObjectURL(url);
      if (currentAudio === audio) currentAudio = null;
    };
    audio.onerror = () => {
      URL.revokeObjectURL(url);
      if (currentAudio === audio) currentAudio = null;
    };

    try {
      await audio.play();
    } catch (e) {
      console.warn("Autoplay blocked (user gesture required).");
    }
  }

  function getLogEl() {
    return document.getElementById("chat-log");
  }

  function appendChat(role, text, meta) {
    const log = getLogEl();
    if (!log) return;

    const div = document.createElement("div");
    div.className = "mb-2";
    div.dataset.role = role;

    if (meta && meta.source) {
      div.dataset.source = meta.source;
    }

    const label = document.createElement("strong");
    label.textContent = (role === "user" ? "Student" : "Patient") + ": ";

    const span = document.createElement("span");
    span.textContent = text;

    div.appendChild(label);
    div.appendChild(span);
    log.appendChild(div);
    log.scrollTop = log.scrollHeight;
  }

  function setTyping(show) {
    const indicator = document.getElementById("typing-indicator");
    if (!indicator) return;
    indicator.style.display = show ? "block" : "none";
  }

  async function postChatMessage(message, opts) {
    const chatPostUrl = cfg.chatPostUrl || window.ORAL_CHAT_POST_URL;
    const phase = cfg.currentPhase || window.ORAL_CURRENT_PHASE || 1;
    if (!chatPostUrl) {
      console.error("ORAL_CHAT_POST_URL not set");
      return { ok: false, error: "Chat not configured" };
    }

    const payload = {
      message,
      phase,
      ...(opts || {}),
    };

    const resp = await fetch(chatPostUrl, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": getCsrfToken(),
        "X-CSRF-Token": getCsrfToken(),
      },
      body: JSON.stringify(payload),
    });

    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) {
      return { ok: false, error: data.error || "Request failed" };
    }
    return data;
  }

  async function send(message, opts) {
    const sendBtn = document.getElementById("chat-send");
    const micBtn = document.getElementById("voice-btn");

    appendChat("user", message, { source: (opts && opts.source) || "text" });

    if (sendBtn) sendBtn.disabled = true;
    if (micBtn) micBtn.disabled = true;
    setTyping(true);

    try {
      const data = await postChatMessage(message, opts);
      if (data.ok) {
        appendChat("assistant", data.reply, { source: "assistant" });
        if (isVoiceModeEnabled()) {
          try {
            await playPatientAudio(data.reply);
          } catch (e) {}
        }
      } else {
        appendChat("assistant", "Sorry — something went wrong: " + (data.error || "unknown error"));
      }
      return data;
    } catch (e) {
      appendChat("assistant", "Sorry — network error.");
      return { ok: false, error: "network error" };
    } finally {
      setTyping(false);
      if (sendBtn) sendBtn.disabled = false;
      if (micBtn) micBtn.disabled = false;
    }
  }

  async function sendChatFromInput() {
    const input = document.getElementById("chat-input");
    if (!input) return;

    const msg = (input.value || "").trim();
    if (!msg) return;

    input.value = "";
    await send(msg, { source: "text" });
    input.focus();
  }

  // Expose a small API for voice to reuse
  window.OralChat = {
    appendChat,
    setTyping,
    postChatMessage,
    send,
    sendChatFromInput,
  };

  onReady(() => {
    const log = getLogEl();
    if (log) log.scrollTop = log.scrollHeight;

    const sendBtn = document.getElementById("chat-send");
    if (sendBtn) sendBtn.addEventListener("click", sendChatFromInput);

    const chatInput = document.getElementById("chat-input");
    if (chatInput) {
      chatInput.addEventListener("keydown", (e) => {
        if (e.key === "Enter") {
          e.preventDefault();
          sendChatFromInput();
        }
      });
    }
  });
})();
