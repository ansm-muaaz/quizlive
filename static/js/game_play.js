/**
 * QuizLive — Player Live Game View Controller
 * Handles mobile friendly button interactions, question polling, answers, and feedback.
 */

(function () {
  'use strict';

  const app = document.getElementById('playerGameApp');
  if (!app) return;

  const sessionId = app.dataset.sessionId;
  const participantId = app.dataset.participantId;
  let currentStatus = app.dataset.status || 'lobby';
  let pollInterval = null;
  let answeredQuestions = new Set();
  let lastAnswerResult = null; // { is_correct: bool, points: int }
  let lastQuestionIndex = -1;

  // Views
  const viewLobby = document.getElementById('playerViewLobby');
  const viewQuestion = document.getElementById('playerViewQuestion');
  const viewReveal = document.getElementById('playerViewReveal');
  const viewFinished = document.getElementById('playerViewFinished');

  // Question Elements
  const playerQBadge = document.getElementById('playerQBadge');
  const playerTimer = document.getElementById('playerTimer');
  const playerQText = document.getElementById('playerQText');
  const playerQImageContainer = document.getElementById('playerQImageContainer');
  const playerQImage = document.getElementById('playerQImage');
  const playerOptA = document.getElementById('playerOptA');
  const playerOptB = document.getElementById('playerOptB');
  const playerOptC = document.getElementById('playerOptC');
  const playerOptD = document.getElementById('playerOptD');
  const answerLockedNotice = document.getElementById('answerLockedNotice');
  const answerButtons = document.querySelectorAll('#playerAnswerButtons button');
  const playerScoreBadge = document.getElementById('playerScoreBadge');

  // Reveal Elements
  const revealIcon = document.getElementById('revealIcon');
  const revealHeading = document.getElementById('revealHeading');
  const pointsEarnedDisplay = document.getElementById('pointsEarnedDisplay');
  const playerCurrentRank = document.getElementById('playerCurrentRank');
  const playerCurrentScore = document.getElementById('playerCurrentScore');

  // Finished Elements
  const playerFinalRank = document.getElementById('playerFinalRank');
  const playerFinalScore = document.getElementById('playerFinalScore');

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
      const resp = await fetch(`/game/play/${sessionId}/state`);
      if (!resp.ok) return;
      const data = await resp.json();
      renderState(data);
    } catch (err) {
      console.error('Error polling player state:', err);
    }
  }

  function renderState(state) {
    if (state.status !== currentStatus) {
      showView(state.status);
    }

    // Update global score pill
    if (playerScoreBadge && state.my_score !== undefined) {
      playerScoreBadge.textContent = `${state.my_score} pts`;
    }

    if (state.status === 'question') {
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
  function renderQuestion(state) {
    const q = state.question;
    if (!q) return;

    // Reset buttons when a new question arrives
    if (lastQuestionIndex !== state.current_question) {
      lastQuestionIndex = state.current_question;
      lastAnswerResult = null;
      answerButtons.forEach(btn => {
        btn.removeAttribute('disabled');
        btn.classList.remove('opacity-50');
      });
      answerLockedNotice.classList.add('d-none');
    }

    // If server says this player already answered this question
    if (state.already_answered) {
      lockAnswerButtons();
    }

    playerQBadge.textContent = `Question ${state.current_question} / ${state.total_questions}`;
    playerQText.textContent = q.question_text;
    playerOptA.textContent = q.option_a;
    playerOptB.textContent = q.option_b;
    playerOptC.textContent = q.option_c;
    playerOptD.textContent = q.option_d;

    if (q.image_url) {
      playerQImage.src = q.image_url;
      playerQImageContainer.classList.remove('d-none');
    } else {
      playerQImageContainer.classList.add('d-none');
    }

    // Timer display
    if (state.time_remaining !== undefined && state.time_remaining !== null) {
      const rem = Math.max(0, Math.ceil(state.time_remaining));
      playerTimer.textContent = rem;
      if (rem <= 5) {
        playerTimer.classList.add('timer-warning');
      } else {
        playerTimer.classList.remove('timer-warning');
      }
    }
  }

  function renderReveal(state) {
    if (lastAnswerResult) {
      if (lastAnswerResult.is_correct) {
        revealIcon.textContent = '🎉';
        revealHeading.textContent = 'Correct!';
        revealHeading.className = 'fw-bold mb-1 text-success';
        pointsEarnedDisplay.textContent = `+${lastAnswerResult.points} pts`;
        pointsEarnedDisplay.className = 'fs-4 fw-bold text-success mb-3';
      } else {
        revealIcon.textContent = '❌';
        revealHeading.textContent = 'Incorrect!';
        revealHeading.className = 'fw-bold mb-1 text-danger';
        pointsEarnedDisplay.textContent = '+0 pts';
        pointsEarnedDisplay.className = 'fs-4 fw-bold text-muted mb-3';
      }
    } else {
      revealIcon.textContent = '⏰';
      revealHeading.textContent = "Time's Up!";
      revealHeading.className = 'fw-bold mb-1 text-warning';
      pointsEarnedDisplay.textContent = '+0 pts';
      pointsEarnedDisplay.className = 'fs-4 fw-bold text-muted mb-3';
    }

    // Compute player's rank from leaderboard
    const lb = state.leaderboard || [];
    let myRank = '—';
    const idx = lb.findIndex(p => p.nickname === state.my_nickname);
    if (idx !== -1) {
      myRank = `#${idx + 1}`;
    }

    playerCurrentRank.textContent = myRank;
    playerCurrentScore.textContent = `Total Score: ${state.my_score || 0} pts`;
  }

  function renderFinished(state) {
    const lb = state.leaderboard || [];
    let myRank = '—';
    const idx = lb.findIndex(p => p.nickname === state.my_nickname);
    if (idx !== -1) {
      myRank = `#${idx + 1}`;
    }

    playerFinalRank.textContent = myRank;
    playerFinalScore.textContent = `${state.my_score || 0} pts`;
  }

  function lockAnswerButtons() {
    answerButtons.forEach(btn => {
      btn.setAttribute('disabled', 'true');
      btn.classList.add('opacity-50');
    });
    answerLockedNotice.classList.remove('d-none');
  }

  // -------------------------------------------------------------------------
  // Answer Submission
  // -------------------------------------------------------------------------
  async function submitChoice(choice) {
    lockAnswerButtons();

    try {
      const resp = await fetch(`/game/play/${sessionId}/answer`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ choice: choice })
      });

      const resData = await resp.json();
      if (resp.ok) {
        lastAnswerResult = resData;
        if (playerScoreBadge && resData.total_score !== undefined) {
          playerScoreBadge.textContent = `${resData.total_score} pts`;
        }
      } else {
        console.warn('Answer response warning:', resData);
      }
    } catch (err) {
      console.error('Error submitting answer:', err);
    }
  }

  // Bind click handlers to 4 answer buttons
  answerButtons.forEach(btn => {
    btn.addEventListener('click', function () {
      const choice = this.dataset.choice;
      if (choice) {
        submitChoice(choice);
      }
    });
  });

  // Start polling every 1.5 seconds
  fetchState();
  pollInterval = setInterval(fetchState, 1500);

})();
