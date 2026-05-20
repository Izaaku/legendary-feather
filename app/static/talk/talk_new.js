// Polyglot Talk — new-room page
//
// Submits the create-room form. On success, redirects to the room URL
// with the host token in the query string so the room page can connect
// without re-prompting the host.

(function () {
  const form = document.getElementById('newRoomForm');
  const errorBox = document.getElementById('errorBox');
  const startBtn = document.getElementById('startBtn');
  const btnText = startBtn.querySelector('.btn-text');

  function showError(msg) {
    errorBox.textContent = msg;
    errorBox.style.display = 'block';
  }

  function hideError() {
    errorBox.style.display = 'none';
  }

  // ── Auth token from sessionStorage (set by /auth login) ───────────
  // For V1 of Polyglot Talk we require authenticated users to *host*
  // rooms (we need to know who's billing/quota). Guests join via the
  // invite link, no auth needed.
  function getAuthToken() {
    return sessionStorage.getItem('lf_token');
  }

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    hideError();

    const token = getAuthToken();
    if (!token) {
      showError('You need to sign in to host a call. ' +
                '<a href="/auth?next=/talk">Sign in →</a>');
      return;
    }

    const name = document.getElementById('hostName').value.trim();
    const lang = document.getElementById('hostLang').value;
    const topic = document.getElementById('topic').value.trim();

    if (!name) {
      showError('Please enter your name.');
      return;
    }

    startBtn.disabled = true;
    btnText.textContent = 'Creating call…';

    try {
      const resp = await fetch('/api/talk/rooms', {
        method: 'POST',
        headers: {
          'Authorization': 'Bearer ' + token,
          'Content-Type':  'application/json',
        },
        body: JSON.stringify({
          spoken_lang:  lang,
          reading_lang: lang,
          topic:        topic || null,
        }),
      });

      if (!resp.ok) {
        const errBody = await resp.json().catch(() => ({}));
        if (resp.status === 401) {
          showError('Your session expired. ' +
                    '<a href="/auth?next=/talk">Sign in again →</a>');
        } else {
          showError(errBody.error || `Server error (HTTP ${resp.status}).`);
        }
        return;
      }

      const data = await resp.json();

      // Save the host's display name + lang in sessionStorage so the room
      // page can use them without round-tripping.
      sessionStorage.setItem('talk_host_name', name);
      sessionStorage.setItem('talk_host_lang', lang);

      // Redirect to the room. Pass the host token in URL so room.html
      // can connect directly without a re-prompt.
      const roomUrl = `/talk/${data.room_id}?t=${encodeURIComponent(data.token)}&host=1`;
      window.location.href = roomUrl;

    } catch (err) {
      console.error('[Polyglot Talk] create room error:', err);
      showError('Could not reach the server. Check your connection and try again.');
    } finally {
      startBtn.disabled = false;
      btnText.textContent = 'Start Call';
    }
  });
})();
