/**
 * QuizLive — Host Live Game Controller
 * Handles real-time polling, state transitions, timers, and leaderboard display.
 */

(function () {
  'use strict';

  const app = document.getElementById('hostGameApp');
  if (!app) return;

  const sessionId = app.dataset.sessionId;
  let currentStatus = app.dataset.status || 'lobby';
  let pollInterval = null;
  let timerCountdownInterval = null;
  let remainingSeconds = 30;

  // Views
  const viewLobby = document.getElementById('viewLobby');
  const viewQuestion = document.getElementById('viewQuestion');
  const viewReveal = document.getElementById('viewReveal');
  const viewFinished = document.getElementById('viewFinished');

  // Buttons
  const btnStartGame = document.getElementById('btnStartGame');
  const btnSkipToReveal = document.getElementById('btnSkipToReveal');
  const btnNextQuestion = document.getElementById('btnNextQuestion');

  // Question Elements
  const qNumberBadge = document.getElementById('qNumberBadge');
  const qTextDisplay = document.getElementById('qTextDisplay');
  const qImageContainer = document.getElementById('qImageContainer');
  const qImageDisplay = document.getElementById('qImageDisplay');
  const optTextA = document.getElementById('optTextA');
  const optTextB = document.getElementById('optTextB');
  const optTextC = document.getElementById('optTextC');
  const optTextD = document.getElementById('optTextD');
  const timerDisplay = document.getElementById('timerDisplay');
  const answerCounter = document.getElementById('answerCounter');

  // Reveal Elements
  const correctLetterBadge = document.getElementById('correctLetterBadge');
  const correctTextDisplay = document.getElementById('correctTextDisplay');
  const countA = document.getElementById('countA');
  const countB = document.getElementById('countB');
  const countC = document.getElementById('countC');
  const countD = document.getElementById('countD');
  const revealLeaderboard = document.getElementById('revealLeaderboard');

  // Lobby Elements
  const participantCount = document.getElementById('participantCount');
  const participantsList = document.getElementById('participantsList');
  const waitingMsg = document.getElementById('waitingMsg');

  // Podium Elements
  const podium1Name = document.getElementById('podium1Name');
  const podium1Score = document.getElementById('podium1Score');
  const podium2Name = document.getElementById('podium2Name');
  const podium2Score = document.getElementById('podium2Score');
  const podium3Name = document.getElementById('podium3Name');
  const podium3Score = document.getElementById('podium3Score');
  const finalLeaderboardList = document.getElementById('finalLeaderboardList');

  // -------------------------------------------------------------------------
  // View Switcher
  // -------------------------------------------------------------------------
  function showView(status) {
    currentStatus = status;
    viewLobby.classList.add('d-none');
    viewQuestion.classList.add('d-none');
    viewReveal.classList.add('d-none');
    viewFinished.classList.add('d-none');

    if (status === 'lobby') {
      viewLobby.classList.remove('d-none');
    } else if (status === 'question') {
      viewQuestion.classList.remove('d-none');
    } else if (status === 'reveal') {
      viewReveal.classList.remove('d-none');
    } else if (status === 'finished') {
      viewFinished.classList.remove('d-none');
    }
  }

  // -------------------------------------------------------------------------
  // State Polling
  // -------------------------------------------------------------------------
  async function fetchState() {
    try {
      const resp = await fetch(`/game/host/${sessionId}/state`);
      if (!resp.ok) return;
      const data = await resp.json();
      renderState(data);
    } catch (err) {
      console.error('Error polling state:', err);
    }
  }

  function renderState(state) {
    if (state.status !== currentStatus) {
      showView(state.status);
    }

    if (state.status === 'lobby') {
      renderLobby(state);
    } else if (state.status === 'question') {
      renderQuestion(state);
    } else if (state.status === 'reveal') {
      renderReveal(state);
    } else if (state.status === 'finished') {
      renderFinished(state);
      if (pollInterval) {
        clearInterval(pollInterval);
        pollInterval = null;
      }
    }
  }

  // -------------------------------------------------------------------------
  // Renderers
  // -------------------------------------------------------------------------
  function renderLobby(state) {
    const count = state.participant_count || 0;
    participantCount.textContent = count;

    if (count > 0) {
      btnStartGame.removeAttribute('disabled');
      if (waitingMsg) waitingMsg.classList.add('d-none');

      // Update participant list
      const currentPills = new Set(Array.from(participantsList.children).map(el => el.dataset.nickname));
      const players = state.leaderboard || [];

      players.forEach(p => {
        if (!currentPills.has(p.nickname)) {
          const pill = document.createElement('div');
          pill.className = 'participant-pill';
          pill.dataset.nickname = p.nickname;
          pill.innerHTML = `<i class="bi bi-person-fill"></i> ${p.nickname}`;
          participantsList.appendChild(pill);
        }
      });
    } else {
      btnStartGame.setAttribute('disabled', 'true');
    }
  }

  function renderQuestion(state) {
    const q = state.question;
    if (!q) return;

    qNumberBadge.textContent = `Question ${state.current_question} / ${state.total_questions}`;
    qTextDisplay.textContent = q.question_text;
    optTextA.textContent = q.option_a;
    optTextB.textContent = q.option_b;
    optTextC.textContent = q.option_c;
    optTextD.textContent = q.option_d;

    if (q.image_url) {
      qImageDisplay.src = q.image_url;
      qImageContainer.classList.remove('d-none');
    } else {
      qImageContainer.classList.add('d-none');
    }

    answerCounter.textContent = `Answers: ${state.answer_count || 0} / ${state.participant_count || 0}`;

    // Timer sync from server
    if (state.time_remaining !== undefined && state.time_remaining !== null) {
      remainingSeconds = Math.max(0, Math.ceil(state.time_remaining));
      timerDisplay.textContent = remainingSeconds;
      if (remainingSeconds <= 5) {
        timerDisplay.classList.add('timer-warning');
      } else {
        timerDisplay.classList.remove('timer-warning');
      }

      // Automatically advance to reveal when time reaches 0
      if (remainingSeconds === 0 && currentStatus === 'question') {
        advanceQuestion();
      }
    }
  }

  function renderReveal(state) {
    const q = state.question;
    if (q) {
      correctLetterBadge.textContent = q.correct_option;
      const optKey = `option_${q.correct_option.toLowerCase()}`;
      correctTextDisplay.textContent = q[optKey] || '';
    }

    // Answer breakdown counts
    const bd = state.answer_breakdown || { A: 0, B: 0, C: 0, D: 0 };
    countA.textContent = bd.A || 0;
    countB.textContent = bd.B || 0;
    countC.textContent = bd.C || 0;
    countD.textContent = bd.D || 0;

    // Leaderboard
    const lb = state.leaderboard || [];
    revealLeaderboard.innerHTML = '';
    lb.slice(0, 5).forEach((p, idx) => {
      const item = document.createElement('div');
      item.className = 'leaderboard-item';
      item.innerHTML = `
        <div class="d-flex align-items-center gap-3">
          <div class="leaderboard-rank">#${idx + 1}</div>
          <span class="fw-bold fs-5">${p.nickname}</span>
        </div>
        <div class="leaderboard-score">${p.score} pts</div>
      `;
      revealLeaderboard.appendChild(item);
    });

    if (state.current_question >= state.total_questions) {
      btnNextQuestion.innerHTML = 'View Final Podium <i class="bi bi-trophy-fill ms-2"></i>';
    } else {
      btnNextQuestion.innerHTML = 'Next Question <i class="bi bi-arrow-right-circle-fill ms-2"></i>';
    }
  }

  function renderFinished(state) {
    const lb = state.leaderboard || [];

    if (lb[0]) {
      podium1Name.textContent = lb[0].nickname;
      podium1Score.textContent = `${lb[0].score} pts`;
    }
    if (lb[1]) {
      podium2Name.textContent = lb[1].nickname;
      podium2Score.textContent = `${lb[1].score} pts`;
    }
    if (lb[2]) {
      podium3Name.textContent = lb[2].nickname;
      podium3Score.textContent = `${lb[2].score} pts`;
    }

    finalLeaderboardList.innerHTML = '';
    lb.forEach((p, idx) => {
      const item = document.createElement('div');
      item.className = 'leaderboard-item';
      item.innerHTML = `
        <div class="d-flex align-items-center gap-3">
          <div class="leaderboard-rank">#${idx + 1}</div>
          <span class="fw-bold">${p.nickname}</span>
        </div>
        <div class="leaderboard-score">${p.score} pts</div>
      `;
      finalLeaderboardList.appendChild(item);
    });
  }

  // -------------------------------------------------------------------------
  // Actions
  // -------------------------------------------------------------------------
  async function startGame() {
    btnStartGame.setAttribute('disabled', 'true');
    try {
      const resp = await fetch(`/game/host/${sessionId}/start`, { method: 'POST' });
      if (resp.ok) {
        await fetchState();
      }
    } catch (err) {
      console.error('Error starting game:', err);
    }
  }

  async function advanceQuestion() {
    try {
      const resp = await fetch(`/game/host/${sessionId}/next`, { method: 'POST' });
      if (resp.ok) {
        await fetchState();
      }
    } catch (err) {
      console.error('Error advancing question:', err);
    }
  }

  // Event Listeners
  if (btnStartGame) {
    btnStartGame.addEventListener('click', startGame);
  }
  if (btnSkipToReveal) {
    btnSkipToReveal.addEventListener('click', advanceQuestion);
  }
  if (btnNextQuestion) {
    btnNextQuestion.addEventListener('click', advanceQuestion);
  }

  // Start initial polling loop (every 1.5 seconds)
  fetchState();
  pollInterval = setInterval(fetchState, 1500);

})();
