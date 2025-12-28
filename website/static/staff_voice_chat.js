(() => {
  const VERBOSE_LOG = false;
  if (VERBOSE_LOG) {
    console.info("[voice-chat] staff_voice_chat.js loaded");
  }
  const config = window.PATIENT_VOICE_CONFIG || {};

  function $(id) {
    return document.getElementById(id);
  }

  const startBtn = $("voice-start");
  const stopBtn = $("voice-stop");
  const muteBtn = $("voice-mute");
  const statusBadge = $("voice-status");
  const audioEl = $("voice-remote-audio");
  const logEl = $("voice-log");
  const errorEl = $("voice-error");
  const selectEl = $("voice-patient-select");
  const nameEl = $("voice-patient-name");
  const personaDefaultEl = $("voice-patient-persona-default");
  const dobEl = $("voice-patient-dob");
  const addressEl = $("voice-patient-address");
  const rxEl = $("voice-patient-rx");
  const imageEl = $("voice-patient-image");
  const videoEl = $("voice-patient-video");
  const personaInput = $("voice-patient-persona-input");

  if (!startBtn || !statusBadge) {
    return;
  }

  const csrfNode = document.querySelector('meta[name="csrf-token"]');
  const CSRF = csrfNode ? csrfNode.getAttribute("content") : "";

  let pc = null;
  let dc = null;
  let localStream = null;
  let remoteStream = null;
  let isMuted = false;
  let assistantBuffer = "";
  let assistantNode = null;
  let userBuffer = "";
  let userNode = null;
  let recognition = null;
  let recognitionActive = false;
  let assistantLastCommitted = "";
  let lastAssistantRendered = "";
  let lastUserRendered = "";
  const patients = Array.isArray(config.patients) ? config.patients : [];
  let selectedPatientId = config.default_patient_id || (patients[0] && patients[0].patient_id) || null;

  function getPatient(pid) {
    return patients.find((p) => p.patient_id === pid);
  }

  if (personaInput) {
    personaInput.dataset.userEdited = "false";
    personaInput.addEventListener("input", () => {
      personaInput.dataset.userEdited = "true";
    });
  }

  function renderPatientDetails(pid) {
    const patient = getPatient(pid) || {};

    if (nameEl) nameEl.textContent = patient.name || "Unknown patient";
    const defaultPersona = patient.default_persona || patient.persona || "";
    if (personaDefaultEl) {
      personaDefaultEl.textContent = defaultPersona;
    }
    if (personaInput) {
      personaInput.dataset.userEdited = "false";
      personaInput.value = "";
      personaInput.placeholder = defaultPersona
        ? "Leave blank if you want the default persona shown above."
        : "Describe the patient persona";
      personaInput.dataset.defaultPersona = defaultPersona;
    }
    if (dobEl) dobEl.textContent = patient.dob || "—";
    if (addressEl) addressEl.textContent = patient.address || "—";
    if (rxEl) rxEl.textContent = patient.previous_rx || "—";
    const hasVideo = !!(patient.video_mp4 || patient.video_webm);
    if (videoEl) {
      if (hasVideo) {
        const sources = [];
        if (patient.video_mp4) {
          sources.push(`<source src="${patient.video_mp4}" type="video/mp4">`);
        }
        if (patient.video_webm) {
          sources.push(`<source src="${patient.video_webm}" type="video/webm">`);
        }
        videoEl.innerHTML = sources.join("");
        if (patient.image) {
          videoEl.setAttribute("poster", patient.image);
        } else {
          videoEl.removeAttribute("poster");
        }
        videoEl.classList.remove("d-none");
        try {
          videoEl.load();
          videoEl.play().catch(() => {});
        } catch (err) {
          if (VERBOSE_LOG) console.warn("[voice-chat] video playback issue", err);
        }
      } else {
        try { videoEl.pause(); } catch (_) {}
        videoEl.innerHTML = "";
        videoEl.removeAttribute("poster");
        videoEl.classList.add("d-none");
      }
    }
    if (imageEl) {
      if (!hasVideo && patient.image) {
        imageEl.src = patient.image;
        imageEl.alt = patient.name || "Patient";
        imageEl.classList.remove("d-none");
      } else if (!hasVideo) {
        imageEl.src = "";
        imageEl.alt = "";
        imageEl.classList.add("d-none");
      } else {
        imageEl.src = patient.image || "";
        imageEl.alt = patient.name || "Patient";
        imageEl.classList.add("d-none");
      }
    }
  }

  if (selectEl) {
    if (selectedPatientId !== null) {
      selectEl.value = String(selectedPatientId);
      if (personaInput) personaInput.dataset.userEdited = "false";
      renderPatientDetails(selectedPatientId);
    }
    selectEl.addEventListener("change", () => {
      const val = parseInt(selectEl.value, 10);
      if (!Number.isNaN(val)) {
        selectedPatientId = val;
        if (personaInput) personaInput.dataset.userEdited = "false";
        renderPatientDetails(selectedPatientId);
        if (!pc) {
          finalizeAssistantTranscript();
          finalizeUserTranscript();
          resetTranscript();
        }
      }
    });
  } else {
    if (personaInput) personaInput.dataset.userEdited = "false";
    renderPatientDetails(selectedPatientId);
  }

  function extractTextFromParts(parts) {
    const out = [];
    (parts || []).forEach((part) => {
      if (!part) return;
      if (typeof part === "string") {
        out.push(part);
        return;
      }
      if (part.text) {
        out.push(part.text);
        return;
      }
      if (part.transcript) {
        out.push(part.transcript);
        return;
      }
      if (Array.isArray(part.output_text)) {
        out.push(part.output_text.join(" "));
        return;
      }
      if (Array.isArray(part.arguments)) {
        out.push(part.arguments.join(" "));
        return;
      }
      if (part.type === "output_text" && part.text) {
        out.push(part.text);
        return;
      }
      if (part.type === "input_text" && part.text) {
        out.push(part.text);
        return;
      }
      if (part.type === "output_audio" && part.transcript) {
        out.push(part.transcript);
        return;
      }
      if (part.type === "input_audio_transcription" && part.transcript) {
        out.push(part.transcript);
      }
    });
    return out.join(" ").trim();
  }

  function setStatus(label, variant) {
    statusBadge.textContent = label;
    statusBadge.className = `badge badge-${variant}`;
  }

  function showError(message) {
    if (!errorEl) return;
    errorEl.textContent = message;
    errorEl.classList.remove("d-none");
  }

  function clearError() {
    if (!errorEl) return;
    errorEl.textContent = "";
    errorEl.classList.add("d-none");
  }

  function resetTranscript() {
    if (logEl) {
      logEl.innerHTML = '<p class="text-muted small mb-0">Transcript will appear here during the call.</p>';
      logEl.dataset.hasTranscript = "false";
    }
    assistantBuffer = "";
    assistantNode = null;
    userBuffer = "";
    userNode = null;
    assistantLastCommitted = "";
    lastAssistantRendered = "";
    lastUserRendered = "";
  }

  function appendTranscript(text, role) {
    if (!logEl) return null;
    if (!text) return null;
    const trimmed = text.trim();
    if (!trimmed) {
      return null;
    }
    if (logEl.dataset.hasTranscript !== "true") {
      logEl.innerHTML = "";
      logEl.dataset.hasTranscript = "true";
    }
    if (role === "assistant" && trimmed === lastAssistantRendered) {
      if (assistantNode) {
        assistantNode.textContent = trimmed;
      }
      return assistantNode;
    }
    if (role === "user") {
      if (trimmed === lastUserRendered) {
        if (userNode) {
          userNode.textContent = trimmed;
        }
        return userNode;
      }
      if (assistantLastCommitted && trimmed.toLowerCase() === assistantLastCommitted.toLowerCase()) {
        return null;
      }
    }
    const p = document.createElement("p");
    p.className = `voice-line mb-2 voice-line-${role}`;
    p.textContent = trimmed;
    logEl.appendChild(p);
    logEl.scrollTop = logEl.scrollHeight;
    if (role === "assistant") {
      lastAssistantRendered = trimmed;
    } else if (role === "user") {
      lastUserRendered = trimmed;
    }
    return p;
  }

  function updateAssistantTranscript(delta) {
    assistantBuffer += delta || "";
    const text = assistantBuffer.trim();
    if (!text) {
      return;
    }
    if (!assistantNode) {
      assistantNode = appendTranscript(text, "assistant");
    } else if (assistantNode) {
      assistantNode.textContent = text;
      lastAssistantRendered = text;
    }
  }

  function finalizeAssistantTranscript(finalText) {
    const text = (finalText || assistantBuffer).trim();
    if (text && text !== assistantLastCommitted) {
      if (!assistantNode) {
        assistantNode = appendTranscript(text, "assistant");
      } else {
        assistantNode.textContent = text;
      }
      assistantLastCommitted = text;
      lastAssistantRendered = text;
    }
    assistantBuffer = "";
    assistantNode = null;
  }

  function updateUserTranscript(delta) {
    userBuffer += delta || "";
    const text = userBuffer.trim();
    if (!text) {
      return;
    }
    if (assistantLastCommitted && text.toLowerCase() === assistantLastCommitted.toLowerCase()) {
      return;
    }
    if (!userNode) {
      userNode = appendTranscript(text, "user");
    } else if (userNode) {
      userNode.textContent = text;
      lastUserRendered = text;
    }
  }

  function finalizeUserTranscript() {
    userBuffer = "";
    userNode = null;
  }

  function startSpeechRecognition() {
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRecognition) {
      console.warn("[voice-chat] Browser speech recognition API not available");
      return;
    }
    if (recognitionActive) {
      return;
    }

    recognition = new SpeechRecognition();
    recognition.lang = "en-GB";
    recognition.continuous = true;
    recognition.interimResults = true;

    recognition.onstart = () => {
      recognitionActive = true;
      if (VERBOSE_LOG) {
        console.debug("[voice-chat] Speech recognition started");
      }
    };

    recognition.onerror = (event) => {
      console.warn("[voice-chat] Speech recognition error", event.error);
    };

    recognition.onend = () => {
      if (VERBOSE_LOG) {
        console.debug("[voice-chat] Speech recognition ended");
      }
      recognitionActive = false;
      if (pc && pc.connectionState === "connected") {
        try {
          recognition.start();
        } catch (err) {
          console.warn("[voice-chat] Restarting speech recognition failed", err);
        }
      }
    };

    recognition.onresult = (event) => {
      let interimText = "";
      let finalText = "";

      for (let i = event.resultIndex; i < event.results.length; i++) {
        const result = event.results[i];
        const transcript = (result[0]?.transcript || "").trim();
        if (!transcript) continue;

        if (result.isFinal) {
          finalText += transcript + " ";
        } else {
          interimText += transcript + " ";
        }
      }

      if (interimText) {
        const text = interimText.trim();
        if (text) {
          userBuffer = text;
          if (!userNode) {
            userNode = appendTranscript(text, "user");
          } else {
            userNode.textContent = text;
          }
        }
      }

      if (finalText) {
        const text = finalText.trim();
        if (text) {
          appendTranscript(text, "user");
        }
        userBuffer = "";
        if (userNode) {
          try {
            userNode.remove();
          } catch (_) {
            userNode.textContent = "";
          }
        }
        userNode = null;
      }
    };

    try {
      recognition.start();
    } catch (err) {
      console.warn("[voice-chat] Speech recognition start failed", err);
    }
  }

  function stopSpeechRecognition() {
    if (recognition) {
      try {
        recognition.onend = null;
        recognition.stop();
      } catch (_) {
        /* no-op */
      }
    }
    recognition = null;
    recognitionActive = false;
  }

  function resetState() {
    if (dc) {
      try { dc.close(); } catch (_) {}
      dc = null;
    }
    if (pc) {
      try { pc.close(); } catch (_) {}
      pc = null;
    }
    if (localStream) {
      localStream.getTracks().forEach(track => track.stop());
      localStream = null;
    }
    if (remoteStream) {
      remoteStream.getTracks().forEach(track => track.stop());
      remoteStream = null;
    }
    if (audioEl) {
      audioEl.srcObject = null;
      audioEl.hidden = true;
    }
    isMuted = false;
    if (muteBtn) {
      muteBtn.textContent = "Mute Mic";
      muteBtn.classList.remove("btn-danger");
      muteBtn.classList.add("btn-outline-secondary");
    }
    finalizeAssistantTranscript();
    finalizeUserTranscript();
    stopSpeechRecognition();
    startBtn.disabled = false;
    stopBtn.disabled = true;
    muteBtn.disabled = true;
    if (selectEl) selectEl.disabled = false;
    setStatus("Idle", "secondary");
  }

  function handleDataMessage(evt) {
    if (!evt?.data) {
      if (VERBOSE_LOG) {
        console.debug("[voice-chat] Empty data channel event", evt);
      }
      return;
    }

    let payload;
    try {
      payload = JSON.parse(evt.data);
    } catch (err) {
      if (VERBOSE_LOG) {
        console.debug("[voice-chat] Non-JSON event", evt.data);
      }
      return;
    }

    if (VERBOSE_LOG) {
      console.debug("[voice-chat] Event", payload.type, payload);
    }

    switch (payload.type) {
      case "response.audio_transcript.delta": {
        const delta =
          (payload.delta && (payload.delta.transcript || payload.delta.text || payload.delta)) ||
          payload.transcript ||
          payload.text ||
          "";
        updateAssistantTranscript(typeof delta === "string" ? delta : String(delta || ""));
        break;
      }
      case "response.audio_transcript.done":
      case "response.audio.done": {
        const finalText =
          (payload.transcript && payload.transcript.text) ||
          payload.transcript ||
          payload.text ||
          "";
        finalizeAssistantTranscript(typeof finalText === "string" ? finalText : String(finalText || ""));
        break;
      }
      case "response.output_text.delta":
        updateAssistantTranscript(payload.delta || "");
        break;
      case "response.output_text.done":
      case "response.output_text.completed":
      case "response.completed":
        finalizeAssistantTranscript();
        break;
      case "conversation.item.created":
        if (payload.item && payload.item.content) {
          const role = payload.item.role;
          const textContent = extractTextFromParts(payload.item.content);
          if (!textContent) break;
          const trimmed = textContent.trim();
          if (!trimmed) break;

          if (role === "user") {
            if (!userNode && !userBuffer) {
              appendTranscript(trimmed, "user");
            }
          }
        }
        break;
      case "response.input_audio_transcription.delta":
      case "response.input_text.delta":
        updateUserTranscript(payload.delta || "");
        break;
      case "response.input_audio_transcription.done":
      case "response.input_audio_transcription.completed":
      case "response.input_text.done":
      case "response.input_text.completed":
        finalizeUserTranscript();
        break;
      case "response.error":
        showError(payload.error?.message || "Realtime session error.");
        break;
      default:
        if (VERBOSE_LOG) {
          console.debug("[voice-chat] Unhandled realtime event", payload);
        }
        break;
    }
  }

  function sendInitialPrompt(instructions) {
    if (!dc || dc.readyState !== "open") {
      return;
    }
    const message = {
      type: "response.create",
      response: {
        modalities: ["text", "audio"],
        instructions: instructions,
      },
    };
    dc.send(JSON.stringify(message));
  }

  async function createSession(patientId) {
    const headers = {
      "Content-Type": "application/json",
    };
    if (CSRF) {
      headers["X-CSRFToken"] = CSRF;
    }
    const personaOverride = personaInput ? personaInput.value.trim() : "";
    const r = await fetch("/dashboard/voice-session", {
      method: "POST",
      headers,
      body: JSON.stringify({ patient_id: patientId, persona_override: personaOverride }),
    });
    if (!r.ok) {
      const msg = await r.text();
      throw new Error(`Session request failed (${r.status}): ${msg}`);
    }
    return r.json();
  }

  async function connect() {
    clearError();
    if (!selectedPatientId) {
      showError("Select a patient before starting the conversation.");
      setStatus("Idle", "secondary");
      return;
    }
    renderPatientDetails(selectedPatientId);
    resetTranscript();
    setStatus("Requesting microphone…", "warning");
    startBtn.disabled = true;
    if (selectEl) selectEl.disabled = true;

    try {
      if (!navigator.mediaDevices?.getUserMedia) {
        throw new Error("Microphone access is not supported in this browser.");
      }

      localStream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          echoCancellation: true,
          noiseSuppression: true,
        },
      });

      const session = await createSession(selectedPatientId);

      pc = new RTCPeerConnection({
        iceServers: [{ urls: "stun:stun.cloudflare.com:3478" }],
      });

      remoteStream = new MediaStream();
      audioEl.hidden = false;
      audioEl.srcObject = remoteStream;

      pc.ontrack = (evt) => {
        evt.streams[0].getTracks().forEach(track => remoteStream.addTrack(track));
        audioEl.play().catch(() => {});
      };

      pc.oniceconnectionstatechange = () => {
        if (!pc) return;
        if (["failed", "disconnected"].includes(pc.iceConnectionState)) {
          showError("Connection lost. Please try again.");
          resetState();
        }
      };

      localStream.getTracks().forEach(track => pc.addTrack(track, localStream));

      dc = pc.createDataChannel("oai-events");
      dc.onmessage = handleDataMessage;
      dc.onopen = () => {
        sendInitialPrompt(session.instructions);
      };
      dc.onerror = (evt) => {
        showError(`Realtime data error: ${evt.message || "unknown error"}`);
      };

      const offer = await pc.createOffer();
      await pc.setLocalDescription(offer);

      const sdpResponse = await fetch(
        `https://api.openai.com/v1/realtime?model=${encodeURIComponent(session.model)}`,
        {
          method: "POST",
          headers: {
            Authorization: `Bearer ${session.client_secret}`,
            "Content-Type": "application/sdp",
            "OpenAI-Beta": "realtime=v1",
          },
          body: offer.sdp,
        }
      );

      if (!sdpResponse.ok) {
        throw new Error(`OpenAI SDP exchange failed (${sdpResponse.status}).`);
      }

      const answer = await sdpResponse.text();
      await pc.setRemoteDescription({ type: "answer", sdp: answer });

      setStatus("Live", "success");
      stopBtn.disabled = false;
      muteBtn.disabled = false;
      startSpeechRecognition();
    } catch (err) {
      console.error("Voice chat setup failed", err);
      showError(err.message || "Unable to start voice session.");
      resetState();
      if (selectEl) selectEl.disabled = false;
    }
  }

  function toggleMute() {
    if (!localStream) return;
    const [track] = localStream.getAudioTracks();
    if (!track) return;
    isMuted = !isMuted;
    track.enabled = !isMuted;
    muteBtn.textContent = isMuted ? "Unmute Mic" : "Mute Mic";
    if (isMuted) {
      muteBtn.classList.remove("btn-outline-secondary");
      muteBtn.classList.add("btn-danger");
      setStatus("Muted", "warning");
    } else {
      muteBtn.classList.remove("btn-danger");
      muteBtn.classList.add("btn-outline-secondary");
      setStatus("Live", "success");
    }
  }

  startBtn.addEventListener("click", () => {
    connect();
  });

  stopBtn.addEventListener("click", () => {
    resetState();
  });

  muteBtn.addEventListener("click", () => {
    toggleMute();
  });

  window.addEventListener("beforeunload", () => {
    resetState();
  });

  resetState();
})();
