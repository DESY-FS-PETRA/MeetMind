const APP_VERSION = "2026-08-26.conf3";
console.log(`APP.JS ${APP_VERSION} LOADED`);

const API_BASE = "http://127.0.0.1:8000";
const WS_BASE = "ws://127.0.0.1:8000";
const CLIENT_ID_KEY = "meeting-ai-client-id";
const clientId = getOrCreateClientId();

let transcriptSocket = null;
let audioSocket = null;
let mediaRecorder = null;
let microphoneStream = null;
let fileAudioContext = null;
let fileAudioSource = null;
let fileAudioStream = null;
let currentMeetingId = null;
let meetingRunning = false;
let meetingStarting = false;
let meetingStopping = false;
let transcriptCount = 0;
let localRecordingChunks = [];
let localRecordingMimeType = "audio/webm";
let localRecordingUrl = null;
let currentHistoryMeetingId = null;
let historyMeetings = [];
let selectedPresentation = null;
let chatMessages = [];
let ragStatus = null;
let ragIndexing = false;
let activeWorkspace = null;
let conferences = [];
let currentConference = null;
let selectedConferenceTalk = null;
let conferenceChatMessages = [];

const transcriptEntries = new Map();
const seenTranscriptIds = new Set();
const seenTranscriptOrder = [];
const MAX_SEEN_TRANSCRIPTS = 500;

const elements = {
    status: document.getElementById("status"),
    transcript: document.getElementById("transcript"),
    transcriptCount: document.getElementById("transcriptCount"),
    meetingTitle: document.getElementById("meetingTitle"),
    presentationFile: document.getElementById("presentationFile"),
    uploadPresentationButton: document.getElementById("uploadPresentationBtn"),
    presentationStatus: document.getElementById("presentationStatus"),
    presentationContext: document.getElementById("presentationContext"),
    presentationTitle: document.getElementById("presentationTitle"),
    presentationMeta: document.getElementById("presentationMeta"),
    currentSlideBadge: document.getElementById("currentSlideBadge"),
    slideControl: document.getElementById("slideControl"),
    slideKeywords: document.getElementById("slideKeywords"),
    audioMode: document.getElementById("audioMode"),
    audioModeHelp: document.getElementById("audioModeHelp"),
    testAudioFileRow: document.getElementById("testAudioFileRow"),
    testAudioFile: document.getElementById("testAudioFile"),
    capturedAudioLink: document.getElementById("capturedAudioLink"),
    processingProgress: document.getElementById("processingProgress"),
    processingProgressLabel: document.getElementById("processingProgressLabel"),
    processingProgressPercent: document.getElementById("processingProgressPercent"),
    processingProgressBar: document.getElementById("processingProgressBar"),
    startButton: document.getElementById("startBtn"),
    stopButton: document.getElementById("stopBtn"),
    regenerateButton: document.getElementById("regenerateBtn"),
    summaryPanel: document.getElementById("summaryPanel"),
    providerBadge: document.getElementById("providerBadge"),
    vocabularyBadge: document.getElementById("vocabularyBadge"),
    summaryText: document.getElementById("summaryText"),
    slideSummaries: document.getElementById("slideSummaries"),
    technicalTerms: document.getElementById("technicalTerms"),
    transcriptionUncertainties: document.getElementById("transcriptionUncertainties"),
    keyPoints: document.getElementById("keyPoints"),
    decisions: document.getElementById("decisions"),
    actionItems: document.getElementById("actionItems"),
    discussionQuestions: document.getElementById("discussionQuestions"),
    openQuestions: document.getElementById("openQuestions"),
    newMeetingTab: document.getElementById("newMeetingTab"),
    historyTab: document.getElementById("historyTab"),
    chatTab: document.getElementById("chatTab"),
    newMeetingView: document.getElementById("newMeetingView"),
    historyView: document.getElementById("historyView"),
    chatView: document.getElementById("chatView"),
    ragStatusBadge: document.getElementById("ragStatusBadge"),
    ragReindexButton: document.getElementById("ragReindexBtn"),
    ragIndexedMeetings: document.getElementById("ragIndexedMeetings"),
    ragChunkCount: document.getElementById("ragChunkCount"),
    ragRetrievalMode: document.getElementById("ragRetrievalMode"),
    chatThread: document.getElementById("chatThread"),
    chatInput: document.getElementById("chatInput"),
    chatStatus: document.getElementById("chatStatus"),
    chatClearButton: document.getElementById("chatClearBtn"),
    chatSendButton: document.getElementById("chatSendBtn"),
    refreshHistoryButton: document.getElementById("refreshHistoryBtn"),
    historySearch: document.getElementById("historySearch"),
    historySearchButton: document.getElementById("historySearchBtn"),
    historyClearButton: document.getElementById("historyClearBtn"),
    historyStatus: document.getElementById("historyStatus"),
    historyList: document.getElementById("historyList"),
    historyCount: document.getElementById("historyCount"),
    historyTotal: document.getElementById("historyTotal"),
    historyCompleted: document.getElementById("historyCompleted"),
    historyAverageConfidence: document.getElementById("historyAverageConfidence"),
    historyDetail: document.getElementById("historyDetail"),
    historyDetailEmpty: document.getElementById("historyDetailEmpty"),
    historyDetailContent: document.getElementById("historyDetailContent"),
    historyTitleInput: document.getElementById("historyTitleInput"),
    saveHistoryTitleButton: document.getElementById("saveHistoryTitleBtn"),
    deleteHistoryButton: document.getElementById("deleteHistoryBtn"),
    historyMetadata: document.getElementById("historyMetadata"),
    historyConfidence: document.getElementById("historyConfidence"),
    historyTranscript: document.getElementById("historyTranscript"),
    historySummaryText: document.getElementById("historySummaryText"),
    historySlideSummaries: document.getElementById("historySlideSummaries"),
    historyTechnicalTerms: document.getElementById("historyTechnicalTerms"),
    historyTranscriptionUncertainties: document.getElementById("historyTranscriptionUncertainties"),
    historyKeyPoints: document.getElementById("historyKeyPoints"),
    historyDecisions: document.getElementById("historyDecisions"),
    historyActionItems: document.getElementById("historyActionItems"),
    historyDiscussionQuestions: document.getElementById("historyDiscussionQuestions"),
    historyOpenQuestions: document.getElementById("historyOpenQuestions"),
};

Object.assign(elements, {
    appShell: document.getElementById("appShell"),
    workspaceLanding: document.getElementById("workspaceLanding"),
    enterMeetingsButton: document.getElementById("enterMeetingsBtn"),
    enterConferencesButton: document.getElementById("enterConferencesBtn"),
    workspaceHomeButton: document.getElementById("workspaceHomeBtn"),
    conferenceTab: document.getElementById("conferenceTab"),
    conferenceView: document.getElementById("conferenceView"),
    newConferenceButton: document.getElementById("newConferenceBtn"),
    refreshConferencesButton: document.getElementById("refreshConferencesBtn"),
    conferenceCreatePanel: document.getElementById("conferenceCreatePanel"),
    conferenceNameInput: document.getElementById("conferenceNameInput"),
    conferenceLocationInput: document.getElementById("conferenceLocationInput"),
    conferenceStartInput: document.getElementById("conferenceStartInput"),
    conferenceEndInput: document.getElementById("conferenceEndInput"),
    conferenceProgramUrlInput: document.getElementById("conferenceProgramUrlInput"),
    conferenceTermsInput: document.getElementById("conferenceTermsInput"),
    cancelConferenceCreateButton: document.getElementById("cancelConferenceCreateBtn"),
    saveConferenceButton: document.getElementById("saveConferenceBtn"),
    conferenceCreateStatus: document.getElementById("conferenceCreateStatus"),
    conferenceList: document.getElementById("conferenceList"),
    conferenceEmpty: document.getElementById("conferenceEmpty"),
    conferenceEmptyCreateButton: document.getElementById("conferenceEmptyCreateBtn"),
    conferenceDetail: document.getElementById("conferenceDetail"),
    conferenceHeroTitle: document.getElementById("conferenceHeroTitle"),
    conferenceHeroSubtitle: document.getElementById("conferenceHeroSubtitle"),
    conferenceTalkCount: document.getElementById("conferenceTalkCount"),
    conferenceRecordedCount: document.getElementById("conferenceRecordedCount"),
    conferenceInterestingCount: document.getElementById("conferenceInterestingCount"),
    conferenceDayCount: document.getElementById("conferenceDayCount"),
    conferenceImportUrl: document.getElementById("conferenceImportUrl"),
    importConferenceUrlButton: document.getElementById("importConferenceUrlBtn"),
    conferenceJsonFile: document.getElementById("conferenceJsonFile"),
    conferenceImportStatus: document.getElementById("conferenceImportStatus"),
    conferenceTalkSearch: document.getElementById("conferenceTalkSearch"),
    conferenceDayFilter: document.getElementById("conferenceDayFilter"),
    conferenceInterestingOnly: document.getElementById("conferenceInterestingOnly"),
    conferenceSchedule: document.getElementById("conferenceSchedule"),
    conferenceTalkDetail: document.getElementById("conferenceTalkDetail"),
    conferenceTalkMeta: document.getElementById("conferenceTalkMeta"),
    conferenceTalkTitle: document.getElementById("conferenceTalkTitle"),
    conferenceTalkSpeaker: document.getElementById("conferenceTalkSpeaker"),
    conferenceTalkContext: document.getElementById("conferenceTalkContext"),
    conferenceTalkAbstract: document.getElementById("conferenceTalkAbstract"),
    closeConferenceTalkButton: document.getElementById("closeConferenceTalkBtn"),
    recordConferenceTalkButton: document.getElementById("recordConferenceTalkBtn"),
    toggleInterestingTalkButton: document.getElementById("toggleInterestingTalkBtn"),
    conferenceTalkNotes: document.getElementById("conferenceTalkNotes"),
    saveConferenceTalkNotesButton: document.getElementById("saveConferenceTalkNotesBtn"),
    conferenceTalkLinkedMeeting: document.getElementById("conferenceTalkLinkedMeeting"),
    conferenceChatScope: document.getElementById("conferenceChatScope"),
    conferenceChatThread: document.getElementById("conferenceChatThread"),
    conferenceChatInput: document.getElementById("conferenceChatInput"),
    conferenceChatAskButton: document.getElementById("conferenceChatAskBtn"),
    conferenceChatStatus: document.getElementById("conferenceChatStatus"),
});

elements.startButton.onclick = startMeeting;
elements.uploadPresentationButton.onclick = uploadPresentation;
elements.slideControl.onchange = changeSlideMode;
elements.stopButton.onclick = stopMeeting;
elements.regenerateButton.onclick = regenerateSummary;
elements.audioMode.onchange = updateAudioModeHelp;
elements.newMeetingTab.onclick = () => switchView("meeting");
elements.historyTab.onclick = () => switchView("history");
elements.chatTab.onclick = () => switchView("chat");
elements.refreshHistoryButton.onclick = () => loadMeetingHistory({ preserveSelection: true });
elements.historySearchButton.onclick = () => loadMeetingHistory();
elements.historyClearButton.onclick = () => {
    elements.historySearch.value = "";
    loadMeetingHistory();
};
elements.historySearch.addEventListener("keydown", (event) => {
    if (event.key === "Enter") loadMeetingHistory();
});
elements.saveHistoryTitleButton.onclick = saveHistoryTitle;
elements.deleteHistoryButton.onclick = deleteHistoryMeeting;
elements.ragReindexButton.onclick = () => reindexMeetings({ force: true });
elements.chatSendButton.onclick = sendChatQuestion;
elements.chatClearButton.onclick = clearChat;
elements.chatInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault();
        sendChatQuestion();
    }
});
elements.enterMeetingsButton.onclick = () => enterWorkspace("meetings");
elements.enterConferencesButton.onclick = () => enterWorkspace("conferences");
elements.workspaceHomeButton.onclick = showWorkspaceLanding;
elements.conferenceTab.onclick = () => switchView("conference");
elements.newConferenceButton.onclick = openConferenceCreate;
elements.conferenceEmptyCreateButton.onclick = openConferenceCreate;
elements.cancelConferenceCreateButton.onclick = closeConferenceCreate;
elements.saveConferenceButton.onclick = createConference;
elements.refreshConferencesButton.onclick = () => loadConferences({ preserveSelection: true });
elements.importConferenceUrlButton.onclick = importConferenceProgramUrl;
elements.conferenceJsonFile.onchange = importConferenceJsonFile;
elements.conferenceTalkSearch.oninput = renderConferenceSchedule;
elements.conferenceDayFilter.onchange = renderConferenceSchedule;
elements.conferenceInterestingOnly.onchange = renderConferenceSchedule;
elements.closeConferenceTalkButton.onclick = () => elements.conferenceTalkDetail.classList.add("is-hidden");
elements.recordConferenceTalkButton.onclick = prepareConferenceTalkRecording;
elements.toggleInterestingTalkButton.onclick = toggleConferenceTalkInteresting;
elements.saveConferenceTalkNotesButton.onclick = saveConferenceTalkNotes;
elements.conferenceChatAskButton.onclick = askConference;
elements.conferenceChatInput.addEventListener("keydown", (event) => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); askConference(); } });
updateAudioModeHelp();
elements.stopButton.disabled = true;
elements.regenerateButton.disabled = true;

async function uploadPresentation() {
    if (meetingRunning || meetingStarting) return;
    const file = elements.presentationFile.files?.[0];
    if (!file) {
        setStatus("Choose a PowerPoint or PDF presentation first", "error");
        return;
    }

    elements.uploadPresentationButton.disabled = true;
    elements.presentationFile.disabled = true;
    elements.presentationStatus.textContent = "Uploading and extracting slide text...";
    elements.presentationStatus.className = "presentation-status";

    try {
        const formData = new FormData();
        formData.append("file", file);
        const response = await fetch(`${API_BASE}/presentations/upload`, {
            method: "POST",
            body: formData,
        });
        selectedPresentation = await readJsonResponse(
            response,
            "Presentation upload failed"
        );
        renderPresentation(selectedPresentation);
        setStatus(
            `Presentation ready: ${selectedPresentation.slide_count} slide(s)`,
            "active"
        );
    } catch (error) {
        console.error("Presentation upload error:", error);
        selectedPresentation = null;
        elements.presentationStatus.textContent = `Upload error: ${error.message}`;
        setStatus(`Presentation error: ${error.message}`, "error");
    } finally {
        elements.uploadPresentationButton.disabled = false;
        elements.presentationFile.disabled = false;
    }
}

function renderPresentation(presentation) {
    if (!presentation) {
        elements.presentationContext.classList.add("is-hidden");
        elements.presentationStatus.textContent = "No presentation uploaded";
        elements.presentationStatus.className = "presentation-status";
        elements.slideControl.disabled = true;
        return;
    }

    elements.presentationContext.classList.remove("is-hidden");
    elements.presentationStatus.textContent = "Presentation text extracted";
    elements.presentationStatus.className = "presentation-status is-ready";
    elements.presentationTitle.textContent = presentation.title || presentation.filename;
    elements.presentationMeta.textContent = `${presentation.filename} · ${presentation.slide_count} slide(s)`;

    const previousValue = elements.slideControl.value || "auto";
    elements.slideControl.replaceChildren();
    const autoOption = document.createElement("option");
    autoOption.value = "auto";
    autoOption.textContent = "Automatic slide matching (recommended)";
    elements.slideControl.appendChild(autoOption);

    for (const slide of presentation.slides || []) {
        const option = document.createElement("option");
        option.value = `slide:${slide.slide_number}`;
        option.textContent = `Slide ${slide.slide_number} — ${slide.title || "Untitled"}`;
        elements.slideControl.appendChild(option);
    }
    elements.slideControl.value = Array.from(elements.slideControl.options)
        .some((option) => option.value === previousValue)
        ? previousValue
        : "auto";
    elements.slideControl.disabled = !currentMeetingId;

    const active = presentation.active_slide || presentation.slides?.[0];
    if (active) {
        renderSlideContext({
            current_slide_number: presentation.active_slide_number || active.slide_number,
            current_slide_title: active.title,
            slide_terms: active.keywords || [],
            slide_auto_match: presentation.auto_match ?? true,
        });
    }
}

async function changeSlideMode() {
    if (!currentMeetingId || !selectedPresentation) return;
    const value = elements.slideControl.value;
    elements.slideControl.disabled = true;
    try {
        let response;
        if (value === "auto") {
            response = await fetch(
                `${API_BASE}/meeting/${encodeURIComponent(currentMeetingId)}/slides/auto`,
                {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ enabled: true }),
                }
            );
        } else {
            const slideNumber = Number(value.split(":")[1]);
            response = await fetch(
                `${API_BASE}/meeting/${encodeURIComponent(currentMeetingId)}/slides/${slideNumber}/activate`,
                { method: "POST" }
            );
        }
        const payload = await readJsonResponse(response, "Slide update failed");
        renderVocabularyStatus(payload.vocabulary);
        setStatus(
            value === "auto"
                ? "Automatic slide matching enabled"
                : `Manual slide context: slide ${payload.slide?.slide_number}`,
            "active"
        );
    } catch (error) {
        setStatus(`Slide context error: ${error.message}`, "error");
    } finally {
        elements.slideControl.disabled = false;
    }
}

function renderSlideContext(vocabulary) {
    if (!selectedPresentation || !vocabulary?.current_slide_number) {
        elements.currentSlideBadge.textContent = selectedPresentation
            ? "Slide context ready"
            : "No slide context";
        elements.slideKeywords.textContent = "";
        return;
    }

    const number = Number(vocabulary.current_slide_number);
    const title = vocabulary.current_slide_title || "Untitled slide";
    const auto = vocabulary.slide_auto_match !== false;
    const terms = Array.isArray(vocabulary.slide_terms) ? vocabulary.slide_terms : [];
    elements.currentSlideBadge.textContent = `Slide ${number} · ${title}`;
    elements.currentSlideBadge.title = auto
        ? "Automatically matched from the raw transcript"
        : "Manually selected slide";
    elements.slideKeywords.textContent = terms.length
        ? `Active slide terms: ${terms.slice(0, 8).join(", ")}`
        : "No glossary terms detected on this slide.";
    elements.slideControl.value = auto ? "auto" : `slide:${number}`;
}

async function startMeeting() {
    if (meetingRunning || meetingStarting) return;

    if (["file", "recorded"].includes(elements.audioMode.value) && !elements.testAudioFile.files?.[0]) {
        setStatus("Choose an audio or video recording first", "error");
        return;
    }

    if (elements.audioMode.value === "recorded") {
        await processRecordedMeeting();
        return;
    }

    meetingStarting = true;
    setButtons({ startDisabled: true, stopDisabled: true });
    setStatus("Starting meeting...");
    resetMeetingView();

    try {
        await cleanupAllConnections();

        const title = elements.meetingTitle.value.trim() || "Conference Meeting";
        const response = await fetch(`${API_BASE}/meeting/start`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                title,
                presentation_id: selectedPresentation?.presentation_id || null,
                conference_talk_id: selectedConferenceTalk?.id || null,
                context_terms: selectedConferenceTalk?.context_terms || [],
            }),
        });
        const data = await readJsonResponse(response, "Meeting start failed");
        currentMeetingId = data.meeting_id;
        renderVocabularyStatus(data.vocabulary);
        if (data.presentation) {
            selectedPresentation = data.presentation;
            renderPresentation(selectedPresentation);
            elements.slideControl.disabled = false;
        }

        await connectTranscriptSocket();

        meetingRunning = true;
        if (elements.audioMode.value === "file") {
            await startAudioFileTest();
            setStatus("Streaming the selected audio file through the browser pipeline...", "active");
        } else {
            await startMicrophone();
            setStatus("Recording — waiting for speech...", "active");
        }

        setButtons({ startDisabled: true, stopDisabled: false });
    } catch (error) {
        console.error("Start error:", error);
        setStatus(`Error: ${error.message}`, "error");
        meetingRunning = false;
        await cleanupAllConnections();
        if (currentMeetingId) {
            await fetch(`${API_BASE}/meeting/stop`, { method: "POST" }).catch(() => {});
        }
        currentMeetingId = null;
        setButtons({ startDisabled: false, stopDisabled: true });
    } finally {
        meetingStarting = false;
    }
}

async function processRecordedMeeting() {
    if (meetingRunning || meetingStarting || meetingStopping) return;
    const file = elements.testAudioFile.files?.[0];
    if (!file) {
        setStatus("Choose an audio or video recording first", "error");
        return;
    }

    meetingStarting = true;
    setButtons({ startDisabled: true, stopDisabled: true });
    elements.regenerateButton.disabled = true;
    resetMeetingView();
    showProcessingProgress("Preparing recording…", 2);
    setStatus("Preparing recording for fast batch processing...");

    try {
        await cleanupAllConnections();
        const form = new FormData();
        form.append("file", file, file.name);
        form.append("title", elements.meetingTitle.value.trim() || file.name || "Recorded Meeting");
        if (selectedPresentation?.presentation_id) {
            form.append("presentation_id", selectedPresentation.presentation_id);
        }
        if (selectedConferenceTalk?.id) {
            form.append("conference_talk_id", selectedConferenceTalk.id);
            form.append("context_terms", (selectedConferenceTalk.context_terms || []).join("|"));
        }

        const started = performance.now();
        const data = await uploadRecordedMeetingWithProgress(form);
        currentMeetingId = data.meeting_id;
        showProcessingProgress("Building final report…", 96);

        if (data.presentation) {
            selectedPresentation = data.presentation;
            renderPresentation(selectedPresentation);
        }
        renderFinalTranscript(data.transcript || []);
        if (data.summary) renderSummary(data.summary);
        elements.regenerateButton.disabled = false;
        loadMeetingHistory({ preserveSelection: false, silent: true }).catch(() => {});

        const metrics = data.processing || {};
        const elapsed = (performance.now() - started) / 1000;
        const audioDuration = Number(metrics.audio_duration_seconds || 0);
        const speed = Number(metrics.transcription_speed_x || 0);
        const audioLabel = audioDuration > 0 ? formatSecondsCompact(audioDuration) : "recording";
        const speedLabel = speed > 0 ? ` · Whisper ${speed.toFixed(1)}× realtime` : "";
        showProcessingProgress("Report ready", 100);
        setStatus(
            `Fast report ready — ${audioLabel} processed in ${formatSecondsCompact(Number(metrics.total_seconds || elapsed))}${speedLabel}`,
            "active"
        );
        window.setTimeout(hideProcessingProgress, 1400);
        if (selectedConferenceTalk && currentConference) {
            const talkId = selectedConferenceTalk.id;
            await openConference(currentConference.id, { quiet: true });
            selectedConferenceTalk = (currentConference.talks || []).find(t => t.id === talkId) || null;
            if (selectedConferenceTalk) showConferenceTalkBanner(selectedConferenceTalk);
        }
    } catch (error) {
        console.error("Recorded processing error:", error);
        setStatus(`Recorded meeting error: ${error.message}`, "error");
        showProcessingProgress("Processing failed", null, { error: true });
        currentMeetingId = null;
    } finally {
        meetingStarting = false;
        meetingRunning = false;
        meetingStopping = false;
        setButtons({ startDisabled: false, stopDisabled: true });
        elements.regenerateButton.disabled = !currentMeetingId;
    }
}

function uploadRecordedMeetingWithProgress(form) {
    return new Promise((resolve, reject) => {
        const xhr = new XMLHttpRequest();
        xhr.open("POST", `${API_BASE}/recorded-meetings/process`);
        xhr.responseType = "json";

        xhr.upload.onprogress = (event) => {
            if (!event.lengthComputable) {
                showProcessingProgress("Uploading recording…", null, { indeterminate: true });
                return;
            }
            const uploadPercent = Math.max(0, Math.min(100, (event.loaded / event.total) * 100));
            // Upload occupies the first 20% of the visible workflow.
            const overall = 3 + (uploadPercent * 0.17);
            showProcessingProgress(`Uploading recording… ${uploadPercent.toFixed(0)}%`, overall);
        };

        xhr.upload.onload = () => {
            showProcessingProgress("Transcribing and analyzing recording…", null, { indeterminate: true });
            setStatus("Upload complete — Whisper is processing the recording on the GPU...");
        };

        xhr.onerror = () => reject(new Error("Network error while uploading the recording"));
        xhr.onabort = () => reject(new Error("Recorded meeting upload was cancelled"));
        xhr.onload = () => {
            const payload = xhr.response || (() => {
                try { return JSON.parse(xhr.responseText || "{}"); } catch (_) { return {}; }
            })();
            if (xhr.status >= 200 && xhr.status < 300) {
                resolve(payload);
                return;
            }
            const detail = payload?.detail;
            reject(new Error(typeof detail === "string" ? detail : `Recorded meeting processing failed (${xhr.status})`));
        };
        xhr.send(form);
    });
}

function showProcessingProgress(label, percent = null, { indeterminate = false, error = false } = {}) {
    elements.processingProgress.classList.remove("is-hidden");
    elements.processingProgress.classList.toggle("is-indeterminate", Boolean(indeterminate));
    elements.processingProgressLabel.textContent = label || "Processing…";
    elements.processingProgressPercent.textContent = Number.isFinite(percent) ? `${Math.round(percent)}%` : "";
    elements.processingProgressBar.style.width = Number.isFinite(percent)
        ? `${Math.max(0, Math.min(100, percent))}%`
        : "";
    const track = elements.processingProgress.querySelector(".processing-progress-track");
    if (track) {
        if (Number.isFinite(percent)) track.setAttribute("aria-valuenow", String(Math.round(percent)));
        else track.removeAttribute("aria-valuenow");
    }
    elements.processingProgress.dataset.state = error ? "error" : "active";
}

function hideProcessingProgress() {
    elements.processingProgress.classList.add("is-hidden");
    elements.processingProgress.classList.remove("is-indeterminate");
    elements.processingProgressBar.style.width = "0%";
    elements.processingProgressPercent.textContent = "";
}

function formatSecondsCompact(value) {
    const seconds = Math.max(0, Math.round(Number(value) || 0));
    const minutes = Math.floor(seconds / 60);
    const remaining = seconds % 60;
    if (minutes >= 60) {
        const hours = Math.floor(minutes / 60);
        return `${hours}h ${minutes % 60}m`;
    }
    return minutes ? `${minutes}m ${remaining}s` : `${remaining}s`;
}

async function stopMeeting() {
    if (!meetingRunning || !currentMeetingId || meetingStopping) return;

    meetingStopping = true;
    setButtons({ startDisabled: true, stopDisabled: true });
    elements.regenerateButton.disabled = true;

    try {
        showProcessingProgress("Finalizing audio…", 20);
        setStatus("Finalizing the last audio buffer...");
        await stopAudioCaptureGracefully();

        showProcessingProgress("Finishing transcription…", 58);
        setStatus("Waiting for Whisper to finish the transcript...");
        const stopResponse = await fetch(`${API_BASE}/meeting/stop`, {
            method: "POST",
        });
        const meeting = await readJsonResponse(stopResponse, "Meeting stop failed");
        renderFinalTranscript(meeting.transcript || []);

        showProcessingProgress("Generating AI report…", 82);
        setStatus("Generating meeting summary and action items...");
        const summary = await requestSummary(currentMeetingId);
        renderSummary(summary);
        loadMeetingHistory({ preserveSelection: false, silent: true }).catch(() => {});

        const providerLabel = formatSummaryProvider(summary);
        const mode = summary.provider === "extractive-fallback"
            ? "Meeting completed — local fallback summary generated"
            : `AI summary ready (${providerLabel})`;
        showProcessingProgress("Report ready", 100);
        setStatus(mode, "active");
        window.setTimeout(hideProcessingProgress, 1400);
    } catch (error) {
        console.error("Stop error:", error);
        showProcessingProgress("Finalization failed", null, { error: true });
        setStatus(`Stop/Summary error: ${error.message}`, "error");
    } finally {
        meetingRunning = false;
        meetingStarting = false;
        meetingStopping = false;
        await closeTranscriptSocket();
        setButtons({ startDisabled: false, stopDisabled: true });
        elements.regenerateButton.disabled = !currentMeetingId;
    }
}

async function regenerateSummary() {
    if (!currentMeetingId) return;

    elements.regenerateButton.disabled = true;
    try {
        setStatus("Regenerating meeting intelligence...");
        const summary = await requestSummary(currentMeetingId);
        renderSummary(summary);
        setStatus("Summary regenerated", "active");
    } catch (error) {
        console.error("Summary regeneration error:", error);
        setStatus(`Summary error: ${error.message}`, "error");
    } finally {
        elements.regenerateButton.disabled = false;
    }
}

async function requestSummary(meetingId) {
    const response = await fetch(`${API_BASE}/meeting/${encodeURIComponent(meetingId)}/summarize`, {
        method: "POST",
    });
    return readJsonResponse(response, "Summary generation failed");
}

function connectTranscriptSocket() {
    return new Promise((resolve, reject) => {
        transcriptSocket = new WebSocket(
            `${WS_BASE}/ws/transcript?client_id=${encodeURIComponent(clientId)}`
        );

        transcriptSocket.onopen = () => {
            console.log("Transcript connected", clientId);
            resolve();
        };

        transcriptSocket.onerror = () => {
            reject(new Error("Could not connect to transcript WebSocket"));
        };

        transcriptSocket.onmessage = (event) => {
            const data = JSON.parse(event.data);
            if (data.meeting_id && data.meeting_id !== currentMeetingId) return;
            if (data.type === "vocabulary_update") {
                renderVocabularyStatus(data);
                return;
            }

            const messageId = data.id || `${data.time}|${data.text}`;
            if (seenTranscriptIds.has(messageId)) return;

            rememberTranscript(messageId);
            upsertTranscriptEntry(data);
        };

        transcriptSocket.onclose = (event) => {
            console.log("Transcript socket closed", event.code, event.reason);
        };
    });
}

async function startMicrophone() {
    const accuracyMode = elements.audioMode.value === "accuracy";
    microphoneStream = await navigator.mediaDevices.getUserMedia({
        audio: {
            channelCount: 1,
            echoCancellation: !accuracyMode,
            noiseSuppression: !accuracyMode,
            autoGainControl: !accuracyMode,
        },
    });

    const audioTrack = microphoneStream.getAudioTracks()[0];
    console.log("Applied microphone settings:", audioTrack?.getSettings?.());
    await startRecorderForStream(microphoneStream);
}

async function startAudioFileTest() {
    const file = elements.testAudioFile.files?.[0];
    if (!file) {
        throw new Error("Choose an audio file before starting the file-stream test");
    }

    const AudioContextClass = window.AudioContext || window.webkitAudioContext;
    if (!AudioContextClass) {
        throw new Error("This browser does not support the Web Audio API");
    }

    fileAudioContext = new AudioContextClass();
    await fileAudioContext.resume();

    const encodedAudio = await file.arrayBuffer();
    const decodedAudio = await fileAudioContext.decodeAudioData(encodedAudio.slice(0));
    const destination = fileAudioContext.createMediaStreamDestination();

    fileAudioSource = fileAudioContext.createBufferSource();
    fileAudioSource.buffer = decodedAudio;
    fileAudioSource.connect(destination);
    fileAudioStream = destination.stream;

    await startRecorderForStream(fileAudioStream);

    fileAudioSource.onended = () => {
        if (!meetingRunning || meetingStopping) return;
        setStatus("Test file finished — finalizing transcript and summary...");
        window.setTimeout(() => stopMeeting(), 100);
    };
    fileAudioSource.start(0);
}

async function startRecorderForStream(stream) {
    const mimeType = selectSupportedMimeType();
    audioSocket = new WebSocket(
        `${WS_BASE}/ws/audio?format=webm&client_id=${encodeURIComponent(clientId)}`
    );
    audioSocket.binaryType = "arraybuffer";
    await waitForSocketOpen(audioSocket);

    localRecordingChunks = [];
    localRecordingMimeType = mimeType || "audio/webm";
    clearCapturedAudioDownload();

    mediaRecorder = new MediaRecorder(
        stream,
        mimeType
            ? { mimeType, audioBitsPerSecond: 96_000 }
            : { audioBitsPerSecond: 96_000 }
    );

    mediaRecorder.ondataavailable = (event) => {
        if (event.data.size <= 0) return;

        if (elements.audioMode.value !== "meeting") {
            localRecordingChunks.push(event.data);
        }

        if (audioSocket?.readyState === WebSocket.OPEN) {
            audioSocket.send(event.data);
        }
    };

    mediaRecorder.onerror = (event) => {
        console.error("MediaRecorder error:", event.error);
        setStatus(
            `Recorder error: ${event.error?.message || "unknown"}`,
            "error"
        );
    };

    mediaRecorder.start(500);
}

async function stopAudioCaptureGracefully() {
    stopFileAudioSource();

    const recorder = mediaRecorder;
    mediaRecorder = null;

    if (recorder && recorder.state !== "inactive") {
        await new Promise((resolve) => {
            recorder.addEventListener("stop", resolve, { once: true });
            recorder.stop();
        });
    }

    prepareCapturedAudioDownload();
    stopCaptureTracks();
    await closeFileAudioContext();

    const socket = audioSocket;
    audioSocket = null;
    if (!socket || socket.readyState !== WebSocket.OPEN) return;

    await new Promise((resolve, reject) => {
        const timeout = setTimeout(() => {
            reject(new Error("Audio finalization timed out"));
        }, 20_000);

        const finish = () => {
            clearTimeout(timeout);
            resolve();
        };

        socket.addEventListener("message", (event) => {
            try {
                const data = JSON.parse(event.data);
                if (data.type === "audio_finalized") finish();
            } catch (_) {
                // Audio control messages are JSON; ignore unrelated data.
            }
        });
        socket.addEventListener("close", finish, { once: true });
        socket.addEventListener("error", () => {
            clearTimeout(timeout);
            reject(new Error("Audio WebSocket closed unexpectedly"));
        }, { once: true });

        // WebSocket preserves message order, so this control message is
        // processed after the final MediaRecorder data chunk.
        socket.send("stop");
    });

    closeSocket(socket, "Audio finalized");
}

async function cleanupAllConnections() {
    stopFileAudioSource();

    const recorder = mediaRecorder;
    mediaRecorder = null;

    if (recorder && recorder.state !== "inactive") {
        await new Promise((resolve) => {
            recorder.addEventListener("stop", resolve, { once: true });
            recorder.stop();
        });
    }

    stopCaptureTracks();
    await closeFileAudioContext();
    localRecordingChunks = [];

    closeSocket(audioSocket, "Audio cleanup");
    audioSocket = null;
    await closeTranscriptSocket();
}

async function closeTranscriptSocket() {
    const socket = transcriptSocket;
    transcriptSocket = null;
    if (!socket) return;
    closeSocket(socket, "Transcript stopped");
}

function renderFinalTranscript(items) {
    for (const item of items) {
        const messageId = item.id || `${item.time}|${item.text}`;
        if (!seenTranscriptIds.has(messageId)) {
            rememberTranscript(messageId);
        }
        upsertTranscriptEntry({
            ...item,
            operation: item.operation || "replace",
            is_final: item.is_final ?? true,
        });
    }
}

function upsertTranscriptEntry(data) {
    const empty = elements.transcript.querySelector(".empty-state");
    empty?.remove();

    const segmentId = data.segment_id || data.id || `${data.time}|${data.text}`;
    let record = transcriptEntries.get(segmentId);

    if (!record) {
        const entry = document.createElement("div");
        entry.className = "transcript-entry";
        entry.dataset.segmentId = segmentId;

        const meta = document.createElement("div");
        meta.className = "transcript-meta";
        const time = document.createElement("time");
        const confidence = document.createElement("span");
        confidence.className = "confidence-summary";
        meta.append(time, confidence);

        const text = document.createElement("p");
        entry.append(meta, text);
        elements.transcript.appendChild(entry);

        record = { entry, time, confidence, text, revision: 0 };
        transcriptEntries.set(segmentId, record);
    }

    const incomingRevision = Number(data.revision || 0);
    if (incomingRevision && incomingRevision < record.revision) return;

    record.revision = incomingRevision;
    record.time.textContent = formatTime(data.time);
    renderTranscriptText(record.text, data);
    renderConfidenceSummary(record.confidence, data);
    record.entry.classList.toggle("is-partial", !data.is_final);
    record.entry.classList.toggle("is-final", Boolean(data.is_final));

    transcriptCount = transcriptEntries.size;
    elements.transcriptCount.textContent = `${transcriptCount} segment${transcriptCount === 1 ? "" : "s"}`;
    elements.transcript.scrollTop = elements.transcript.scrollHeight;
}

function renderTranscriptText(container, data) {
    container.replaceChildren();
    const words = Array.isArray(data.words) ? data.words : [];
    if (!words.length) {
        container.textContent = data.text || "";
        return;
    }

    words.forEach((word, index) => {
        if (index > 0) container.appendChild(document.createTextNode(" "));
        const span = document.createElement("span");
        span.textContent = word.text || "";
        if (word.needs_review) {
            span.className = "word-needs-review";
            const probability = Number(word.probability);
            span.title = Number.isFinite(probability)
                ? `Whisper word score: ${(probability * 100).toFixed(0)}% — review recommended`
                : "Review recommended";
        }
        container.appendChild(span);
    });
}

function renderConfidenceSummary(container, data) {
    const hasAverage = data.average_confidence !== null &&
        data.average_confidence !== undefined &&
        data.average_confidence !== "";
    const average = Number(data.average_confidence);
    const lowCount = Number(data.low_confidence_count || 0);
    const parts = [];
    if (hasAverage && Number.isFinite(average)) {
        parts.push(`${(average * 100).toFixed(0)}% avg word score`);
    }
    if (lowCount > 0) {
        parts.push(`${lowCount} needs review`);
    }
    container.textContent = parts.join(" · ");
    container.classList.toggle("has-review", lowCount > 0);
}

function renderVocabularyStatus(vocabulary) {
    renderSlideContext(vocabulary);
    if (!vocabulary) {
        elements.vocabularyBadge.className = "badge badge-vocabulary";
        elements.vocabularyBadge.textContent = "Scientific vocabulary · core terms";
        return;
    }

    const labels = Array.isArray(vocabulary.category_labels)
        ? vocabulary.category_labels
        : [];
    const termCount = Number(
        vocabulary.active_term_count ?? vocabulary.active_terms?.length ?? 0
    );
    const corrections = Number(vocabulary.correction_count || 0);
    const label = labels.length
        ? labels.slice(0, 2).join(" + ")
        : "Core scientific vocabulary";
    const parts = [label];
    if (termCount) parts.push(`${termCount} terms`);
    if (corrections) parts.push(`${corrections} corrected`);

    elements.vocabularyBadge.className = "badge badge-vocabulary";
    elements.vocabularyBadge.textContent = parts.join(" · ");
    elements.vocabularyBadge.title = labels.length
        ? `Detected domains: ${labels.join(", ")}`
        : "Core scientific hotwords are active until the meeting topic is detected.";
}

function renderSummary(summary) {
    elements.summaryPanel.classList.remove("is-hidden");
    elements.summaryText.textContent = summary.summary || "No summary available.";
    renderSlideSummaries(elements.slideSummaries, summary.slide_summaries || []);
    renderTermChips(elements.technicalTerms, summary.technical_terms || []);
    renderList(
        elements.transcriptionUncertainties,
        summary.transcription_uncertainties || [],
        "No scientific terms require review."
    );
    renderList(elements.keyPoints, summary.key_points, "No key points extracted.");
    renderList(elements.decisions, summary.decisions, "No explicit decisions detected.");
    renderDiscussionQuestions(elements.discussionQuestions, summary.discussion_questions || []);
    renderList(elements.openQuestions, summary.open_questions, "No unresolved questions detected.");
    renderActionItems(summary.action_items || []);

    const isAI = summary.provider === "openai" || summary.provider === "ollama";
    elements.providerBadge.className = `badge ${isAI ? "badge-ai" : "badge-fallback"}`;
    elements.providerBadge.textContent = formatSummaryProvider(summary);
}

function formatSummaryProvider(summary) {
    if (summary?.provider === "ollama") {
        return `Ollama · ${summary.model || "local model"}`;
    }
    if (summary?.provider === "openai") {
        return `OpenAI · ${summary.model || "configured model"}`;
    }
    return "Local extractive fallback";
}

function renderList(container, items = [], emptyText) {
    container.innerHTML = "";
    if (!items.length) {
        const item = document.createElement("li");
        item.className = "empty-list";
        item.textContent = emptyText;
        container.appendChild(item);
        return;
    }

    for (const value of items) {
        const item = document.createElement("li");
        item.textContent = value;
        container.appendChild(item);
    }
}

function renderSlideSummaries(container, items = []) {
    container.replaceChildren();
    if (!items.length) {
        const empty = document.createElement("p");
        empty.className = "empty-list";
        empty.textContent = "No slide-aligned discussion was available.";
        container.appendChild(empty);
        return;
    }

    for (const item of items) {
        const card = document.createElement("article");
        card.className = "slide-summary-card";

        const heading = document.createElement("div");
        heading.className = "slide-summary-heading";
        const title = document.createElement("h4");
        title.textContent = `Slide ${item.slide_number} · ${item.title || "Untitled"}`;
        heading.appendChild(title);

        const text = document.createElement("p");
        text.textContent = item.summary || "No spoken summary available.";
        card.append(heading, text);

        if (Array.isArray(item.key_terms) && item.key_terms.length) {
            const terms = document.createElement("div");
            terms.className = "term-chips compact";
            for (const value of item.key_terms) {
                const chip = document.createElement("span");
                chip.textContent = value;
                terms.appendChild(chip);
            }
            card.appendChild(terms);
        }
        container.appendChild(card);
    }
}

function renderDiscussionQuestions(container, items = []) {
    container.replaceChildren();
    if (!items.length) {
        const empty = document.createElement("p");
        empty.className = "empty-list";
        empty.textContent = "No technical discussion questions detected.";
        container.appendChild(empty);
        return;
    }

    for (const item of items) {
        const card = document.createElement("article");
        card.className = `qa-card ${item.status === "answered" ? "is-answered" : "is-unresolved"}`;

        const head = document.createElement("div");
        head.className = "qa-card-head";
        const question = document.createElement("strong");
        question.textContent = item.question || "Question";
        const status = document.createElement("span");
        status.className = "qa-status";
        status.textContent = item.status === "answered" ? "Answered" : "Unresolved";
        head.append(question, status);
        card.appendChild(head);

        if (item.status === "answered" && item.answer) {
            const answer = document.createElement("p");
            answer.textContent = item.answer;
            card.appendChild(answer);
        }
        container.appendChild(card);
    }
}

function renderTermChips(container, items = []) {
    container.replaceChildren();
    if (!items.length) {
        const empty = document.createElement("p");
        empty.className = "empty-list";
        empty.textContent = "No technical terms extracted.";
        container.appendChild(empty);
        return;
    }
    for (const value of items) {
        const chip = document.createElement("span");
        chip.textContent = value;
        container.appendChild(chip);
    }
}

function renderActionItems(items) {
    elements.actionItems.innerHTML = "";
    if (!items.length) {
        const empty = document.createElement("p");
        empty.className = "empty-list";
        empty.textContent = "No explicit action items detected.";
        elements.actionItems.appendChild(empty);
        return;
    }

    for (const item of items) {
        const row = document.createElement("div");
        row.className = "action-item";

        const task = document.createElement("p");
        task.textContent = item.task;

        const meta = document.createElement("div");
        meta.className = "action-meta";
        meta.textContent = [
            item.owner ? `Owner: ${item.owner}` : "Owner: unassigned",
            item.deadline ? `Due: ${item.deadline}` : "Due: not specified",
        ].join(" · ");

        row.append(task, meta);
        elements.actionItems.appendChild(row);
    }
}


function switchView(view) {
    const showMeeting = view === "meeting";
    const showHistory = view === "history";
    const showChat = view === "chat";
    const showConference = view === "conference";

    elements.newMeetingView.classList.toggle("is-hidden", !showMeeting);
    elements.historyView.classList.toggle("is-hidden", !showHistory);
    elements.chatView.classList.toggle("is-hidden", !showChat);
    elements.conferenceView.classList.toggle("is-hidden", !showConference);

    elements.newMeetingTab.classList.toggle("is-active", showMeeting);
    elements.historyTab.classList.toggle("is-active", showHistory);
    elements.chatTab.classList.toggle("is-active", showChat);
    elements.conferenceTab.classList.toggle("is-active", showConference);
    elements.newMeetingTab.setAttribute("aria-selected", String(showMeeting));
    elements.historyTab.setAttribute("aria-selected", String(showHistory));
    elements.chatTab.setAttribute("aria-selected", String(showChat));
    elements.conferenceTab.setAttribute("aria-selected", String(showConference));

    if (showHistory) {
        loadMeetingHistory({ preserveSelection: true });
    } else if (showChat) {
        initializeRagChat();
    } else if (showConference) {
        loadConferences({ preserveSelection: true });
    }
}

async function loadMeetingHistory({ preserveSelection = false, silent = false } = {}) {
    if (!silent) setHistoryStatus("Loading meetings...");
    const search = elements.historySearch.value.trim();
    const params = new URLSearchParams({ limit: "100", offset: "0" });
    if (search) params.set("search", search);

    try {
        const response = await fetch(`${API_BASE}/meetings?${params.toString()}`);
        const payload = await readJsonResponse(response, "Meeting history failed");
        historyMeetings = Array.isArray(payload.items) ? payload.items : [];
        renderHistoryList(historyMeetings);
        renderHistoryStats(payload);

        if (preserveSelection && currentHistoryMeetingId) {
            const stillVisible = historyMeetings.some(
                (meeting) => meeting.meeting_id === currentHistoryMeetingId
            );
            if (stillVisible) {
                await openHistoryMeeting(currentHistoryMeetingId, { silent: true });
            } else {
                clearHistoryDetail();
            }
        } else if (historyMeetings.length) {
            await openHistoryMeeting(historyMeetings[0].meeting_id, { silent: true });
        } else {
            clearHistoryDetail();
        }

        if (!silent) {
            setHistoryStatus(
                search
                    ? `${payload.total || 0} matching meeting(s)`
                    : `${payload.total || 0} meeting(s) stored`,
                "active"
            );
        }
    } catch (error) {
        console.error("History load error:", error);
        if (!silent) setHistoryStatus(`History error: ${error.message}`, "error");
    }
}

function renderHistoryStats(payload) {
    elements.historyTotal.textContent = String(payload.total || 0);
    elements.historyCompleted.textContent = String(payload.completed || 0);
    const confidences = historyMeetings
        .map((meeting) => Number(meeting.average_confidence))
        .filter(Number.isFinite);
    const average = confidences.length
        ? confidences.reduce((sum, value) => sum + value, 0) / confidences.length
        : null;
    elements.historyAverageConfidence.textContent = average === null
        ? "—"
        : `${(average * 100).toFixed(0)}%`;
}

function renderHistoryList(meetings) {
    elements.historyList.replaceChildren();
    elements.historyCount.textContent = `${meetings.length} meeting${meetings.length === 1 ? "" : "s"}`;

    if (!meetings.length) {
        const empty = document.createElement("p");
        empty.className = "empty-state";
        empty.textContent = elements.historySearch.value.trim()
            ? "No meetings match this search."
            : "No meetings have been stored yet.";
        elements.historyList.appendChild(empty);
        return;
    }

    for (const meeting of meetings) {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "history-list-item";
        button.dataset.meetingId = meeting.meeting_id;
        button.classList.toggle("is-selected", meeting.meeting_id === currentHistoryMeetingId);
        button.onclick = () => openHistoryMeeting(meeting.meeting_id);

        const top = document.createElement("div");
        top.className = "history-list-item-top";
        const title = document.createElement("strong");
        title.textContent = meeting.title || "Untitled meeting";
        const status = document.createElement("span");
        status.className = `meeting-status status-${meeting.status || "unknown"}`;
        status.textContent = meeting.status || "unknown";
        top.append(title, status);

        const dateRow = document.createElement("div");
        dateRow.className = "history-date-row";
        const dateChip = document.createElement("span");
        dateChip.className = "history-date-chip";
        dateChip.textContent = `📅 ${formatDateTime(meeting.start_time || meeting.created_at)}`;
        const durationChip = document.createElement("span");
        durationChip.className = "history-date-chip";
        durationChip.textContent = `⏱ ${formatDuration(meeting.start_time, meeting.end_time)}`;
        dateRow.append(dateChip, durationChip);

        const meta = document.createElement("p");
        meta.textContent = `${meeting.transcript_count || 0} transcript segment(s)`;

        const preview = document.createElement("p");
        preview.className = "history-preview";
        preview.textContent = meeting.final_transcript
            ? truncateText(meeting.final_transcript, 145)
            : "No final transcript available.";

        const confidence = document.createElement("span");
        confidence.className = "history-confidence-chip";
        const average = Number(meeting.average_confidence);
        confidence.textContent = Number.isFinite(average)
            ? `${(average * 100).toFixed(0)}% confidence`
            : "Confidence unavailable";

        button.append(top, dateRow, meta, preview, confidence);
        elements.historyList.appendChild(button);
    }
}

async function openHistoryMeeting(meetingId, { silent = false } = {}) {
    if (!silent) setHistoryStatus("Loading meeting details...");
    try {
        const response = await fetch(`${API_BASE}/meetings/${encodeURIComponent(meetingId)}`);
        const meeting = await readJsonResponse(response, "Meeting details failed");
        currentHistoryMeetingId = meetingId;
        renderHistoryDetail(meeting);
        document.querySelectorAll(".history-list-item").forEach((item) => {
            item.classList.toggle("is-selected", item.dataset.meetingId === meetingId);
        });
        if (!silent) setHistoryStatus("Meeting loaded", "active");
    } catch (error) {
        console.error("History detail error:", error);
        setHistoryStatus(`Meeting error: ${error.message}`, "error");
    }
}

function renderHistoryDetail(meeting) {
    elements.historyDetailEmpty.classList.add("is-hidden");
    elements.historyDetailContent.classList.remove("is-hidden");
    elements.historyTitleInput.value = meeting.title || "";

    elements.historyMetadata.replaceChildren();
    const metadata = [
        ["Status", meeting.status || "unknown"],
        ["Meeting date", formatDateTime(meeting.start_time || meeting.created_at)],
        ["Report generated", formatDateTime(meeting.summary?.generated_at)],
        ["Duration", formatDuration(meeting.start_time, meeting.end_time)],
        ["Segments", String(meeting.transcript_count || 0)],
        ["Review words", String(meeting.low_confidence_count || 0)],
        ["Summary AI", meeting.summary ? formatSummaryProvider(meeting.summary) : "Not generated"],
        ["Vocabulary", meeting.vocabulary?.category_labels?.length
            ? meeting.vocabulary.category_labels.join(", ")
            : "Core terms only"],
        ["Presentation", meeting.presentation
            ? `${meeting.presentation.title} (${meeting.presentation.slide_count} slides)`
            : "None"],
    ];
    for (const [label, value] of metadata) {
        const item = document.createElement("span");
        item.innerHTML = `<strong>${escapeHtml(label)}:</strong> ${escapeHtml(value || "—")}`;
        elements.historyMetadata.appendChild(item);
    }

    const transcriptItems = Array.isArray(meeting.transcript) ? meeting.transcript : [];
    const finalItems = transcriptItems.filter((item) => item.is_final);
    const selected = finalItems.length ? finalItems : transcriptItems;
    renderHistoryTranscript(selected);

    const average = Number(meeting.average_confidence);
    const confidenceParts = [];
    if (Number.isFinite(average)) confidenceParts.push(`${(average * 100).toFixed(0)}% avg word score`);
    if (meeting.low_confidence_count) confidenceParts.push(`${meeting.low_confidence_count} needs review`);
    elements.historyConfidence.textContent = confidenceParts.join(" · ");
    elements.historyConfidence.classList.toggle("has-review", Boolean(meeting.low_confidence_count));

    const summary = meeting.summary;
    elements.historySummaryText.textContent = summary?.summary || "No summary has been generated for this meeting.";
    renderSlideSummaries(elements.historySlideSummaries, summary?.slide_summaries || []);
    renderTermChips(elements.historyTechnicalTerms, summary?.technical_terms || []);
    renderList(
        elements.historyTranscriptionUncertainties,
        summary?.transcription_uncertainties || [],
        "No scientific terms require review."
    );
    renderList(elements.historyKeyPoints, summary?.key_points || [], "No key points available.");
    renderList(elements.historyDecisions, summary?.decisions || [], "No decisions available.");
    renderDiscussionQuestions(elements.historyDiscussionQuestions, summary?.discussion_questions || []);
    renderList(elements.historyOpenQuestions, summary?.open_questions || [], "No unresolved questions available.");
    renderActionItemsInto(elements.historyActionItems, summary?.action_items || []);
}

function renderHistoryTranscript(items) {
    elements.historyTranscript.replaceChildren();
    if (!items.length) {
        const empty = document.createElement("p");
        empty.className = "empty-list";
        empty.textContent = "No transcript available.";
        elements.historyTranscript.appendChild(empty);
        return;
    }

    for (const item of items) {
        const block = document.createElement("div");
        block.className = "history-transcript-block";
        const time = document.createElement("time");
        time.textContent = formatTime(item.time);
        const text = document.createElement("p");
        renderTranscriptText(text, item);
        block.append(time, text);
        elements.historyTranscript.appendChild(block);
    }
}


async function initializeRagChat() {
    await loadRagStatus();
    if (!ragStatus) return;
    const missing = Number(ragStatus.total_meetings || 0) - Number(ragStatus.indexed_meetings || 0);
    if (missing > 0 && !ragIndexing) {
        await reindexMeetings({ force: false, silent: true });
    }
}

async function loadRagStatus() {
    setChatStatus("Checking meeting index...");
    try {
        const response = await fetch(`${API_BASE}/rag/status`);
        ragStatus = await readJsonResponse(response, "RAG status failed");
        renderRagStatus(ragStatus);
        setChatStatus("Ready", "active");
        return ragStatus;
    } catch (error) {
        console.error("RAG status error:", error);
        setChatStatus(`RAG status error: ${error.message}`, "error");
        elements.ragStatusBadge.textContent = "RAG unavailable";
        elements.ragStatusBadge.className = "badge badge-muted";
        return null;
    }
}

function renderRagStatus(status) {
    const indexed = Number(status?.indexed_meetings || 0);
    const total = Number(status?.total_meetings || 0);
    const chunks = Number(status?.chunks || 0);
    const semantic = Boolean(status?.embedding_available);

    elements.ragIndexedMeetings.textContent = `${indexed}/${total}`;
    elements.ragChunkCount.textContent = String(chunks);
    elements.ragRetrievalMode.textContent = semantic ? "Semantic + lexical" : "Lexical fallback";

    if (semantic) {
        elements.ragStatusBadge.textContent = `${status.embedding_model} · semantic RAG`;
        elements.ragStatusBadge.className = "badge badge-ai";
    } else {
        elements.ragStatusBadge.textContent = `${indexed}/${total} indexed · lexical RAG`;
        elements.ragStatusBadge.className = "badge badge-muted";
        elements.ragStatusBadge.title = status?.message || "Embedding model not available";
    }
}

async function reindexMeetings({ force = false, silent = false } = {}) {
    if (ragIndexing) return;
    ragIndexing = true;
    elements.ragReindexButton.disabled = true;
    if (!silent) setChatStatus(force ? "Rebuilding meeting index..." : "Indexing new meetings...");
    try {
        const response = await fetch(`${API_BASE}/rag/index?force=${force ? "true" : "false"}`, {
            method: "POST",
        });
        const result = await readJsonResponse(response, "RAG indexing failed");
        await loadRagStatus();
        if (!silent) {
            const mode = result.semantic_enabled ? "semantic" : "lexical";
            setChatStatus(
                `Index ready · ${result.total_meetings || 0} meetings · ${result.chunks || 0} chunks · ${mode}`,
                "active"
            );
        }
    } catch (error) {
        console.error("RAG indexing error:", error);
        setChatStatus(`Indexing error: ${error.message}`, "error");
    } finally {
        ragIndexing = false;
        elements.ragReindexButton.disabled = false;
    }
}

function isWeatherQuestion(text) {
    const q = String(text || "").toLowerCase();
    return /\b(weather|forecast)\b/.test(q)
        || /\b(temperature|temp)\b.*\b(today|tonight|outside)\b/.test(q)
        || /\b(rain|snow|wind|umbrella)\b.*\b(today|tonight)\b/.test(q);
}

function weatherQuestionHasNamedLocation(text) {
    const q = String(text || "").trim().replace(/[?!.,]+$/, "");
    const generic = new Set([
        "today", "tonight", "tomorrow", "now", "current", "currently", "outside",
        "weather", "forecast", "temperature", "temp", "temperatures", "for", "in", "at",
    ]);
    const patterns = [
        /\b(?:weather|forecast|temperature|temp)\s+(?:in|at)\s+(.+?)(?:\s+(?:today|tonight|tomorrow|now))?$/i,
        /\b(?:weather|forecast|temperature|temp)\s+for\s+(.+?)(?:\s+(?:today|tonight|tomorrow|now))?$/i,
        /\b(?:weather|forecast)\s+(.+?)(?:\s+(?:today|tonight|tomorrow|now))?$/i,
    ];
    for (const pattern of patterns) {
        const match = q.match(pattern);
        if (!match) continue;
        const tokens = String(match[1] || "").toLowerCase().match(/[a-zà-öø-ÿ0-9]+/g) || [];
        if (tokens.length && tokens.some((token) => !generic.has(token))) return true;
    }
    return false;
}

async function getOptionalWeatherLocation(question) {
    if (!isWeatherQuestion(question) || weatherQuestionHasNamedLocation(question)) {
        return {};
    }
    if (!navigator.geolocation) return {};
    setChatStatus("Weather question detected · requesting location permission...");
    try {
        const position = await new Promise((resolve, reject) => {
            navigator.geolocation.getCurrentPosition(resolve, reject, {
                enableHighAccuracy: false,
                timeout: 7000,
                maximumAge: 10 * 60 * 1000,
            });
        });
        return {
            latitude: position.coords.latitude,
            longitude: position.coords.longitude,
            timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || null,
        };
    } catch (error) {
        console.info("Browser location unavailable for weather:", error?.message || error);
        return {};
    }
}

function escapeHtml(value) {
    return String(value ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
}

function renderInlineMarkdown(value) {
    let raw = String(value ?? "");
    const protectedTokens = [];
    const protect = (html) => {
        const token = `@@PROTECTED${protectedTokens.length}@@`;
        protectedTokens.push(html);
        return token;
    };

    // Protect inline code and math before applying Markdown emphasis rules.
    raw = raw.replace(/`([^`]+)`/g, (_, code) => protect(`<code>${escapeHtml(code)}</code>`));
    raw = raw.replace(/\\\((.+?)\\\)/g, (match) => protect(escapeHtml(match)));
    raw = raw.replace(/\$(?!\$)([^$\n]+?)\$/g, (match) => protect(escapeHtml(match)));

    let text = escapeHtml(raw);
    text = text.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
    text = text.replace(/__([^_]+)__/g, "<strong>$1</strong>");
    text = text.replace(/(^|[^*])\*([^*\n]+)\*(?!\*)/g, "$1<em>$2</em>");
    for (let index = 0; index < protectedTokens.length; index += 1) {
        text = text.replace(`@@PROTECTED${index}@@`, protectedTokens[index]);
    }
    return text;
}

function isMarkdownTableSeparator(line) {
    const cells = line.trim().replace(/^\||\|$/g, "").split("|");
    return cells.length >= 2 && cells.every((cell) => /^\s*:?-{3,}:?\s*$/.test(cell));
}

function renderScientificMarkdown(value) {
    const lines = String(value ?? "").replace(/\r\n?/g, "\n").split("\n");
    const html = [];
    let paragraph = [];
    let listType = null;
    let inCode = false;
    let codeLanguage = "";
    let codeLines = [];
    let inDisplayMath = false;
    let displayMathLines = [];
    let displayMathClose = "$$";

    const flushParagraph = () => {
        if (!paragraph.length) return;
        html.push(`<p>${renderInlineMarkdown(paragraph.join(" "))}</p>`);
        paragraph = [];
    };
    const closeList = () => {
        if (!listType) return;
        html.push(`</${listType}>`);
        listType = null;
    };
    const flushDisplayMath = () => {
        if (!displayMathLines.length) return;
        const body = displayMathLines.join("\n").trim();
        const open = displayMathClose === "\\]" ? "\\[" : "$$";
        html.push(`<div class="chat-math-block">${escapeHtml(`${open}\n${body}\n${displayMathClose}`)}</div>`);
        displayMathLines = [];
    };

    for (let index = 0; index < lines.length; index += 1) {
        const line = lines[index];
        const trimmed = line.trim();

        if (inDisplayMath) {
            if ((displayMathClose === "$$" && trimmed === "$$") || (displayMathClose === "\\]" && trimmed === "\\]")) {
                flushDisplayMath();
                inDisplayMath = false;
            } else {
                displayMathLines.push(line);
            }
            continue;
        }

        if (trimmed === "$$" || trimmed === "\\[") {
            flushParagraph();
            closeList();
            inDisplayMath = true;
            displayMathClose = trimmed === "\\[" ? "\\]" : "$$";
            displayMathLines = [];
            continue;
        }

        if (trimmed.startsWith("$$") && trimmed.endsWith("$$") && trimmed.length > 4) {
            flushParagraph();
            closeList();
            const body = trimmed.slice(2, -2).trim();
            html.push(`<div class="chat-math-block">${escapeHtml(`$$\n${body}\n$$`)}</div>`);
            continue;
        }
        if (trimmed.startsWith("\\[") && trimmed.endsWith("\\]") && trimmed.length > 4) {
            flushParagraph();
            closeList();
            const body = trimmed.slice(2, -2).trim();
            html.push(`<div class="chat-math-block">${escapeHtml(`\\[\n${body}\n\\]`)}</div>`);
            continue;
        }

        if (trimmed.startsWith("```")) {
            flushParagraph();
            closeList();
            if (!inCode) {
                inCode = true;
                codeLanguage = trimmed.slice(3).trim();
                codeLines = [];
            } else {
                const languageClass = codeLanguage ? ` class="language-${escapeHtml(codeLanguage)}"` : "";
                html.push(`<pre><code${languageClass}>${escapeHtml(codeLines.join("\n"))}</code></pre>`);
                inCode = false;
                codeLanguage = "";
                codeLines = [];
            }
            continue;
        }
        if (inCode) {
            codeLines.push(line);
            continue;
        }
        if (!trimmed) {
            flushParagraph();
            closeList();
            continue;
        }
        if (trimmed.includes("|") && index + 1 < lines.length && isMarkdownTableSeparator(lines[index + 1])) {
            flushParagraph();
            closeList();
            const headers = trimmed.replace(/^\||\|$/g, "").split("|").map((cell) => cell.trim());
            const rows = [];
            index += 2;
            while (index < lines.length && lines[index].includes("|") && lines[index].trim()) {
                rows.push(lines[index].trim().replace(/^\||\|$/g, "").split("|").map((cell) => cell.trim()));
                index += 1;
            }
            index -= 1;
            html.push("<div class=\"chat-table-wrap\"><table><thead><tr>" + headers.map((cell) => `<th>${renderInlineMarkdown(cell)}</th>`).join("") + "</tr></thead><tbody>" + rows.map((row) => "<tr>" + row.map((cell) => `<td>${renderInlineMarkdown(cell)}</td>`).join("") + "</tr>").join("") + "</tbody></table></div>");
            continue;
        }
        const heading = trimmed.match(/^(#{1,4})\s+(.+)$/);
        if (heading) {
            flushParagraph();
            closeList();
            const level = Math.min(4, heading[1].length + 2);
            html.push(`<h${level}>${renderInlineMarkdown(heading[2])}</h${level}>`);
            continue;
        }
        const bullet = trimmed.match(/^[-*+]\s+(.+)$/);
        const numbered = trimmed.match(/^\d+[.)]\s+(.+)$/);
        if (bullet || numbered) {
            flushParagraph();
            const desired = bullet ? "ul" : "ol";
            if (listType !== desired) {
                closeList();
                listType = desired;
                html.push(`<${listType}>`);
            }
            html.push(`<li>${renderInlineMarkdown((bullet || numbered)[1])}</li>`);
            continue;
        }
        paragraph.push(trimmed);
    }
    if (inDisplayMath) flushDisplayMath();
    if (inCode) html.push(`<pre><code>${escapeHtml(codeLines.join("\n"))}</code></pre>`);
    flushParagraph();
    closeList();
    return html.join("");
}

function typesetChatMath(element) {
    if (!element || !window.MathJax?.typesetPromise) return;
    window.MathJax.typesetPromise([element]).catch((error) => {
        console.warn("MathJax typesetting failed:", error);
    });
}

async function sendChatQuestion() {
    const question = elements.chatInput.value.trim();
    if (!question || elements.chatSendButton.disabled) return;

    appendChatMessage("user", question);
    chatMessages.push({ role: "user", content: question });
    elements.chatInput.value = "";
    elements.chatSendButton.disabled = true;
    elements.ragReindexButton.disabled = true;
    setChatStatus("Routing question and preparing answer...");

    const placeholder = appendChatMessage("assistant", "Thinking…", { pending: true });
    try {
        const weatherLocation = await getOptionalWeatherLocation(question);
        const response = await fetch(`${API_BASE}/rag/ask`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                question,
                history: chatMessages.slice(0, -1).slice(-8),
                top_k: 8,
                ...weatherLocation,
            }),
        });
        const data = await readJsonResponse(response, "Meeting chat failed");
        placeholder.remove();
        appendChatMessage("assistant", data.answer || "No answer returned.", {
            sources: Array.isArray(data.sources) ? data.sources : [],
        });
        chatMessages.push({ role: "assistant", content: data.answer || "" });
        while (chatMessages.length > 16) chatMessages.shift();
        const route = data.route || "meeting_rag";
        const sourceCount = Array.isArray(data.sources) ? data.sources.length : 0;
        if (route === "date_time") {
            setChatStatus("Answered from system date/time", "active");
        } else if (route === "weather") {
            setChatStatus(data.needs_location ? "Weather needs a location" : "Answered using live weather data · Open-Meteo", "active");
        } else if (route === "general") {
            setChatStatus("Answered using local Ollama · general knowledge", "active");
        } else if (route === "hybrid") {
            const meetingText = sourceCount
                ? ` + ${sourceCount} meeting source${sourceCount === 1 ? "" : "s"}`
                : "";
            setChatStatus(`Answered using general knowledge${meetingText}`, "active");
        } else if (data.cross_meeting && data.evidence_found !== false) {
            const meetingCount = Array.isArray(data.meetings_used) ? data.meetings_used.length : 0;
            const mode = data.semantic_used ? "semantic + lexical" : "lexical";
            setChatStatus(`Cross-meeting answer · ${meetingCount || "multiple"} meetings · ${sourceCount} cited sources · ${mode}`, "active");
        } else if (data.evidence_found === false) {
            setChatStatus("No supporting meeting evidence found", "active");
        } else {
            const mode = data.semantic_used ? "semantic + lexical retrieval" : "lexical retrieval";
            setChatStatus(`Answered from meeting archive using ${mode} · ${sourceCount} cited source${sourceCount === 1 ? "" : "s"}`, "active");
        }
        await loadRagStatus();
    } catch (error) {
        placeholder.remove();
        appendChatMessage("assistant", `I could not answer this question: ${error.message}`);
        setChatStatus(`Chat error: ${error.message}`, "error");
    } finally {
        elements.chatSendButton.disabled = false;
        elements.ragReindexButton.disabled = false;
        elements.chatInput.focus();
    }
}

function appendChatMessage(role, text, { sources = [], pending = false } = {}) {
    const welcome = elements.chatThread.querySelector(".chat-welcome");
    if (welcome) welcome.remove();

    const wrapper = document.createElement("div");
    wrapper.className = `chat-message is-${role}`;
    if (pending) wrapper.dataset.pending = "true";
    const bubble = document.createElement("div");
    bubble.className = "chat-bubble";
    if (role === "assistant" && !pending) {
        bubble.classList.add("is-rich");
        bubble.innerHTML = renderScientificMarkdown(text);
    } else {
        bubble.textContent = text;
    }
    wrapper.appendChild(bubble);
    elements.chatThread.appendChild(wrapper);
    if (role === "assistant" && !pending) {
        typesetChatMath(bubble);
    }

    if (role === "assistant" && sources.length) {
        const sourceList = document.createElement("div");
        sourceList.className = "chat-source-list";

        const grouped = new Map();
        for (const source of sources) {
            const key = source.meeting_id || source.meeting_title || "meeting";
            if (!grouped.has(key)) grouped.set(key, []);
            grouped.get(key).push(source);
        }

        for (const meetingSources of grouped.values()) {
            const group = document.createElement("section");
            group.className = "chat-source-group";

            const groupHeader = document.createElement("div");
            groupHeader.className = "chat-source-group-head";
            const meetingName = document.createElement("strong");
            meetingName.textContent = meetingSources[0]?.meeting_title || "Meeting";
            const count = document.createElement("span");
            count.textContent = `${meetingSources.length} cited source${meetingSources.length === 1 ? "" : "s"}`;
            groupHeader.append(meetingName, count);
            group.appendChild(groupHeader);

            for (const source of meetingSources) {
                const card = document.createElement("button");
                card.type = "button";
                card.className = "chat-source-card";
                card.onclick = () => openChatSourceMeeting(source.meeting_id);

                const head = document.createElement("div");
                head.className = "chat-source-head";
                const title = document.createElement("strong");
                title.textContent = source.source_label || "Meeting evidence";
                const id = document.createElement("span");
                id.className = "chat-source-id";
                id.textContent = source.source_id || "Source";
                head.append(title, id);

                const meta = document.createElement("p");
                meta.className = "chat-source-meta";
                meta.textContent = formatDateTime(source.meeting_date);
                const excerpt = document.createElement("p");
                excerpt.textContent = source.excerpt || "";
                card.append(head, meta, excerpt);
                group.appendChild(card);
            }
            sourceList.appendChild(group);
        }
        elements.chatThread.appendChild(sourceList);
    }

    elements.chatThread.scrollTop = elements.chatThread.scrollHeight;
    return wrapper;
}

async function openChatSourceMeeting(meetingId) {
    if (!meetingId) return;
    currentHistoryMeetingId = meetingId;
    switchView("history");
    await loadMeetingHistory({ preserveSelection: true, silent: true });
    await openHistoryMeeting(meetingId, { silent: true });
}

function clearChat() {
    chatMessages = [];
    elements.chatThread.replaceChildren();
    const welcome = document.createElement("div");
    welcome.className = "chat-welcome";
    welcome.innerHTML = `
        <p class="section-kicker">MEETMIND KNOWLEDGE</p>
        <h3>Ask across your meeting memory</h3>
        <p>Ask about methods, decisions, results, unresolved questions, people, software, or compare multiple meetings side by side.</p>
    `;
    elements.chatThread.appendChild(welcome);
    setChatStatus("Ready", "active");
}

function setChatStatus(message, state = "") {
    elements.chatStatus.textContent = message;
    elements.chatStatus.className = `chat-status${state ? ` is-${state}` : ""}`;
}

async function saveHistoryTitle() {
    if (!currentHistoryMeetingId) return;
    const title = elements.historyTitleInput.value.trim();
    if (!title) {
        setHistoryStatus("Meeting title cannot be empty", "error");
        return;
    }

    elements.saveHistoryTitleButton.disabled = true;
    try {
        const response = await fetch(
            `${API_BASE}/meetings/${encodeURIComponent(currentHistoryMeetingId)}`,
            {
                method: "PATCH",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ title }),
            }
        );
        await readJsonResponse(response, "Meeting update failed");
        setHistoryStatus("Meeting title saved", "active");
        await loadMeetingHistory({ preserveSelection: true, silent: true });
    } catch (error) {
        setHistoryStatus(`Update error: ${error.message}`, "error");
    } finally {
        elements.saveHistoryTitleButton.disabled = false;
    }
}

async function deleteHistoryMeeting() {
    if (!currentHistoryMeetingId) return;
    const selected = historyMeetings.find(
        (meeting) => meeting.meeting_id === currentHistoryMeetingId
    );
    const label = selected?.title || "this meeting";
    if (!window.confirm(`Delete “${label}”? This cannot be undone.`)) return;

    elements.deleteHistoryButton.disabled = true;
    try {
        const response = await fetch(
            `${API_BASE}/meetings/${encodeURIComponent(currentHistoryMeetingId)}`,
            { method: "DELETE" }
        );
        if (!response.ok) {
            await readJsonResponse(response, "Meeting deletion failed");
        }
        currentHistoryMeetingId = null;
        clearHistoryDetail();
        await loadMeetingHistory({ preserveSelection: false, silent: true });
        setHistoryStatus("Meeting deleted", "active");
    } catch (error) {
        setHistoryStatus(`Delete error: ${error.message}`, "error");
    } finally {
        elements.deleteHistoryButton.disabled = false;
    }
}

function clearHistoryDetail() {
    currentHistoryMeetingId = null;
    elements.historyDetailEmpty.classList.remove("is-hidden");
    elements.historyDetailContent.classList.add("is-hidden");
}

function setHistoryStatus(message, mode = "normal") {
    elements.historyStatus.textContent = message;
    elements.historyStatus.className = "status";
    if (mode === "error") elements.historyStatus.classList.add("is-error");
    if (mode === "active") elements.historyStatus.classList.add("is-active");
}

function renderActionItemsInto(container, items) {
    container.replaceChildren();
    if (!items.length) {
        const empty = document.createElement("p");
        empty.className = "empty-list";
        empty.textContent = "No explicit action items detected.";
        container.appendChild(empty);
        return;
    }

    for (const item of items) {
        const row = document.createElement("div");
        row.className = "action-item";
        const task = document.createElement("p");
        task.textContent = item.task || "Untitled action";
        const meta = document.createElement("div");
        meta.className = "action-meta";
        meta.textContent = [
            item.owner ? `Owner: ${item.owner}` : "Owner: unassigned",
            item.deadline ? `Due: ${item.deadline}` : "Due: not specified",
        ].join(" · ");
        row.append(task, meta);
        container.appendChild(row);
    }
}

function formatDateTime(value) {
    if (!value) return "";
    const date = new Date(value);
    return Number.isNaN(date.getTime())
        ? value
        : date.toLocaleString([], {
            year: "numeric",
            month: "short",
            day: "2-digit",
            hour: "2-digit",
            minute: "2-digit",
        });
}

function formatDuration(startValue, endValue) {
    if (!startValue || !endValue) return "In progress";
    const start = new Date(startValue);
    const end = new Date(endValue);
    if (Number.isNaN(start.getTime()) || Number.isNaN(end.getTime())) return "";
    const totalSeconds = Math.max(0, Math.round((end - start) / 1000));
    const minutes = Math.floor(totalSeconds / 60);
    const seconds = totalSeconds % 60;
    if (minutes >= 60) {
        const hours = Math.floor(minutes / 60);
        return `${hours}h ${minutes % 60}m`;
    }
    return `${minutes}m ${seconds}s`;
}

function truncateText(value, maxLength) {
    const text = String(value || "").replace(/\s+/g, " ").trim();
    return text.length <= maxLength ? text : `${text.slice(0, maxLength - 1)}…`;
}

function escapeHtml(value) {
    return String(value ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
}

function resetMeetingView() {
    currentMeetingId = null;
    transcriptCount = 0;
    transcriptEntries.clear();
    clearSeenTranscripts();
    elements.transcript.innerHTML = '<p class="empty-state">Listening for speech...</p>';
    elements.transcriptCount.textContent = "0 segments";
    elements.summaryPanel.classList.add("is-hidden");
    elements.providerBadge.className = "badge badge-muted";
    elements.providerBadge.textContent = "Summary not generated";
    renderVocabularyStatus(null);
    elements.slideControl.disabled = true;
    elements.regenerateButton.disabled = true;
    clearCapturedAudioDownload();
    hideProcessingProgress();
}

function updateAudioModeHelp() {
    const mode = elements.audioMode.value;
    elements.testAudioFileRow.classList.toggle("is-hidden", !["file", "recorded"].includes(mode));
    elements.startButton.textContent = mode === "recorded" ? "Process Recording" : "Start Meeting";

    if (mode === "recorded") {
        elements.audioModeHelp.textContent =
            "Uploads the complete recording and runs batched Whisper as fast as the GPU allows. The audio is not played in real time; transcript, slide alignment, and report are returned together.";
    } else if (mode === "file") {
        elements.audioModeHelp.textContent =
            "Regression mode: plays the file through MediaRecorder and the live WebSocket pipeline at real-time speed.";
    } else if (mode === "accuracy") {
        elements.audioModeHelp.textContent =
            "Raw microphone mode. Use only to inspect the acoustic speaker-to-microphone path.";
    } else {
        elements.audioModeHelp.textContent =
            "Use this for a person speaking directly into the microphone.";
    }
}

function stopCaptureTracks() {
    microphoneStream?.getTracks().forEach((track) => track.stop());
    microphoneStream = null;
    fileAudioStream?.getTracks().forEach((track) => track.stop());
    fileAudioStream = null;
}

function stopFileAudioSource() {
    if (!fileAudioSource) return;
    fileAudioSource.onended = null;
    try {
        fileAudioSource.stop();
    } catch (_) {
        // The source may already have ended.
    }
    try {
        fileAudioSource.disconnect();
    } catch (_) {
        // Ignore disconnect errors during cleanup.
    }
    fileAudioSource = null;
}

async function closeFileAudioContext() {
    const context = fileAudioContext;
    fileAudioContext = null;
    if (context && context.state !== "closed") {
        try {
            await context.close();
        } catch (error) {
            console.warn("AudioContext close error:", error);
        }
    }
}

function prepareCapturedAudioDownload() {
    if (!localRecordingChunks.length || elements.audioMode.value === "meeting") return;

    if (localRecordingUrl) URL.revokeObjectURL(localRecordingUrl);
    const blob = new Blob(localRecordingChunks, { type: localRecordingMimeType });
    localRecordingUrl = URL.createObjectURL(blob);
    elements.capturedAudioLink.href = localRecordingUrl;
    elements.capturedAudioLink.download = `captured-${Date.now()}.webm`;
    elements.capturedAudioLink.classList.remove("is-hidden");
    localRecordingChunks = [];
}

function clearCapturedAudioDownload() {
    if (localRecordingUrl) {
        URL.revokeObjectURL(localRecordingUrl);
        localRecordingUrl = null;
    }
    elements.capturedAudioLink.removeAttribute("href");
    elements.capturedAudioLink.classList.add("is-hidden");
}

function selectSupportedMimeType() {
    const candidates = ["audio/webm;codecs=opus", "audio/webm"];
    return candidates.find((type) => MediaRecorder.isTypeSupported(type)) || "";
}

function waitForSocketOpen(socket) {
    return new Promise((resolve, reject) => {
        socket.addEventListener("open", resolve, { once: true });
        socket.addEventListener(
            "error",
            () => reject(new Error("Could not connect to audio WebSocket")),
            { once: true }
        );
    });
}

function closeSocket(socket, reason) {
    if (!socket) return;
    if (
        socket.readyState === WebSocket.OPEN ||
        socket.readyState === WebSocket.CONNECTING
    ) {
        try {
            socket.close(1000, reason);
        } catch (error) {
            console.warn("Socket close error:", error);
        }
    }
}

async function readJsonResponse(response, fallbackMessage) {
    let payload = null;
    try {
        payload = await response.json();
    } catch (_) {
        // Preserve a useful HTTP error below when response is not JSON.
    }

    if (!response.ok) {
        throw new Error(payload?.detail || `${fallbackMessage}: HTTP ${response.status}`);
    }
    return payload;
}

function setStatus(message, mode = "normal") {
    elements.status.textContent = message;
    elements.status.className = "status";
    if (mode === "error") elements.status.classList.add("is-error");
    if (mode === "active") elements.status.classList.add("is-active");
}

function setButtons({ startDisabled, stopDisabled }) {
    elements.startButton.disabled = startDisabled;
    elements.stopButton.disabled = stopDisabled;
    elements.meetingTitle.disabled = startDisabled;
    elements.audioMode.disabled = startDisabled;
    elements.testAudioFile.disabled = startDisabled;
    elements.presentationFile.disabled = startDisabled;
    elements.uploadPresentationButton.disabled = startDisabled;
    elements.slideControl.disabled = !currentMeetingId || stopDisabled && !meetingRunning;
}

function rememberTranscript(messageId) {
    seenTranscriptIds.add(messageId);
    seenTranscriptOrder.push(messageId);
    if (seenTranscriptOrder.length > MAX_SEEN_TRANSCRIPTS) {
        const oldest = seenTranscriptOrder.shift();
        seenTranscriptIds.delete(oldest);
    }
}

function clearSeenTranscripts() {
    seenTranscriptIds.clear();
    seenTranscriptOrder.length = 0;
}

function getOrCreateClientId() {
    let value = sessionStorage.getItem(CLIENT_ID_KEY);
    if (!value) {
        value = globalThis.crypto?.randomUUID?.() ||
            `client-${Date.now()}-${Math.random().toString(16).slice(2)}`;
        sessionStorage.setItem(CLIENT_ID_KEY, value);
    }
    return value;
}

function formatTime(value) {
    if (!value) return "";
    const date = new Date(value);
    return Number.isNaN(date.getTime())
        ? value
        : date.toLocaleTimeString([], {
            hour: "2-digit",
            minute: "2-digit",
            second: "2-digit",
        });
}

window.addEventListener("pagehide", () => {
    if (mediaRecorder?.state !== "inactive") {
        try {
            mediaRecorder.stop();
        } catch (_) {
            // Page is unloading.
        }
    }
    stopFileAudioSource();
    stopCaptureTracks();
    if (fileAudioContext && fileAudioContext.state !== "closed") {
        fileAudioContext.close().catch(() => {});
    }
    closeSocket(audioSocket, "Page closed");
    closeSocket(transcriptSocket, "Page closed");
});

// ============================================================
// Conference workspace
// ============================================================
function enterWorkspace(workspace) {
    activeWorkspace = workspace;
    elements.workspaceLanding.classList.add("is-hidden");
    elements.appShell.classList.remove("is-hidden");
    const conferenceMode = workspace === "conferences";
    elements.conferenceTab.classList.toggle("is-hidden", !conferenceMode);
    if (conferenceMode) {
        switchView("conference");
    } else {
        selectedConferenceTalk = null;
        removeConferenceTalkBanner();
        switchView("meeting");
    }
}

function showWorkspaceLanding() {
    if (meetingRunning || meetingStarting || meetingStopping) {
        setStatus("Stop the active recording before switching workspaces", "error");
        return;
    }
    elements.appShell.classList.add("is-hidden");
    elements.workspaceLanding.classList.remove("is-hidden");
}

function openConferenceCreate() {
    elements.conferenceCreatePanel.classList.remove("is-hidden");
    elements.conferenceNameInput.focus();
}

function closeConferenceCreate() {
    elements.conferenceCreatePanel.classList.add("is-hidden");
    elements.conferenceCreateStatus.textContent = "";
}

async function createConference() {
    const name = elements.conferenceNameInput.value.trim();
    if (!name) {
        elements.conferenceCreateStatus.textContent = "Conference name is required.";
        return;
    }
    const terms = elements.conferenceTermsInput.value.split(/[,;|]/).map(x => x.trim()).filter(Boolean);
    elements.saveConferenceButton.disabled = true;
    elements.conferenceCreateStatus.textContent = "Creating conference…";
    try {
        const response = await fetch(`${API_BASE}/conferences`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                name,
                location: elements.conferenceLocationInput.value.trim(),
                start_date: elements.conferenceStartInput.value || null,
                end_date: elements.conferenceEndInput.value || null,
                program_url: elements.conferenceProgramUrlInput.value.trim() || null,
                global_terms: terms,
            }),
        });
        const conference = await readJsonResponse(response, "Conference creation failed");
        currentConference = conference;
        closeConferenceCreate();
        elements.conferenceNameInput.value = "";
        elements.conferenceLocationInput.value = "";
        elements.conferenceStartInput.value = "";
        elements.conferenceEndInput.value = "";
        elements.conferenceTermsInput.value = "";
        await loadConferences({ preserveSelection: true });
        await openConference(conference.id);
        if (conference.program_url) {
            elements.conferenceImportUrl.value = conference.program_url;
        }
    } catch (error) {
        elements.conferenceCreateStatus.textContent = error.message;
    } finally {
        elements.saveConferenceButton.disabled = false;
    }
}

async function loadConferences({ preserveSelection = false } = {}) {
    try {
        const response = await fetch(`${API_BASE}/conferences`);
        const payload = await readJsonResponse(response, "Conference list failed");
        conferences = Array.isArray(payload.conferences) ? payload.conferences : [];
        renderConferenceList();
        if (preserveSelection && currentConference) {
            const exists = conferences.some(c => c.id === currentConference.id);
            if (exists) await openConference(currentConference.id, { quiet: true });
        } else if (!currentConference && conferences.length === 1) {
            await openConference(conferences[0].id, { quiet: true });
        } else if (!conferences.length) {
            currentConference = null;
            renderConferenceDetail();
        }
    } catch (error) {
        elements.conferenceList.innerHTML = `<p class="empty-state">${escapeHtml(error.message)}</p>`;
    }
}

function renderConferenceList() {
    if (!conferences.length) {
        elements.conferenceList.innerHTML = '<p class="empty-state">No conferences yet.</p>';
        return;
    }
    elements.conferenceList.innerHTML = conferences.map(conf => {
        const selected = currentConference?.id === conf.id ? " is-selected" : "";
        const date = [conf.start_date, conf.end_date].filter(Boolean).join(" → ");
        return `<button class="conference-list-item${selected}" data-conference-id="${escapeHtml(conf.id)}" type="button">
            <strong>${escapeHtml(conf.name)}</strong>
            <span>${escapeHtml(conf.location || "Location not set")}${date ? ` · ${escapeHtml(date)}` : ""}</span>
            <span>${Number(conf.talk_count || 0)} talks · ${Number(conf.recorded_talk_count || 0)} processed</span>
        </button>`;
    }).join("");
    elements.conferenceList.querySelectorAll("[data-conference-id]").forEach(button => {
        button.onclick = () => openConference(button.dataset.conferenceId);
    });
}

async function openConference(conferenceId, { quiet = false } = {}) {
    try {
        const response = await fetch(`${API_BASE}/conferences/${encodeURIComponent(conferenceId)}`);
        currentConference = await readJsonResponse(response, "Conference could not be loaded");
        selectedConferenceTalk = null;
        elements.conferenceTalkDetail.classList.add("is-hidden");
        renderConferenceList();
        renderConferenceDetail();
        if (currentConference.program_url && !elements.conferenceImportUrl.value) {
            elements.conferenceImportUrl.value = currentConference.program_url;
        }
    } catch (error) {
        if (!quiet) elements.conferenceImportStatus.textContent = error.message;
    }
}

function renderConferenceDetail() {
    const has = Boolean(currentConference);
    elements.conferenceEmpty.classList.toggle("is-hidden", has);
    elements.conferenceDetail.classList.toggle("is-hidden", !has);
    if (!has) {
        elements.conferenceHeroTitle.textContent = "Conference Hub";
        elements.conferenceHeroSubtitle.textContent = "Create a conference, import its program, and turn each talk into searchable scientific memory.";
        return;
    }
    const conf = currentConference;
    elements.conferenceHeroTitle.textContent = conf.name;
    elements.conferenceHeroSubtitle.textContent = [conf.location, [conf.start_date, conf.end_date].filter(Boolean).join(" – ")].filter(Boolean).join(" · ") || "Scientific conference workspace";
    elements.conferenceTalkCount.textContent = conf.talk_count || 0;
    elements.conferenceRecordedCount.textContent = conf.recorded_talk_count || 0;
    elements.conferenceInterestingCount.textContent = conf.interesting_count || 0;
    elements.conferenceDayCount.textContent = (conf.days || []).length || 0;
    const previousDay = elements.conferenceDayFilter.value;
    elements.conferenceDayFilter.innerHTML = '<option value="">All days</option>' + (conf.days || []).map(day => `<option value="${escapeHtml(day)}">${escapeHtml(day)}</option>`).join("");
    if ((conf.days || []).includes(previousDay)) elements.conferenceDayFilter.value = previousDay;
    renderConferenceSchedule();
}

async function importConferenceProgramUrl() {
    if (!currentConference) return;
    const url = elements.conferenceImportUrl.value.trim() || currentConference.program_url || "";
    if (!url) {
        elements.conferenceImportStatus.textContent = "Paste the official conference program URL first.";
        return;
    }
    elements.importConferenceUrlButton.disabled = true;
    elements.conferenceImportStatus.textContent = "Fetching and parsing the official program…";
    try {
        const response = await fetch(`${API_BASE}/conferences/${encodeURIComponent(currentConference.id)}/import-url`, {
            method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ url }),
        });
        const result = await readJsonResponse(response, "Program import failed");
        elements.conferenceImportStatus.textContent = `Imported/updated ${result.imported || 0} talk records. Review titles and metadata before recording.`;
        await openConference(currentConference.id, { quiet: true });
    } catch (error) {
        elements.conferenceImportStatus.textContent = `${error.message} You can use JSON import as a reliable fallback.`;
    } finally {
        elements.importConferenceUrlButton.disabled = false;
    }
}

async function importConferenceJsonFile() {
    if (!currentConference) return;
    const file = elements.conferenceJsonFile.files?.[0];
    if (!file) return;
    elements.conferenceImportStatus.textContent = "Reading JSON program…";
    try {
        const parsed = JSON.parse(await file.text());
        const talks = Array.isArray(parsed) ? parsed : parsed.talks;
        if (!Array.isArray(talks)) throw new Error('JSON must be an array of talks or an object with a "talks" array.');
        const response = await fetch(`${API_BASE}/conferences/${encodeURIComponent(currentConference.id)}/import`, {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ talks, replace: false }),
        });
        const result = await readJsonResponse(response, "JSON import failed");
        elements.conferenceImportStatus.textContent = `Imported/updated ${result.imported || 0} talks from JSON.`;
        await openConference(currentConference.id, { quiet: true });
    } catch (error) {
        elements.conferenceImportStatus.textContent = error.message;
    } finally {
        elements.conferenceJsonFile.value = "";
    }
}

function renderConferenceSchedule() {
    if (!currentConference) return;
    const query = elements.conferenceTalkSearch.value.trim().toLowerCase();
    const dayFilter = elements.conferenceDayFilter.value;
    const interestingOnly = elements.conferenceInterestingOnly.checked;
    let talks = Array.isArray(currentConference.talks) ? currentConference.talks.slice() : [];
    talks = talks.filter(talk => {
        if (dayFilter && talk.day_label !== dayFilter) return false;
        if (interestingOnly && !talk.interesting) return false;
        if (!query) return true;
        const haystack = [talk.title, talk.speaker, talk.institution, talk.session_name, talk.track, talk.room, ...(talk.keywords || []), ...(talk.context_terms || [])].join(" ").toLowerCase();
        return haystack.includes(query);
    });
    if (!talks.length) {
        elements.conferenceSchedule.innerHTML = '<p class="empty-state">No talks match this view.</p>';
        return;
    }
    const dayMap = new Map();
    for (const talk of talks) {
        const day = talk.day_label || inferDayLabel(talk.start_at) || "Program";
        if (!dayMap.has(day)) dayMap.set(day, []);
        dayMap.get(day).push(talk);
    }
    elements.conferenceSchedule.innerHTML = Array.from(dayMap.entries()).map(([day, dayTalks]) => {
        const sessionMap = new Map();
        for (const talk of dayTalks) {
            const session = talk.session_name || talk.track || "Talks";
            if (!sessionMap.has(session)) sessionMap.set(session, []);
            sessionMap.get(session).push(talk);
        }
        const sessionsHtml = Array.from(sessionMap.entries()).map(([session, sessionTalks]) => `
            <div class="conference-session-block">
                <div class="conference-session-label">${escapeHtml(session)}</div>
                ${sessionTalks.sort((a,b) => String(a.start_at || "").localeCompare(String(b.start_at || ""))).map(renderConferenceTalkRow).join("")}
            </div>`).join("");
        return `<section class="conference-day-block"><div class="conference-day-title"><h3>${escapeHtml(day)}</h3><span class="counter">${dayTalks.length} talks</span></div>${sessionsHtml}</section>`;
    }).join("");
    elements.conferenceSchedule.querySelectorAll("[data-talk-id]").forEach(row => {
        row.onclick = () => openConferenceTalk(row.dataset.talkId);
    });
}

function renderConferenceTalkRow(talk) {
    const time = formatConferenceTime(talk.start_at) || "—";
    const speakerLine = [talk.speaker, talk.institution].filter(Boolean).join(" · ") || [talk.room, talk.track].filter(Boolean).join(" · ") || "Program metadata";
    const flags = [
        talk.meeting_id ? '<span class="conference-talk-flag is-recorded">Processed</span>' : '<span class="conference-talk-flag">Not recorded</span>',
        talk.interesting ? '<span class="conference-talk-flag is-interesting">★ Interesting</span>' : "",
    ].join("");
    return `<article class="conference-talk-row" data-talk-id="${escapeHtml(talk.id)}">
        <div class="conference-talk-time">${escapeHtml(time)}</div>
        <div class="conference-talk-main"><strong>${escapeHtml(talk.title)}</strong><span>${escapeHtml(speakerLine)}${talk.room ? ` · ${escapeHtml(talk.room)}` : ""}</span></div>
        <div class="conference-talk-flags">${flags}</div>
    </article>`;
}

function openConferenceTalk(talkId) {
    const talk = (currentConference?.talks || []).find(item => item.id === talkId);
    if (!talk) return;
    selectedConferenceTalk = talk;
    elements.conferenceTalkMeta.textContent = [talk.day_label, formatConferenceTime(talk.start_at), talk.session_name, talk.room].filter(Boolean).join(" · ");
    elements.conferenceTalkTitle.textContent = talk.title;
    elements.conferenceTalkSpeaker.textContent = [talk.speaker, talk.institution].filter(Boolean).join(" — ") || "Speaker metadata not available";
    renderTermChips(elements.conferenceTalkContext, talk.context_terms || []);
    elements.conferenceTalkAbstract.textContent = talk.abstract || "No abstract was imported. The title, session and conference vocabulary are still used to build the context pack.";
    elements.conferenceTalkNotes.value = talk.notes || "";
    elements.toggleInterestingTalkButton.textContent = talk.interesting ? "★ Interesting" : "☆ Mark Interesting";
    elements.conferenceTalkLinkedMeeting.innerHTML = talk.meeting_id
        ? `Linked MeetMind record: <button class="button-link" type="button" data-open-linked-meeting="${escapeHtml(talk.meeting_id)}">${escapeHtml(talk.meeting_id)}</button>`
        : "No recording has been linked to this talk yet.";
    const linked = elements.conferenceTalkLinkedMeeting.querySelector("[data-open-linked-meeting]");
    if (linked) linked.onclick = () => { switchView("history"); openHistoryMeeting(talk.meeting_id); };
    elements.conferenceTalkDetail.classList.remove("is-hidden");
    elements.conferenceTalkDetail.scrollIntoView({ behavior: "smooth", block: "start" });
}

function prepareConferenceTalkRecording() {
    if (!selectedConferenceTalk) return;
    elements.meetingTitle.value = selectedConferenceTalk.title.slice(0, 200);
    activeWorkspace = "conferences";
    elements.conferenceTab.classList.remove("is-hidden");
    showConferenceTalkBanner(selectedConferenceTalk);
    switchView("meeting");
    setStatus(`Conference context ready · ${selectedConferenceTalk.context_terms?.length || 0} talk-specific terms loaded`, "active");
    elements.audioMode.focus();
}

function showConferenceTalkBanner(talk) {
    removeConferenceTalkBanner();
    const banner = document.createElement("div");
    banner.id = "conferenceActiveTalkBanner";
    banner.className = "conference-active-talk-banner";
    banner.innerHTML = `<strong>Conference talk:</strong> ${escapeHtml(talk.title)}<br><span>${escapeHtml([talk.day_label, formatConferenceTime(talk.start_at), talk.room].filter(Boolean).join(" · "))} · ${talk.context_terms?.length || 0} ASR context terms</span>`;
    elements.newMeetingView.prepend(banner);
}

function removeConferenceTalkBanner() {
    document.getElementById("conferenceActiveTalkBanner")?.remove();
}

async function toggleConferenceTalkInteresting() {
    if (!selectedConferenceTalk) return;
    const next = !selectedConferenceTalk.interesting;
    try {
        const response = await fetch(`${API_BASE}/conference-talks/${encodeURIComponent(selectedConferenceTalk.id)}`, {
            method:"PATCH", headers:{"Content-Type":"application/json"}, body:JSON.stringify({interesting:next}),
        });
        const updated = await readJsonResponse(response, "Could not update talk");
        const talkId = updated.id;
        await openConference(currentConference.id, { quiet:true });
        openConferenceTalk(talkId);
    } catch (error) {
        elements.conferenceTalkLinkedMeeting.textContent = error.message;
    }
}

async function saveConferenceTalkNotes() {
    if (!selectedConferenceTalk) return;
    try {
        const response = await fetch(`${API_BASE}/conference-talks/${encodeURIComponent(selectedConferenceTalk.id)}`, {
            method:"PATCH", headers:{"Content-Type":"application/json"}, body:JSON.stringify({notes:elements.conferenceTalkNotes.value}),
        });
        const updated = await readJsonResponse(response, "Could not save notes");
        elements.conferenceTalkLinkedMeeting.textContent = updated.meeting_id ? `Notes saved · linked meeting ${updated.meeting_id}` : "Notes saved.";
        const talkId = updated.id;
        await openConference(currentConference.id, { quiet:true });
        openConferenceTalk(talkId);
    } catch (error) {
        elements.conferenceTalkLinkedMeeting.textContent = error.message;
    }
}

async function askConference() {
    if (!currentConference) return;
    const question = elements.conferenceChatInput.value.trim();
    if (!question) return;
    const scope = elements.conferenceChatScope.value;
    const payload = {
        question,
        scope,
        day_label: scope === "day" ? (elements.conferenceDayFilter.value || null) : null,
        session_name: scope === "session" ? (selectedConferenceTalk?.session_name || null) : null,
        talk_ids: [],
        top_k: 10,
    };
    appendConferenceChat("user", question);
    elements.conferenceChatInput.value = "";
    elements.conferenceChatAskButton.disabled = true;
    elements.conferenceChatStatus.textContent = "Retrieving conference evidence…";
    try {
        const response = await fetch(`${API_BASE}/conferences/${encodeURIComponent(currentConference.id)}/ask`, {
            method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(payload),
        });
        const result = await readJsonResponse(response, "Conference question failed");
        appendConferenceChat("assistant", result.answer || "No answer returned", result.sources || []);
        elements.conferenceChatStatus.textContent = `${result.scope_meeting_count || 0} processed talk(s) searched.`;
    } catch (error) {
        appendConferenceChat("assistant", `Error: ${error.message}`);
        elements.conferenceChatStatus.textContent = error.message;
    } finally {
        elements.conferenceChatAskButton.disabled = false;
    }
}

function appendConferenceChat(role, text, sources = []) {
    const empty = elements.conferenceChatThread.querySelector(".empty-state");
    if (empty) empty.remove();
    const item = document.createElement("div");
    item.className = `conference-chat-message ${role === "user" ? "is-user" : "is-assistant"}`;
    item.innerHTML = renderScientificMarkdown(text);
    if (sources.length) {
        const source = document.createElement("span");
        source.className = "conference-chat-source";
        source.textContent = sources.slice(0, 5).map(s => s.source_id || s.source_label || s.meeting_title || "source").join(" · ");
        item.appendChild(source);
    }
    elements.conferenceChatThread.appendChild(item);
    elements.conferenceChatThread.scrollTop = elements.conferenceChatThread.scrollHeight;
    typesetChatMath(item);
}

function inferDayLabel(startAt) {
    if (!startAt || !String(startAt).includes("T")) return "";
    const d = new Date(startAt);
    return Number.isNaN(d.getTime()) ? "" : d.toLocaleDateString(undefined,{weekday:"short",month:"short",day:"numeric"});
}

function formatConferenceTime(value) {
    if (!value) return "";
    const text = String(value);
    if (/^\d{2}:\d{2}/.test(text)) return text.slice(0,5);
    const d = new Date(text);
    if (Number.isNaN(d.getTime())) return text.slice(0,5);
    return d.toLocaleTimeString([], {hour:"2-digit",minute:"2-digit"});
}
