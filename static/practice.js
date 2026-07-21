/**
 * practice.js
 * ─────────────────────────────────────────────────────────────
 * Practice Test & Weak Spot Tracker for Quick Notes
 */

// ── State ──────────────────────────────────────────────────────
var practiceQuestions    = [];
var practiceAnswers      = {};
var questionStartTime    = 0;
var currentQuestionIndex = 0;
var testCompleted        = false;
var flashcardsCompleted  = false;
var weakSpotUnlocked     = false;
var weakSpotQuestions    = [];
var weakSpotAnswers      = {};
var weakSpotIndex        = 0;
var isSubmitting         = false;   // blocks double submits
var studyCycle           = 0;       // increments each time both are finished
var weakSpotsBuiltCycle  = -1;      // which cycle the current weak spots came from

// ── Inject styles for the submit button + loading dots ─────────
(function injectStyles() {
  var css = document.createElement("style");
  css.textContent = [
    ".qn-submit{transition:transform .12s ease,background .2s ease,box-shadow .2s ease;}",
    ".qn-submit:hover:not(:disabled){transform:translateY(-2px);box-shadow:0 6px 16px rgba(0,0,0,.18);filter:brightness(1.08);}",
    ".qn-submit:active:not(:disabled){transform:translateY(1px) scale(.985);}",
    ".qn-dots{display:inline-flex;gap:6px;align-items:center;justify-content:center;}",
    ".qn-dots span{width:8px;height:8px;border-radius:50%;background:currentColor;display:inline-block;animation:qnBounce 1s infinite ease-in-out;}",
    ".qn-dots span:nth-child(2){animation-delay:.15s;}",
    ".qn-dots span:nth-child(3){animation-delay:.3s;}",
    "@keyframes qnBounce{0%,80%,100%{transform:translateY(0);opacity:.5;}40%{transform:translateY(-6px);opacity:1;}}",
    "#tab-test,#tab-weakspot{max-height:none;overflow:visible;}"
  ].join("");
  document.head.appendChild(css);
})();

// ── Helpers ────────────────────────────────────────────────────

// Claude sometimes leaves "A: answer" inside the question text.
// Strip it so open-ended questions never reveal their own answer.
function cleanQuestion(text) {
  if (!text) return "";
  var m = String(text).match(/^(.*?)[\s\/\-\u2013|]*\bA\s*:\s*.+$/);
  return (m ? m[1] : text).trim();
}

function calcAllowedSeconds(question, choices) {
  var qWords = String(question || "").trim().split(/\s+/).length;
  var cWords = choices ? choices.join(" ").trim().split(/\s+/).length : 0;
  return (qWords + cWords) * 2 + 10;
}

function isConfident(startTime, question, choices) {
  var elapsed = (Date.now() - startTime) / 1000;
  return elapsed <= calcAllowedSeconds(question, choices);
}

// Scroll the feedback into view so the user never hunts for it
function scrollIntoView(el) {
  if (!el) return;
  setTimeout(function () {
    try { el.scrollIntoView({ behavior: "smooth", block: "nearest" }); }
    catch (e) { el.scrollIntoView(); }
  }, 60);
}

function setLoading(btn) {
  if (!btn) return;
  btn.disabled = true;
  btn.dataset.label = btn.textContent;
  btn.innerHTML = "<span class='qn-dots'><span></span><span></span><span></span></span>";
}

// ── Generate Practice Test ─────────────────────────────────────
function startPracticeTest() {
  // Reuse the already-generated test instead of paying for a new one
  if (practiceQuestions.length > 0) {
    practiceAnswers      = {};
    currentQuestionIndex = 0;
    testCompleted        = false;
    document.getElementById("testNotStarted").style.display = "none";
    document.getElementById("testResults").style.display    = "none";
    showQuestion(0);
    return;
  }

  document.getElementById("testNotStarted").style.display = "none";
  document.getElementById("testLoading").style.display    = "block";

  var transcript = document.getElementById("tab-transcript").textContent ||
                   document.getElementById("tab-notes").textContent || "";

  fetch("/api/practice-test", {
    method:  "POST",
    headers: { "Content-Type": "application/json" },
    body:    JSON.stringify({ transcript: transcript })
  })
  .then(function (res) { return res.json(); })
  .then(function (data) {
    if (data.error) {
      document.getElementById("testLoading").style.display    = "none";
      document.getElementById("testNotStarted").style.display = "block";
      alert("Error generating test: " + data.error);
      return;
    }
    practiceQuestions    = (data.questions || []).map(function (q) {
      q.question = cleanQuestion(q.question);
      return q;
    });
    practiceAnswers      = {};
    currentQuestionIndex = 0;
    testCompleted        = false;
    document.getElementById("testLoading").style.display = "none";
    showQuestion(0);
  })
  .catch(function (err) {
    document.getElementById("testLoading").style.display    = "none";
    document.getElementById("testNotStarted").style.display = "block";
    alert("Error: " + err.message);
  });
}

// ── Show Question ──────────────────────────────────────────────
function showQuestion(idx) {
  if (idx >= practiceQuestions.length) { showTestResults(); return; }

  isSubmitting = false;
  var q    = practiceQuestions[idx];
  var wrap = document.getElementById("testQuestions");
  wrap.style.display = "block";
  questionStartTime  = Date.now();

  var typeLabel = q.type === "mc" ? "Multiple Choice" :
                  q.type === "tf" ? "True / False" : "Open Ended";

  var html = "<div style='margin-bottom:8px;font-size:12px;font-weight:600;color:var(--muted);letter-spacing:0.06em;'>" +
    "QUESTION " + (idx + 1) + " OF " + practiceQuestions.length +
    "<span style='float:right;background:var(--blue-light);color:var(--blue);padding:2px 10px;border-radius:20px;font-size:11px;'>" +
    typeLabel + "</span></div>" +
    "<div style='font-size:17px;font-weight:500;color:var(--text);margin-bottom:20px;line-height:1.5;'>" + q.question + "</div>";

  if (q.type === "mc") {
    html += "<div style='display:flex;flex-direction:column;gap:10px;'>";
    for (var i = 0; i < q.choices.length; i++) {
      html += "<button id='mc-" + i + "' class='qn-submit' onclick='answerMC(" + idx + "," + i + ")' " +
        "style='padding:13px 18px;background:var(--card);border:1px solid var(--border);border-radius:12px;" +
        "font-family:sans-serif;font-size:14px;color:var(--text);cursor:pointer;text-align:left;'>" +
        String.fromCharCode(65 + i) + ". " + q.choices[i] + "</button>";
    }
    html += "</div>";

  } else if (q.type === "tf") {
    html += "<div style='display:flex;gap:12px;'>" +
      "<button class='qn-submit' onclick='answerTF(" + idx + ",true)' style='flex:1;padding:14px;background:var(--card);border:1px solid var(--border);border-radius:12px;font-family:sans-serif;font-size:15px;font-weight:600;color:var(--text);cursor:pointer;'>True</button>" +
      "<button class='qn-submit' onclick='answerTF(" + idx + ",false)' style='flex:1;padding:14px;background:var(--card);border:1px solid var(--border);border-radius:12px;font-family:sans-serif;font-size:15px;font-weight:600;color:var(--text);cursor:pointer;'>False</button>" +
      "</div>";

  } else {
    html += "<textarea id='openEndedAnswer' placeholder='Type your answer here...' " +
      "style='width:100%;min-height:120px;background:var(--card);border:1px solid var(--border);border-radius:12px;" +
      "padding:14px;font-family:sans-serif;font-size:14px;color:var(--text);resize:vertical;outline:none;line-height:1.7;box-sizing:border-box;'></textarea>" +
      "<button id='qnSubmitBtn' class='qn-submit' onclick='submitOpenEnded(" + idx + ")' " +
      "style='width:100%;margin-top:10px;padding:13px;background:var(--blue);color:#fff;border:none;border-radius:12px;" +
      "font-family:sans-serif;font-size:14px;font-weight:600;cursor:pointer;'>Submit Answer</button>" +
      "<div id='openEndedFeedback' style='display:none;margin-top:14px;'></div>";
  }

  wrap.innerHTML = html;
}

// ── Answer MC ──────────────────────────────────────────────────
function answerMC(idx, choiceIdx) {
  if (isSubmitting) return;
  isSubmitting = true;

  var q         = practiceQuestions[idx];
  var confident = isConfident(questionStartTime, q.question, q.choices);
  var correct   = choiceIdx === q.correct_index;

  practiceAnswers[idx] = { correct: correct, confident: confident, type: "mc" };

  var btns = document.querySelectorAll("[id^='mc-']");
  for (var i = 0; i < btns.length; i++) {
    btns[i].disabled = true;
    if (i === q.correct_index) {
      btns[i].style.background  = "#EAF3DE";
      btns[i].style.borderColor = "#1D9E75";
      btns[i].style.color       = "#3B6D11";
    } else if (i === choiceIdx && !correct) {
      btns[i].style.background  = "#FCEBEB";
      btns[i].style.borderColor = "#D85A30";
      btns[i].style.color       = "#A32D2D";
    }
  }

  var wrap = document.getElementById("testQuestions");
  var fb   = document.createElement("div");
  fb.style.cssText = "margin-top:14px;padding:12px 16px;border-radius:12px;background:" +
    (correct ? "#EAF3DE" : "#FCEBEB") + ";color:" + (correct ? "#3B6D11" : "#A32D2D") +
    ";font-size:14px;font-weight:500;";

  if (correct && confident)      fb.textContent = "Correct! Great confidence.";
  else if (correct)              fb.textContent = "Correct, but took a while — review this concept.";
  else                           fb.textContent = "Incorrect. Correct answer: " + String.fromCharCode(65 + q.correct_index) + ". " + q.choices[q.correct_index];

  wrap.appendChild(fb);
  appendNextBtn(wrap);
  scrollIntoView(fb);
}

// ── Answer TF ──────────────────────────────────────────────────
function answerTF(idx, answer) {
  if (isSubmitting) return;
  isSubmitting = true;

  var q         = practiceQuestions[idx];
  var confident = isConfident(questionStartTime, q.question, ["True", "False"]);
  var correct   = answer === q.correct_answer;

  practiceAnswers[idx] = { correct: correct, confident: confident, type: "tf" };

  var wrap    = document.getElementById("testQuestions");
  var allBtns = wrap.querySelectorAll("button");
  for (var i = 0; i < allBtns.length; i++) allBtns[i].disabled = true;

  var fb = document.createElement("div");
  fb.style.cssText = "margin-top:14px;padding:12px 16px;border-radius:12px;background:" +
    (correct ? "#EAF3DE" : "#FCEBEB") + ";color:" + (correct ? "#3B6D11" : "#A32D2D") +
    ";font-size:14px;font-weight:500;";

  if (correct && confident)      fb.textContent = "Correct! Great confidence.";
  else if (correct)              fb.textContent = "Correct, but took a while — review this concept.";
  else                           fb.textContent = "Incorrect. Answer: " + (q.correct_answer ? "True" : "False") + ". " + (q.explanation || "");

  wrap.appendChild(fb);
  appendNextBtn(wrap);
  scrollIntoView(fb);
}

// ── Submit Open Ended ──────────────────────────────────────────
function submitOpenEnded(idx) {
  if (isSubmitting) return;

  var q      = practiceQuestions[idx];
  var answer = document.getElementById("openEndedAnswer").value.trim();
  if (!answer) return;

  isSubmitting  = true;
  var confident = isConfident(questionStartTime, q.question, null);
  var btn       = document.getElementById("qnSubmitBtn");
  setLoading(btn);

  fetch("/api/rate-answer", {
    method:  "POST",
    headers: { "Content-Type": "application/json" },
    body:    JSON.stringify({ question: q.question, answer: answer, model_answer: q.model_answer })
  })
  .then(function (res) { return res.json(); })
  .then(function (data) {
    var correct = data.score >= 7;
    practiceAnswers[idx] = { correct: correct, confident: confident, type: "open", score: data.score };

    if (btn && btn.parentNode) btn.parentNode.removeChild(btn);

    var fb = document.getElementById("openEndedFeedback");
    var bgColor = correct ? "#EAF3DE" : data.score >= 5 ? "#FAEEDA" : "#FCEBEB";
    var txColor = correct ? "#3B6D11" : data.score >= 5 ? "#854F0B" : "#A32D2D";
    fb.style.cssText = "display:block;padding:14px;border-radius:12px;background:" + bgColor + ";margin-top:14px;";
    fb.innerHTML = "<div style='font-size:16px;font-weight:700;color:" + txColor + ";margin-bottom:6px;'>Score: " +
      data.score + "/10</div><div style='font-size:14px;color:var(--text);line-height:1.6;'>" + data.feedback + "</div>";

    appendNextBtn(document.getElementById("testQuestions"));
    scrollIntoView(fb);
  })
  .catch(function (err) {
    isSubmitting = false;
    if (btn) { btn.disabled = false; btn.textContent = btn.dataset.label || "Submit Answer"; }
    alert("Could not rate answer: " + err.message);
  });
}

// ── Next Button (guards against duplicates) ────────────────────
function appendNextBtn(wrap) {
  if (!wrap || wrap.querySelector(".qn-next")) return;   // never add twice
  var next = document.createElement("button");
  next.className   = "qn-next qn-submit";
  next.textContent = currentQuestionIndex + 1 < practiceQuestions.length ? "Next Question" : "See Results";
  next.style.cssText = "width:100%;margin-top:12px;padding:13px;background:var(--blue);color:#fff;" +
    "border:none;border-radius:12px;font-family:sans-serif;font-size:14px;font-weight:600;cursor:pointer;";
  next.onclick = function () { currentQuestionIndex++; showQuestion(currentQuestionIndex); };
  wrap.appendChild(next);
}

// ── Test Results ───────────────────────────────────────────────
function showTestResults() {
  testCompleted = true;
  document.getElementById("testQuestions").style.display = "none";

  var total = practiceQuestions.length, correct = 0, confident = 0;
  for (var k in practiceAnswers) {
    if (practiceAnswers[k].correct)   correct++;
    if (practiceAnswers[k].confident) confident++;
  }

  var pct   = total > 0 ? Math.round((correct / total) * 100) : 0;
  var color = pct >= 80 ? "#1D9E75" : pct >= 60 ? "#854F0B" : "#A32D2D";
  var msg   = pct >= 80 ? "Great job!" : pct >= 60 ? "Good effort — keep studying!" : "Keep practicing — you will get there!";

  var resultsEl = document.getElementById("testResults");
  resultsEl.style.display = "block";
  resultsEl.innerHTML =
    "<div style='text-align:center;padding:24px 0;'>" +
    "<div style='font-size:48px;font-weight:700;color:" + color + ";margin-bottom:4px;'>" + pct + "%</div>" +
    "<div style='font-size:16px;color:var(--text);font-weight:500;margin-bottom:4px;'>" + correct + "/" + total + " correct</div>" +
    "<div style='font-size:14px;color:var(--muted);margin-bottom:20px;'>" + msg + "</div>" +
    "<div style='font-size:13px;color:var(--muted);margin-bottom:24px;'>Confident on " + confident + "/" + total + " questions</div>" +
    "<button onclick='retakePracticeTest()' class='qn-submit' style='padding:12px 28px;background:transparent;border:1px solid var(--border);" +
    "border-radius:12px;font-family:sans-serif;font-size:14px;color:var(--text);cursor:pointer;'>Retake Test</button>" +
    "</div>";

  markCycleProgress();
}

// Retake reuses the SAME questions — no new API call, no new cost
function retakePracticeTest() {
  document.getElementById("testResults").style.display   = "none";
  document.getElementById("testQuestions").style.display = "block";
  practiceAnswers      = {};
  currentQuestionIndex = 0;
  testCompleted        = false;
  showQuestion(0);
}

// ── Weak Spot Tracker ──────────────────────────────────────────
function markCycleProgress() {
  if (testCompleted && flashcardsCompleted) {
    studyCycle++;
    weakSpotUnlocked = true;

    var btn = document.getElementById("weakspotTabBtn");
    if (btn) {
      btn.style.opacity = "1";
      btn.style.cursor  = "pointer";
      btn.innerHTML     = "Weak Spots";
      btn.title         = "";
    }

    // First time: build immediately.
    // Later cycles: keep the old set, offer a refresh button instead.
    if (weakSpotsBuiltCycle === -1) buildWeakSpotTest();
    else                            showRefreshPrompt();
  }
}

// Kept for backwards compatibility with older calls
function checkWeakSpotUnlock() { markCycleProgress(); }

function showRefreshPrompt() {
  if (weakSpotsBuiltCycle >= studyCycle) return;
  var wrap = document.getElementById("weakspotContent");
  if (!wrap || document.getElementById("qnRefreshWeak")) return;

  var bar = document.createElement("div");
  bar.id = "qnRefreshWeak";
  bar.style.cssText = "margin-bottom:16px;padding:14px;border-radius:12px;background:#FAEEDA;text-align:center;";
  bar.innerHTML =
    "<div style='font-size:14px;color:#854F0B;margin-bottom:10px;'>You finished the flashcards and test again.</div>" +
    "<button onclick='buildWeakSpotTest()' class='qn-submit' style='padding:10px 22px;background:#D85A30;color:#fff;border:none;" +
    "border-radius:10px;font-family:sans-serif;font-size:14px;font-weight:600;cursor:pointer;'>Update my weak spots</button>";
  wrap.insertBefore(bar, wrap.firstChild);
}

function buildWeakSpotTest() {
  weakSpotQuestions = [];

  for (var i = 0; i < practiceQuestions.length; i++) {
    var a = practiceAnswers[i];
    if (a && (!a.correct || !a.confident)) weakSpotQuestions.push(practiceQuestions[i]);
  }

  if (window._weakFlashcards) weakSpotQuestions = weakSpotQuestions.concat(window._weakFlashcards);

  weakSpotIndex       = 0;
  weakSpotAnswers     = {};
  weakSpotsBuiltCycle = studyCycle;

  var content = document.getElementById("weakspotContent");
  if (!content) return;

  if (weakSpotQuestions.length === 0) {
    content.innerHTML =
      "<div style='text-align:center;padding:40px 0;'>" +
      "<div style='font-size:32px;margin-bottom:12px;'>🏆</div>" +
      "<div style='font-family:serif;font-size:20px;color:var(--text);'>No weak spots found!</div>" +
      "<div style='font-size:14px;color:var(--muted);margin-top:8px;'>You aced everything with confidence.</div>" +
      "</div>";
    return;
  }

  showWeakSpotQuestion();
}

function showWeakSpotQuestion() {
  isSubmitting = false;

  var idx = -1;
  for (var i = weakSpotIndex; i < weakSpotQuestions.length; i++) {
    var a = weakSpotAnswers[i];
    if (!a || !a.correct || !a.confident) { idx = i; break; }
  }

  if (idx === -1) { showWeakSpotResults(); return; }
  weakSpotIndex = idx;

  var q    = weakSpotQuestions[idx];
  var wrap = document.getElementById("weakspotContent");
  if (!wrap) return;
  questionStartTime = Date.now();

  var typeLabel = q.type === "mc" ? "Multiple Choice" :
                  q.type === "tf" ? "True / False" : "Open Ended";

  var html =
    "<div style='margin-bottom:8px;font-size:12px;font-weight:600;color:#D85A30;letter-spacing:0.06em;'>" +
    "WEAK SPOT " + (idx + 1) + " OF " + weakSpotQuestions.length +
    "<span style='float:right;background:#FCEBEB;color:#A32D2D;padding:2px 10px;border-radius:20px;font-size:11px;'>" +
    typeLabel + "</span></div>" +
    "<div style='font-size:17px;font-weight:500;color:var(--text);margin-bottom:20px;line-height:1.5;'>" +
    cleanQuestion(q.question) + "</div>";

  if (q.type === "mc" && q.choices) {
    html += "<div style='display:flex;flex-direction:column;gap:10px;'>";
    for (var j = 0; j < q.choices.length; j++) {
      html += "<button id='wmc-" + j + "' class='qn-submit' onclick='answerWeakMC(" + j + ")' " +
        "style='padding:13px 18px;background:var(--card);border:1px solid var(--border);border-radius:12px;" +
        "font-family:sans-serif;font-size:14px;color:var(--text);cursor:pointer;text-align:left;'>" +
        String.fromCharCode(65 + j) + ". " + q.choices[j] + "</button>";
    }
    html += "</div>";

  } else if (q.type === "tf") {
    html += "<div style='display:flex;gap:12px;'>" +
      "<button class='qn-submit' onclick='answerWeakTF(true)' style='flex:1;padding:14px;background:var(--card);border:1px solid var(--border);" +
      "border-radius:12px;font-family:sans-serif;font-size:15px;font-weight:600;color:var(--text);cursor:pointer;'>True</button>" +
      "<button class='qn-submit' onclick='answerWeakTF(false)' style='flex:1;padding:14px;background:var(--card);border:1px solid var(--border);" +
      "border-radius:12px;font-family:sans-serif;font-size:15px;font-weight:600;color:var(--text);cursor:pointer;'>False</button>" +
      "</div>";

  } else {
    html += "<textarea id='weakOpenAnswer' placeholder='Type your answer...' " +
      "style='width:100%;min-height:100px;background:var(--card);border:1px solid var(--border);border-radius:12px;" +
      "padding:14px;font-family:sans-serif;font-size:14px;color:var(--text);resize:vertical;outline:none;box-sizing:border-box;'></textarea>" +
      "<button id='qnWeakSubmitBtn' class='qn-submit' onclick='submitWeakOpen()' style='width:100%;margin-top:10px;padding:13px;background:#D85A30;color:#fff;" +
      "border:none;border-radius:12px;font-family:sans-serif;font-size:14px;font-weight:600;cursor:pointer;'>Submit</button>" +
      "<div id='weakOpenFeedback' style='display:none;margin-top:14px;'></div>";
  }

  wrap.innerHTML = html;
}

function answerWeakMC(choiceIdx) {
  if (isSubmitting) return;
  isSubmitting = true;

  var q         = weakSpotQuestions[weakSpotIndex];
  var confident = isConfident(questionStartTime, q.question, q.choices);
  var correct   = choiceIdx === q.correct_index;
  weakSpotAnswers[weakSpotIndex] = { correct: correct, confident: confident, type: "mc" };

  var btns = document.querySelectorAll("[id^='wmc-']");
  for (var i = 0; i < btns.length; i++) {
    btns[i].disabled = true;
    if (i === q.correct_index) { btns[i].style.background = "#EAF3DE"; btns[i].style.borderColor = "#1D9E75"; }
    else if (i === choiceIdx && !correct) { btns[i].style.background = "#FCEBEB"; btns[i].style.borderColor = "#D85A30"; }
  }

  var wrap = document.getElementById("weakspotContent");
  var fb   = document.createElement("div");
  fb.style.cssText = "margin-top:14px;padding:12px 16px;border-radius:12px;font-size:14px;font-weight:500;background:" +
    (correct && confident ? "#EAF3DE" : "#FCEBEB") + ";color:" + (correct && confident ? "#3B6D11" : "#A32D2D") + ";";

  if (correct && confident) fb.textContent = "Mastered!";
  else if (correct)         fb.textContent = "Correct, but not confident yet. You will see this again.";
  else                      fb.textContent = "Incorrect. Correct: " + String.fromCharCode(65 + q.correct_index) + ". " + q.choices[q.correct_index];

  wrap.appendChild(fb);
  appendWeakNextBtn(wrap);
  scrollIntoView(fb);
}

function answerWeakTF(answer) {
  if (isSubmitting) return;
  isSubmitting = true;

  var q         = weakSpotQuestions[weakSpotIndex];
  var confident = isConfident(questionStartTime, q.question, ["True", "False"]);
  var correct   = answer === q.correct_answer;
  weakSpotAnswers[weakSpotIndex] = { correct: correct, confident: confident, type: "tf" };

  var wrap    = document.getElementById("weakspotContent");
  var allBtns = wrap.querySelectorAll("button");
  for (var i = 0; i < allBtns.length; i++) allBtns[i].disabled = true;

  var fb = document.createElement("div");
  fb.style.cssText = "margin-top:14px;padding:12px 16px;border-radius:12px;font-size:14px;font-weight:500;background:" +
    (correct && confident ? "#EAF3DE" : "#FCEBEB") + ";color:" + (correct && confident ? "#3B6D11" : "#A32D2D") + ";";

  if (correct && confident) fb.textContent = "Mastered!";
  else if (correct)         fb.textContent = "Correct, but not confident yet.";
  else                      fb.textContent = "Incorrect. Answer: " + (q.correct_answer ? "True" : "False");

  wrap.appendChild(fb);
  appendWeakNextBtn(wrap);
  scrollIntoView(fb);
}

function submitWeakOpen() {
  if (isSubmitting) return;

  var q      = weakSpotQuestions[weakSpotIndex];
  var answer = document.getElementById("weakOpenAnswer").value.trim();
  if (!answer) return;

  isSubmitting  = true;
  var confident = isConfident(questionStartTime, q.question, null);
  var btn       = document.getElementById("qnWeakSubmitBtn");
  setLoading(btn);

  fetch("/api/rate-answer", {
    method:  "POST",
    headers: { "Content-Type": "application/json" },
    body:    JSON.stringify({ question: q.question, answer: answer, model_answer: q.model_answer })
  })
  .then(function (res) { return res.json(); })
  .then(function (data) {
    var correct = data.score >= 7;
    weakSpotAnswers[weakSpotIndex] = { correct: correct, confident: confident, type: "open", score: data.score };

    if (btn && btn.parentNode) btn.parentNode.removeChild(btn);

    var fb = document.getElementById("weakOpenFeedback");
    fb.style.cssText = "display:block;padding:14px;border-radius:12px;background:" +
      (correct && confident ? "#EAF3DE" : "#FCEBEB") + ";margin-top:14px;";
    fb.innerHTML = "<div style='font-size:16px;font-weight:700;color:" + (correct ? "#3B6D11" : "#A32D2D") + ";'>" +
      "Score: " + data.score + "/10" + (correct && confident ? " — Mastered!" : "") +
      "</div><div style='font-size:14px;margin-top:6px;color:var(--text);'>" + data.feedback + "</div>";

    appendWeakNextBtn(document.getElementById("weakspotContent"));
    scrollIntoView(fb);
  })
  .catch(function (err) {
    isSubmitting = false;
    if (btn) { btn.disabled = false; btn.textContent = btn.dataset.label || "Submit"; }
    alert("Could not rate answer: " + err.message);
  });
}

function appendWeakNextBtn(wrap) {
  if (!wrap || wrap.querySelector(".qn-next")) return;   // never add twice
  var next = document.createElement("button");
  next.className   = "qn-next qn-submit";
  next.textContent = "Next";
  next.style.cssText = "width:100%;margin-top:12px;padding:13px;background:#D85A30;color:#fff;" +
    "border:none;border-radius:12px;font-family:sans-serif;font-size:14px;font-weight:600;cursor:pointer;";
  next.onclick = function () { weakSpotIndex++; showWeakSpotQuestion(); };
  wrap.appendChild(next);
}

function showWeakSpotResults() {
  var content = document.getElementById("weakspotContent");
  if (!content) return;
  content.innerHTML =
    "<div style='text-align:center;padding:40px 0;'>" +
    "<div style='font-size:48px;margin-bottom:12px;'>🎯</div>" +
    "<div style='font-family:serif;font-size:22px;color:var(--text);margin-bottom:8px;'>All Weak Spots Cleared!</div>" +
    "<div style='font-size:14px;color:var(--muted);margin-bottom:24px;'>You have mastered every concept you were struggling with.</div>" +
    "<button onclick='replayWeakSpots()' class='qn-submit' style='padding:12px 28px;background:var(--blue);color:#fff;" +
    "border:none;border-radius:12px;font-family:sans-serif;font-size:14px;font-weight:600;cursor:pointer;'>Practice These Again</button>" +
    "</div>";
}

// Replay the SAME weak spots — the set only changes via "Update my weak spots"
function replayWeakSpots() {
  weakSpotIndex   = 0;
  weakSpotAnswers = {};
  showWeakSpotQuestion();
}

// ── Hook into flashcard completion ────────────────────────────
document.addEventListener("DOMContentLoaded", function () {
  setTimeout(function () {
    if (typeof window.showStudyDone === "function") {
      var _orig = window.showStudyDone;
      window.showStudyDone = function () {
        flashcardsCompleted    = true;
        window._weakFlashcards = [];
        if (typeof studyCards !== "undefined" && typeof studyQueue !== "undefined") {
          for (var i = 0; i < studyCards.length; i++) {
            if (studyQueue.indexOf(i) !== -1) {
              window._weakFlashcards.push({
                type: "open",
                question: cleanQuestion(studyCards[i].q),
                model_answer: studyCards[i].a
              });
            }
          }
        }
        markCycleProgress();
        _orig();
      };
    }
  }, 500);
});
