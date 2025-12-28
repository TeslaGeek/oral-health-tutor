
let csrfToken;

//const csrfToken = document.querySelector('meta[name="csrf-token"]').getAttribute('content');
document.addEventListener('DOMContentLoaded', function () {
    csrfToken = document.querySelector('meta[name="csrf-token"]').getAttribute('content');
    //console.log("CSRF Token:", csrfToken);

    // Handle closing alerts when DOM is ready
    const closeButtons = document.querySelectorAll('.alert .close');
    closeButtons.forEach(button => {
        button.addEventListener('click', function () {
            this.parentElement.classList.add('d-none');
        });
    });
});

// script.js
document.addEventListener('DOMContentLoaded', function () {
    const closeButtons = document.querySelectorAll('.alert .close');
    closeButtons.forEach(button => {
        button.addEventListener('click', function () {
            this.parentElement.classList.add('d-none');
        });
    });
});

// handle clicks on the radio buttons
function handleRadioClick(radio) {
    var job_id = radio.value;

    try { localStorage.removeItem('block_hns_patient_' + job_id); } catch (e) {}

    // Make an AJAX request to your Flask server
    fetch('/process_patients', {
    method: 'POST',
    body: JSON.stringify({ patient_id: job_id }), // or patient_id if renamed
    headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': csrfToken
        }
    })

    .then(response => {
        //console.log('Received response from /process_job:', response);
        if (!response.ok) {
            throw new Error('Network response was not ok');
        }
        return response.json();
    })
    .then(data => {
        //console.log('Data received:', data);
        if (data.error) {
            console.error('Error from server:', data.error);
        } else {
            const newSessionId = data.session_id;
            const patientId = data.patient_id;


            console.log('Patient data received from server:', newSessionId);
            // Redirect after successful response from server
            window.location.href = `/history_and_symptoms?session_id=${newSessionId}&patient_id=${patientId}`;
        }
    })
    .catch(error => {
        //console.error('Error during fetch operation:', error);
        alert('An error occurred: ' + error.message);
    });
}

// Attach an event listener to the radio buttons
document.addEventListener('DOMContentLoaded', function() {
    var radioButtons = document.querySelectorAll('input[type=radio][name=selected_job]');
    radioButtons.forEach(function(radio) {
        radio.addEventListener('click', function() {
        });
    });
});



// Determine the current page's pathname
var currentPage = window.location.pathname;

if (currentPage.endsWith('/history_and_symptoms')) {
    document.addEventListener('DOMContentLoaded', function() {
        const searchParams = new URLSearchParams(window.location.search);
        const sessionIdParam = searchParams.get('session_id');
        const patientParam = searchParams.get('patient_id') || 'unknown';
        const storagePrefix = sessionIdParam ? `hns:${sessionIdParam}:` : `hns:${patientParam}:draft:`;

        function storageKey(name) {
            return `${storagePrefix}${name}`;
        }

        function clearHNSSessionDraft() {
            const removeKeys = [];
            for (let i = 0; i < sessionStorage.length; i += 1) {
                const key = sessionStorage.key(i);
                if (key && key.startsWith(storagePrefix)) {
                    removeKeys.push(key);
                }
            }
            removeKeys.forEach((key) => sessionStorage.removeItem(key));
        }

        const isFreshStart = !sessionIdParam;
        if (isFreshStart) {
            clearHNSSessionDraft();
            localStorage.removeItem('student_diagnosis');
            localStorage.removeItem('student_advice');
            localStorage.removeItem('student_recall_interval');
            localStorage.removeItem('student_referralText');
            localStorage.removeItem('referral_radio');

            // ✅ Clear all form fields
            const checkboxes = document.querySelectorAll('input[type="checkbox"]');
            checkboxes.forEach(checkbox => checkbox.checked = false);

            const hnsTextarea = document.getElementById('history_n_symptoms_text');
            if (hnsTextarea) hnsTextarea.value = '';

            ['prov_diag1', 'prov_diag2', 'prov_diag3'].forEach(id => {
                const input = document.getElementById(id);
                if (input) input.value = '';
            });
        }

        const hnsTextarea = document.getElementById('history_n_symptoms_text');
        const historyFields = [
            { id: 'prov_diag1', key: 'prov_diag1' },
            { id: 'prov_diag2', key: 'prov_diag2' },
            { id: 'prov_diag3', key: 'prov_diag3' },
        ];

        function autoResize(el) {
            if (!el) return;
            el.style.height = 'auto';
            const minHeight = 200;
            el.style.height = Math.max(el.scrollHeight, minHeight) + 'px';
        }

        if (hnsTextarea) {
            const savedHistory = sessionStorage.getItem(storageKey('history'));
            if (savedHistory && !isFreshStart) {
                hnsTextarea.value = savedHistory;
            }
            autoResize(hnsTextarea);
            hnsTextarea.addEventListener('input', () => {
                sessionStorage.setItem(storageKey('history'), hnsTextarea.value);
                autoResize(hnsTextarea);
            });
        }

        historyFields.forEach(({ id, key }) => {
            const input = document.getElementById(id);
            if (!input) return;
            const saved = sessionStorage.getItem(storageKey(key));
            if (saved !== null && !isFreshStart) {
                input.value = saved;
            }
            input.addEventListener('input', () => {
                sessionStorage.setItem(storageKey(key), input.value);
            });
        });

        const checkboxFields = document.querySelectorAll('input[type="checkbox"][id^="checkboxData_"]');
        checkboxFields.forEach((checkbox) => {
            const saved = sessionStorage.getItem(storageKey(checkbox.id));
            if (saved !== null && !isFreshStart) {
                checkbox.checked = saved === 'true';
            }
            checkbox.addEventListener('change', () => {
                sessionStorage.setItem(storageKey(checkbox.id), String(checkbox.checked));
            });
        });

        document.getElementById('HnSsubmitBtn').addEventListener('click', function (e) {
            e.preventDefault();

            const spinner = document.getElementById("fullPageSpinner");
            if (spinner) spinner.classList.remove("d-none");

            var patient_id = new URL(window.location.href).searchParams.get("patient_id");
            var session_id = window.session_id || new URL(window.location.href).searchParams.get("session_id");

            var history_n_symptoms_text = (hnsTextarea ? hnsTextarea.value : '');
            var formatted_text = history_n_symptoms_text.replace(/\n/g, '<br>');
            history_n_symptoms_text = formatted_text;
            var prov_diag1 = document.getElementById('prov_diag1').value;
            var prov_diag2 = document.getElementById('prov_diag2').value;
            var prov_diag3 = document.getElementById('prov_diag3').value;
            var checkboxData_unaided_vision = document.getElementById('checkboxData_unaided_vision').checked;
            var checkboxData_unaidedCT = document.getElementById('checkboxData_unaidedCT').checked;
            var checkboxData_focimetry = document.getElementById('checkboxData_focimetry').checked;
            var checkboxData_visual_acuity_rx = document.getElementById('checkboxData_visual_acuity_rx').checked;
            var checkboxData_ct_rx = document.getElementById('checkboxData_ct_rx').checked;
            var checkboxData_npc = document.getElementById('checkboxData_npc').checked;
            var checkboxData_motility = document.getElementById('checkboxData_motility').checked;
            var checkboxData_pupils = document.getElementById('checkboxData_pupils').checked;
            var checkboxData_PD = document.getElementById('checkboxData_PD').checked;
            var checkboxData_retinoscopy = document.getElementById('checkboxData_retinoscopy').checked;
            var checkboxData_subjective = document.getElementById('checkboxData_subjective').checked;
            var checkboxData_pinholeVA = document.getElementById('checkboxData_pinholeVA').checked;
            var checkboxData_plus1blur = document.getElementById('checkboxData_plus1blur').checked;
            var checkboxData_amp_accom = document.getElementById('checkboxData_amp_accom').checked;
            var checkboxData_near_add = document.getElementById('checkboxData_near_add').checked;
            var checkboxData_mad_rod = document.getElementById('checkboxData_mad_rod').checked;
            var checkboxData_mad_wing = document.getElementById('checkboxData_mad_wing').checked;
            var checkboxData_ct_new_rx = document.getElementById('checkboxData_ct_new_rx').checked;
            var checkboxData_fix_disparity = document.getElementById('checkboxData_fix_disparity').checked;
            var checkboxData_slit_lamp = document.getElementById('checkboxData_slit_lamp').checked;
            var checkboxData_ophthalmoscopy = document.getElementById('checkboxData_ophthalmoscopy').checked;
            var checkboxData_oct = document.getElementById('checkboxData_oct').checked;
            var checkboxData_pressures = document.getElementById('checkboxData_pressures').checked;
            var checkboxData_visual_field = document.getElementById('checkboxData_visual_field').checked;
            var checkboxData_amsler_chart = document.getElementById('checkboxData_amsler_chart').checked;
            var checkboxData_stereopsis = document.getElementById('checkboxData_stereopsis').checked;
            var checkboxData_contrast_sensitivity = document.getElementById('checkboxData_contrast_sensitivity').checked;
            var checkboxData_colour_vision = document.getElementById('checkboxData_colour_vision').checked;
            var checkboxData_dark_adaptation = document.getElementById('checkboxData_dark_adaptation').checked;
            var checkboxData_pachymetry = document.getElementById('checkboxData_pachymetry').checked;
            var checkboxData_keratometry = document.getElementById('checkboxData_keratometry').checked;

            var data = {
                'session_id': session_id,
                'patient_id': patient_id,
                'history_n_symptoms_text': history_n_symptoms_text,
                'prov_diag1': prov_diag1,
                'prov_diag2': prov_diag2,
                'prov_diag3': prov_diag3,
                'checkboxData_unaided_vision': checkboxData_unaided_vision,
                'checkboxData_unaidedCT': checkboxData_unaidedCT,
                'checkboxData_focimetry': checkboxData_focimetry,
                'checkboxData_visual_acuity_rx': checkboxData_visual_acuity_rx,
                'checkboxData_ct_rx': checkboxData_ct_rx,
                'checkboxData_npc': checkboxData_npc,
                'checkboxData_motility': checkboxData_motility,
                'checkboxData_pupils': checkboxData_pupils,
                'checkboxData_PD': checkboxData_PD,
                'checkboxData_retinoscopy': checkboxData_retinoscopy,
                'checkboxData_subjective': checkboxData_subjective,
                'checkboxData_pinholeVA': checkboxData_pinholeVA,
                'checkboxData_plus1blur': checkboxData_plus1blur,
                'checkboxData_amp_accom': checkboxData_amp_accom,
                'checkboxData_near_add': checkboxData_near_add,
                'checkboxData_mad_rod': checkboxData_mad_rod,
                'checkboxData_mad_wing': checkboxData_mad_wing,
                'checkboxData_ct_new_rx': checkboxData_ct_new_rx,
                'checkboxData_fix_disparity': checkboxData_fix_disparity,
                'checkboxData_slit_lamp': checkboxData_slit_lamp,
                'checkboxData_ophthalmoscopy': checkboxData_ophthalmoscopy,
                'checkboxData_oct': checkboxData_oct,
                'checkboxData_pressures': checkboxData_pressures,
                'checkboxData_visual_field': checkboxData_visual_field,
                'checkboxData_amsler_chart': checkboxData_amsler_chart,
                'checkboxData_stereopsis': checkboxData_stereopsis,
                'checkboxData_contrast_sensitivity': checkboxData_contrast_sensitivity,
                'checkboxData_colour_vision': checkboxData_colour_vision,
                'checkboxData_dark_adaptation': checkboxData_dark_adaptation,
                'checkboxData_pachymetry': checkboxData_pachymetry,
                'checkboxData_keratometry': checkboxData_keratometry

            };

            // Send the data to the server
            fetch('/history_and_symptoms', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': csrfToken, // Attach the CSRF token here
                },
                body: JSON.stringify(data)
            })
                .then(response => response.json())
                .then(data => {
                    if (data.success) {
                        clearHNSSessionDraft();
                        // Redirect to the test_results page with the job_id
                        window.location.href = '/test_results?session_id=' + data.session_id + '&patient_id=' + data.patient_id;
                    } else {
                        // Handle the error. Maybe display an error message to the user.
                        console.error("Failed to store data:", data.error);
                        if (spinner) spinner.classList.add("d-none");
                    }

                })
                .catch(error => {
                    // ✅ Catch network or unexpected errors
                    if (spinner)
                        spinner.classList.add("d-none");
                    console.error('Error submitting form:', error);
                });
        });
    });
    window.addEventListener("pageshow", function (event) {
        const spinner = document.getElementById("fullPageSpinner");
        if (spinner) spinner.classList.add("d-none");

        const button = document.getElementById("HnSsubmitBtn");
        if (button) button.disabled = false;
    });

    $(document).ready(function() {
    $('#chat-input').keypress(function(event) {
        var keycode = (event.keyCode ? event.keyCode : event.which);
        if (keycode == 13) {
            $("#gpt-button").click();
        }
    });

    $("#gpt-button").click(function() {

        var question = $("#chat-input").val().trim();
        if (!question) {
            return;
        }

        var session_id = window.session_id || new URL(window.location.href).searchParams.get("session_id");

        const userBubble = `
            <a href="#" class="list-group-item list-group-item-action d-flex gap-3 py-2">
                <img src="../static/images/person2.png" alt="twbs" width="19" height="19" class="rounded-circle flex-shrink-0">
                <div class="d-flex gap-2 w-100 justify-content-between">
                    <div>
                        <p class="mb-0 opacity-75">${question}</p>
                    </div>
                </div>
            </a>`;

        $("#list-group").append(userBubble);
        $("#list-group .list-group-item:last-child p").css("font-size", "12px");
        $("#chat-input").val('').prop('disabled', true);
        $("#gpt-button").prop('disabled', true);

        const typingId = `typing-${Date.now()}`;
        const typingBubble = `
            <a id="${typingId}" class="list-group-item list-group-item-action d-flex gap-3 py-2">
                <img src="../static/images/chat2.jpg" alt="twbs" width="20" height="20" class="rounded-circle flex-shrink-0">
                <div class="d-flex gap-2 w-100 justify-content-between">
                    <div>
                        <p class="mb-0 typing-indicator">Typing<span class="dot">.</span><span class="dot">.</span><span class="dot">.</span></p>
                    </div>
                </div>
            </a>`;
        $("#list-group").append(typingBubble);
        $("#list-group").scrollTop($("#list-group")[0].scrollHeight);

        $.ajax({
            type: "POST",
            url: "/chat",
            data: { 'prompt': question, 'session_id': session_id, 'csrf_token': csrfToken  },
            success: function(data) {
                $("#" + typingId).remove();
                const answerBubble = `
                    <a href="#" class="list-group-item list-group-item-action d-flex gap-3 py-2">
                        <img src="../static/images/chat2.jpg" alt="twbs" width="20" height="20" class="rounded-circle flex-shrink-0">
                        <div class="d-flex gap-2 w-100 justify-content-between">
                            <div>
                                <p class="mb-0 opacity-75">${data.answer}</p>
                            </div>
                        </div>
                    </a>`;
                $("#list-group").append(answerBubble);
                $("#list-group .list-group-item:last-child p").css("font-size", "12px");
            },
            error: function(jqXHR, textStatus, errorThrown) {
                console.log("AJAX request failed:", textStatus, errorThrown);
                $("#" + typingId).remove();
                const message = (jqXHR.responseJSON && jqXHR.responseJSON.error) ? jqXHR.responseJSON.error : "Oh, I am sorry. I got distracted and missed what you said. Could you please repeat your question?";
                const errorBubble = `
                    <a href="#" class="list-group-item list-group-item-action d-flex gap-3 py-2">
                        <img src="../static/images/chat2.jpg" alt="twbs" width="20" height="20" class="rounded-circle flex-shrink-0">
                        <div class="d-flex gap-2 w-100 justify-content-between">
                            <div>
                                <p class="mb-0 opacity-75">${message}</p>
                            </div>
                        </div>
                    </a>`;
                $("#list-group").append(errorBubble);
            },
            complete: function() {
                $("#list-group").scrollTop($("#list-group")[0].scrollHeight);
                $("#chat-input").prop('disabled', false).focus();
                $("#gpt-button").prop('disabled', false);
            }
        });
    });
});
} else if (currentPage.endsWith('/test_results')) {
    document.addEventListener('DOMContentLoaded', function() {
        const currentSessionId = new URLSearchParams(window.location.search).get("session_id");
        const currentPatientId = new URLSearchParams(window.location.search).get("patient_id");
        const previousSessionId = localStorage.getItem("previous_session_id");

        // Clear localStorage if new session
        if (currentSessionId !== previousSessionId) {
            localStorage.removeItem('student_diagnosis');
            localStorage.removeItem('student_advice');
            localStorage.removeItem('student_recall_interval');
            localStorage.removeItem('student_referralText');
            localStorage.removeItem('referral_radio');
            localStorage.setItem("previous_session_id", currentSessionId);
        }

        //console.log('Page loaded, setting up event listeners...');
        const session_id = new URL(window.location.href).searchParams.get("session_id");
        const patient_id = new URL(window.location.href).searchParams.get("patient_id");  // if needed elsewhere
        // Define input fields
        const diagnosisInput = document.getElementById('student_diagnosis');
        const adviceInput = document.getElementById('student_advice');
        const recallInput = document.getElementById('student_recall_interval');
        const referralInput = document.getElementById('student_referralText');

        // Load data from localStorage when the DOM is loaded
        if (localStorage.getItem('student_diagnosis')) {
            diagnosisInput.value = localStorage.getItem('student_diagnosis');
        }
        if (localStorage.getItem('student_advice')) {
            adviceInput.value = localStorage.getItem('student_advice');
        }
        if (localStorage.getItem('student_recall_interval')) {
            recallInput.value = localStorage.getItem('student_recall_interval');
        }
        if (localStorage.getItem('student_referralText')) {
            referralInput.value = localStorage.getItem('student_referralText');
        }

        // Load referral radio value and adjust referral text box visibility accordingly
        if (localStorage.getItem('referral_radio')) {
            const referralRadioValue = localStorage.getItem('referral_radio');
            document.querySelector(`input[name="referral_radio"][value="${referralRadioValue}"]`).checked = true;

            // Call toggleTextbox based on the saved value
            if (referralRadioValue === 'yes') {
                toggleTextbox(true);
            } else {
                toggleTextbox(false);
            }
        } else {
            toggleTextbox(false); // Hide by default if no selection is found
        }

        // Save data to localStorage when input fields change
        diagnosisInput.addEventListener('input', function() {
            //console.log('Saving diagnosis to localStorage');
            localStorage.setItem('student_diagnosis', diagnosisInput.value);
        });
        adviceInput.addEventListener('input', function() {
            //console.log('Saving advice to localStorage');
            localStorage.setItem('student_advice', adviceInput.value);
        });
        recallInput.addEventListener('input', function() {
            //console.log('Saving recall to localStorage');
            localStorage.setItem('student_recall_interval', recallInput.value);
        });
        referralInput.addEventListener('input', function() {
            //console.log('Saving referral text to localStorage');
            localStorage.setItem('student_referralText', referralInput.value);
        });

        // Update referral text box visibility based on referral radio value
        const referralRadios = document.querySelectorAll('input[name="referral_radio"]');
        referralRadios.forEach(radio => {
            radio.addEventListener('change', function() {
                if (radio.checked) {
                    //console.log(`Saving referral radio value as ${radio.value}`);
                    localStorage.setItem('referral_radio', radio.value);

                    // Call toggleTextbox based on the selected value
                    toggleTextbox(radio.value === 'yes');
                }
            });
        });

        // Adding event listener to FeedbacksubmitBtn once DOM is fully loaded
        const feedbackSubmitBtn = document.getElementById('FeedbacksubmitBtn');
        const goBackBtn = document.getElementById('GoBackBtn');
        const feedbackStatus = document.getElementById('feedbackStatus');

        function hideFeedbackStatus() {
            if (feedbackStatus) {
                feedbackStatus.classList.add('d-none');
                feedbackStatus.textContent = '';
                feedbackStatus.classList.remove('alert-warning', 'alert-danger', 'alert-success', 'alert-info');
            }
        }

        function showFeedbackStatus(message, style = 'warning') {
            if (!feedbackStatus) return;
            feedbackStatus.classList.remove('d-none', 'alert-warning', 'alert-danger', 'alert-success', 'alert-info');
            feedbackStatus.classList.add(`alert-${style}`);
            feedbackStatus.textContent = message;
        }

        function setFeedbackInProgress(isInProgress) {
            if (feedbackSubmitBtn) {
                feedbackSubmitBtn.disabled = isInProgress;
            }
            if (goBackBtn) {
                goBackBtn.disabled = isInProgress;
            }
        }

        if (feedbackSubmitBtn) {
            feedbackSubmitBtn.addEventListener('click', function(e) {
                e.preventDefault();
                //console.log('Feedback button clicked.');

                // Prevent repeated submissions while feedback is preparing
                if (feedbackSubmitBtn.disabled) {
                    return;
                }
                setFeedbackInProgress(true);
                hideFeedbackStatus();

                // Get session_id from URL
                const patient_id = new URL(window.location.href).searchParams.get("patient_id");

                //console.log('Job ID:', job_id);

                // Capture the current value of the referral radio buttons
                const referral_radio_buttons = document.querySelector('input[name="referral_radio"]:checked');
                let referral_radio = '';

                // Ensure that a radio button is selected
                if (referral_radio_buttons) {
                    referral_radio = referral_radio_buttons.value; // "yes" or "no"
                }

                //console.log('Referral Radio Value Captured:', referral_radio);

                // Capture values from the form inputs
                var diagnosis = diagnosisInput.value.replace(/\n/g, '<br>');
                var advice = adviceInput.value.replace(/\n/g, '<br>');
                var recall = recallInput.value.replace(/\n/g, '<br>');
                var referral = referralInput.value.replace(/\n/g, '<br>');
                let referral_radio_boolean = referral_radio === 'yes';

                // Prepare data to be sent to the server
                var data = {
                    'session_id': session_id,
                    'patient_id': patient_id,
                    'diagnosis': diagnosis,
                    'advice': advice,
                    'recall': recall,
                    'referral': referral,
                    'referral_radio': referral_radio_boolean
                };

                //console.log('Data to be sent:', data);

                // Show loading spinner
                const loadingPopup = document.getElementById('loadingPopup');
                if (loadingPopup) {
                    loadingPopup.style.display = 'flex';
                } else {
                    console.error('Loading popup element not found!');
                }

                // Step 1: Prepare Feedback - send the data to the backend
                fetch('/prepare_feedback/' + data.session_id, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': csrfToken, // Attach the CSRF token here
                    },
                    body: JSON.stringify(data)  // Send the data in JSON format
                })
                .then(async (resp) => {
                  const text = await resp.text();
                  let json;
                  try { json = JSON.parse(text); } catch { json = { success: false, error: text || resp.statusText }; }

                  if (!resp.ok || !json.success) {
                    console.error('prepare_feedback failed', json, 'status', resp.status);
                    showFeedbackStatus(json.error || 'Feedback preparation failed.', 'danger');
                    const loadingPopup = document.getElementById('loadingPopup');
                    if (loadingPopup) loadingPopup.style.display = 'none';
                    setFeedbackInProgress(false);
                    throw new Error('prepare_feedback ' + resp.status);
                  }
                  return json; // { success: true, session_id, ... }
                })
                .then(({ session_id }) => {
                  // No increment_attempt here — the server will bump on first feedback view
                  hideFeedbackStatus();
                  window.location.replace('/student_feedback/' + session_id);
                })
                .catch((err) => {
                  console.error(err);
                  showFeedbackStatus("We couldn't start your feedback just now. Please try again in a moment.", 'danger');
                  const loadingPopup = document.getElementById('loadingPopup');
                  if (loadingPopup) loadingPopup.style.display = 'none';
                  setFeedbackInProgress(false);
                });

            });
        } else {
            console.error('Feedback submit button not found!');
        }

        // Adding event listeners for enlarging images (restored functionality)
        const imageWrappers = document.querySelectorAll('.image-wrapper');

        function showOverlay(imageSrc, imageAlt) {
            const overlay = document.createElement('div');
            overlay.classList.add('enlarged-overlay');
            overlay.innerHTML = `<img src="${imageSrc}" alt="${imageAlt}">`;
            document.body.appendChild(overlay);
            overlay.style.display = 'flex';

            // Close the overlay when it's clicked
            overlay.addEventListener('click', function() {
                document.body.removeChild(overlay);
            });
        }

        // Adding click event to all image wrappers
        imageWrappers.forEach(function(wrapper) {
            wrapper.addEventListener('click', function() {
                const img = wrapper.querySelector('img');
                showOverlay(img.src, img.alt);
            });
        });
    });

}

else if (document.getElementById('download') && document.getElementById('content')) { //if (currentPage.includes('/student_feedback')) {
    document.addEventListener("DOMContentLoaded", function () {
        const loadingPopup = document.getElementById('loadingPopup');
        if (loadingPopup) {
            loadingPopup.style.display = 'none';
        }

        document.getElementById('download').addEventListener('click', function () {
            const element = document.getElementById('content');

            // Grab values from HTML
            const studentName = document.getElementById('studentName')?.innerText.trim().replace(/\s+/g, '_') || 'Student';
            const patientName = document.getElementById('patientName')?.innerText.trim().replace(/\s+/g, '_') || 'Patient';
            const attemptNo = document.getElementById('attemptNo')?.innerText.trim() || '1';

            const filename = `${studentName}_${patientName}_attempt${attemptNo}.pdf`;

            const opt = {
                margin: 10,
                filename: filename,
                image: { type: 'jpeg', quality: 0.98 },
                html2canvas: { scale: 2 },
                jsPDF: { unit: 'mm', format: 'a4', orientation: 'portrait' }
            };

            html2pdf().from(element).set(opt).save();
        });
    });

}
$(function () {
  $('[data-toggle="tooltip"]').tooltip();
});

function exportTableToCSV(tableId, filename) {
  const table = document.getElementById(tableId);
  if (!table) return;

  // Hyphen-like chars we want to treat as "empty"
  const DASHES = /^(?:[\u002D\u2010\u2011\u2012\u2013\u2014\u2212]+)$/;
  //            ASCII -, hyphen, non-breaking hyphen, figure dash, en dash, em dash, minus sign

  const rows = Array.from(table.rows);
  const csvLines = rows.map(row => {
    const cells = Array.from(row.cells).map(cell => {
      // get text, normalize spaces, trim
      let text = (cell.innerText || cell.textContent || "")
        .replace(/\u00A0/g, ' ')       // nbsp -> space
        .replace(/\s+/g, ' ')          // collapse whitespace/newlines
        .trim();

      // If the cell is only dashes (any of the above), treat as empty
      if (DASHES.test(text)) text = "";

      // Optionally: if you want to force truly empty cells when there's only punctuation:
      // if (/^[\s\-\–\—\u2010-\u2015\u2212]*$/.test(text)) text = "";

      // Escape quotes by doubling them, then wrap in quotes
      text = `"${text.replaceAll(`"`, `""`)}"`;
      return text;
    });
    return cells.join(",");
  });

  // Add BOM so Excel detects UTF-8, and CRLF line endings for compatibility
  const csvString = "\uFEFF" + csvLines.join("\r\n");
  const blob = new Blob([csvString], { type: "text/csv;charset=utf-8" });

  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = filename || "export.csv";
  document.body.appendChild(link);
  link.click();
  link.remove();
}

function exportOutcomeMatrixToCSV(tableId, filename) {
  const table = document.getElementById(tableId);
  const rows = table.querySelectorAll("tr");
  let csv = [];

  rows.forEach(row => {
    let rowData = [];
    const cells = row.querySelectorAll("th, td");

    cells.forEach(cell => {
      const title = cell.getAttribute("title");
      if (title) {
        // Extract numbers from the tooltip
        const match = title.match(/🟥 (\d+) 🟧 (\d+) 🟩 (\d+)/);
        if (match) {
          rowData.push(`R:${match[1]} A:${match[2]} G:${match[3]}`);
        } else {
          rowData.push("");
        }
      } else {
        // For student name or OFR header
        rowData.push(cell.textContent.trim());
      }
    });

    csv.push(rowData.join(","));
  });

  // Trigger download
  const blob = new Blob([csv.join("\n")], { type: "text/csv" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}
