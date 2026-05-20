// Polyglot Talk — room (active call) page
//
// Drives 3 stages:
//   1. PRE-JOIN  — if the user has only an invite_token (guest), show
//                  a form to enter name + language, then fetch a real
//                  participant token via /api/talk/rooms/<id>/join.
//   2. CONNECTING — while LiveKit handshake completes.
//   3. CALL      — active call. Video grid + mic/cam/hangup controls.
//
// Pass-through state — `window.TALK_CONFIG` is set by the template:
//   roomId          — uuid
//   inviteToken     — short URL-safe token (for guests)
//   prefilledToken  — full JWT (for host who created the room) — may be null
//   liveKitUrl      — wss://polyglot-livekit.fly.dev
//   apiBase         — '/api/talk'

(function () {
  const cfg = window.TALK_CONFIG;
  if (!cfg) {
    console.error('[Polyglot Talk] no TALK_CONFIG set');
    return;
  }

  const LK = window.LivekitClient;
  if (!LK) {
    console.error('[Polyglot Talk] LiveKit client SDK not loaded');
    return;
  }

  // ── DOM refs ─────────────────────────────────────────────────────
  const preJoinView    = document.getElementById('preJoinView');
  const connectingView = document.getElementById('connectingView');
  const connectingDetail = document.getElementById('connectingDetail');
  const callView       = document.getElementById('callView');
  const joinForm       = document.getElementById('joinForm');
  const joinErrorBox   = document.getElementById('joinErrorBox');
  const videoGrid      = document.getElementById('videoGrid');
  const callStatus     = document.getElementById('callStatus');
  const micToggleBtn   = document.getElementById('micToggleBtn');
  const camToggleBtn   = document.getElementById('camToggleBtn');
  const hangupBtn      = document.getElementById('hangupBtn');
  const copyInviteBtn  = document.getElementById('copyInviteBtn');

  // ── Stage management ────────────────────────────────────────────
  function showStage(stage) {
    preJoinView.style.display    = stage === 'prejoin'    ? 'flex' : 'none';
    connectingView.style.display = stage === 'connecting' ? 'flex' : 'none';
    callView.style.display       = stage === 'call'       ? 'flex' : 'none';
  }

  function showJoinError(msg) {
    joinErrorBox.textContent = msg;
    joinErrorBox.style.display = 'block';
  }

  function showConnectingDetail(msg) {
    connectingDetail.textContent = msg;
  }

  function toast(msg) {
    const el = document.createElement('div');
    el.className = 'toast';
    el.textContent = msg;
    document.body.appendChild(el);
    setTimeout(() => el.remove(), 3000);
  }

  // ── Determine the entry path ────────────────────────────────────
  // Three possible cases:
  //   A) ?t=<JWT> + host=1   → host who just created. Connect directly.
  //   B) ?t=<invite_token>   → guest with invite link. Show pre-join form.
  //   C) no token            → invalid URL. Show error.
  const urlParams = new URLSearchParams(window.location.search);
  const urlToken  = urlParams.get('t') || cfg.prefilledToken;
  const isHost    = urlParams.get('host') === '1';

  if (!urlToken) {
    document.body.innerHTML =
      '<div style="padding:40px;text-align:center;color:#EAE4D8;">' +
      '<h2>Invalid invite link</h2>' +
      '<p>This room link is missing the invite token.</p>' +
      '<p><a href="/talk" style="color:#D4A843;">Create a new call →</a></p>' +
      '</div>';
    return;
  }

  // ── Connect logic ───────────────────────────────────────────────
  let room = null;
  let localParticipantInfo = null;  // { name, lang }

  async function connectWithToken(jwt, participantInfo) {
    showStage('connecting');
    showConnectingDetail('Requesting camera and microphone access…');

    room = new LK.Room({
      adaptiveStream: true,
      dynacast:       true,
    });

    // Listeners — set up BEFORE connect so we don't miss early events
    room.on(LK.RoomEvent.ParticipantConnected,    onParticipantConnected);
    room.on(LK.RoomEvent.ParticipantDisconnected, onParticipantDisconnected);
    room.on(LK.RoomEvent.TrackSubscribed,         onTrackSubscribed);
    room.on(LK.RoomEvent.TrackUnsubscribed,       onTrackUnsubscribed);
    room.on(LK.RoomEvent.LocalTrackPublished,     onLocalTrackPublished);
    room.on(LK.RoomEvent.Disconnected,            onDisconnected);
    room.on(LK.RoomEvent.ConnectionStateChanged,  onConnectionStateChanged);

    try {
      showConnectingDetail('Connecting to media server…');
      await room.connect(cfg.liveKitUrl, jwt);
      console.log('[Polyglot Talk] connected to room:', room.name);

      showConnectingDetail('Publishing your camera and microphone…');
      await room.localParticipant.enableCameraAndMicrophone();

      localParticipantInfo = participantInfo;

      // Render local participant tile
      addLocalTile(room.localParticipant);

      // Render any participants already in the room
      for (const remoteP of room.remoteParticipants.values()) {
        addRemoteTile(remoteP);
        for (const pub of remoteP.trackPublications.values()) {
          if (pub.isSubscribed && pub.track) attachRemoteTrack(remoteP, pub.track);
        }
      }

      showStage('call');
      toast('Connected!');
    } catch (err) {
      console.error('[Polyglot Talk] connect error:', err);
      showConnectingDetail('');
      showStage('prejoin');
      showJoinError('Could not connect: ' + (err.message || err));
    }
  }

  // ── Guest join flow ─────────────────────────────────────────────
  async function handleGuestJoin(e) {
    e.preventDefault();
    joinErrorBox.style.display = 'none';

    const name = document.getElementById('guestName').value.trim();
    const lang = document.getElementById('guestLang').value;

    if (!name) { showJoinError('Please enter your name.'); return; }
    if (!lang) { showJoinError('Please choose your language.'); return; }

    const joinBtn = document.getElementById('joinBtn');
    joinBtn.disabled = true;
    joinBtn.querySelector('.btn-text').textContent = 'Joining…';

    try {
      const resp = await fetch(`${cfg.apiBase}/rooms/${cfg.roomId}/join`, {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({
          invite_token:  urlToken,
          display_name:  name,
          spoken_lang:   lang,
          reading_lang:  lang,
        }),
      });

      if (!resp.ok) {
        const err = await resp.json().catch(() => ({}));
        if (resp.status === 403) {
          showJoinError('This invite link is invalid or has expired.');
        } else if (resp.status === 404) {
          showJoinError('This room no longer exists.');
        } else if (resp.status === 410) {
          showJoinError('This call has ended.');
        } else {
          showJoinError(err.error || `Server error (HTTP ${resp.status}).`);
        }
        joinBtn.disabled = false;
        joinBtn.querySelector('.btn-text').textContent = 'Join Call';
        return;
      }

      const data = await resp.json();
      // Store guest info for the duration of the call (so a refresh keeps it)
      sessionStorage.setItem('talk_guest_name', name);
      sessionStorage.setItem('talk_guest_lang', lang);

      await connectWithToken(data.token, { name, lang });

    } catch (err) {
      console.error('[Polyglot Talk] join error:', err);
      showJoinError('Could not reach the server. Check your connection.');
      joinBtn.disabled = false;
      joinBtn.querySelector('.btn-text').textContent = 'Join Call';
    }
  }

  if (joinForm) joinForm.addEventListener('submit', handleGuestJoin);

  // ── Decide entry path on page load ──────────────────────────────
  if (isHost && urlToken) {
    // Host with full JWT — connect immediately
    const hostName = sessionStorage.getItem('talk_host_name') || 'Host';
    const hostLang = sessionStorage.getItem('talk_host_lang') || 'en';
    connectWithToken(urlToken, { name: hostName, lang: hostLang });
  } else if (urlToken) {
    // Guest with invite_token — show pre-join form
    // Pre-fill name/lang if guest had connected previously
    const cachedName = sessionStorage.getItem('talk_guest_name');
    const cachedLang = sessionStorage.getItem('talk_guest_lang');
    if (cachedName) document.getElementById('guestName').value = cachedName;
    if (cachedLang) document.getElementById('guestLang').value = cachedLang;
    showStage('prejoin');
  }

  // ── Room event handlers ─────────────────────────────────────────
  function onConnectionStateChanged(state) {
    console.log('[Polyglot Talk] connection state:', state);
    if (state === LK.ConnectionState.Reconnecting) {
      callStatus.textContent = '● Reconnecting…';
      callStatus.style.color = '#EEC96A';
    } else if (state === LK.ConnectionState.Connected) {
      callStatus.textContent = '● Connected';
      callStatus.style.color = '#6FE38A';
    }
  }

  function onDisconnected(reason) {
    console.log('[Polyglot Talk] disconnected:', reason);
    callStatus.textContent = '● Disconnected';
    callStatus.style.color = '#ff7878';
  }

  function onParticipantConnected(participant) {
    console.log('[Polyglot Talk] participant joined:', participant.identity);
    toast(`${participantDisplayName(participant)} joined`);
    addRemoteTile(participant);
  }

  function onParticipantDisconnected(participant) {
    console.log('[Polyglot Talk] participant left:', participant.identity);
    toast(`${participantDisplayName(participant)} left`);
    removeTile(participant.sid);
  }

  function onTrackSubscribed(track, publication, participant) {
    attachRemoteTrack(participant, track);
  }

  function onTrackUnsubscribed(track, publication, participant) {
    detachTrack(track);
  }

  function onLocalTrackPublished(publication, participant) {
    if (publication.kind === 'video' && publication.track) {
      const tile = document.querySelector(`[data-sid="${participant.sid}"]`);
      if (tile) {
        const video = tile.querySelector('video');
        if (video) publication.track.attach(video);
      }
    }
  }

  // ── Tile rendering ──────────────────────────────────────────────
  function participantDisplayName(p) {
    return p.name || p.identity || 'Participant';
  }

  function participantLang(p) {
    try {
      const meta = JSON.parse(p.metadata || '{}');
      return (meta.spoken_lang || '').toUpperCase();
    } catch { return ''; }
  }

  function addLocalTile(localP) {
    const name = localParticipantInfo?.name || 'You';
    const lang = (localParticipantInfo?.lang || '').toUpperCase();
    const tile = makeTile(localP.sid, name + ' (you)', lang, true);
    videoGrid.appendChild(tile);
  }

  function addRemoteTile(remoteP) {
    if (document.querySelector(`[data-sid="${remoteP.sid}"]`)) return;
    const tile = makeTile(remoteP.sid, participantDisplayName(remoteP), participantLang(remoteP), false);
    videoGrid.appendChild(tile);
  }

  function makeTile(sid, label, lang, isLocal) {
    const tile = document.createElement('div');
    tile.className = 'video-tile' + (isLocal ? ' is-local' : '');
    tile.dataset.sid = sid;
    tile.dataset.initial = label.substring(0,1).toUpperCase();

    const video = document.createElement('video');
    video.autoplay = true;
    video.playsInline = true;
    if (isLocal) video.muted = true;  // Don't play own audio back
    tile.appendChild(video);

    const labelEl = document.createElement('div');
    labelEl.className = 'video-tile-label';
    labelEl.innerHTML = `<span>${escapeHtml(label)}</span>` +
                       (lang ? ` <span class="video-tile-lang">${lang}</span>` : '');
    tile.appendChild(labelEl);

    const mutedTag = document.createElement('div');
    mutedTag.className = 'video-tile-muted';
    mutedTag.textContent = 'muted';
    tile.appendChild(mutedTag);

    return tile;
  }

  function attachRemoteTrack(participant, track) {
    const tile = document.querySelector(`[data-sid="${participant.sid}"]`);
    if (!tile) return;
    if (track.kind === 'video') {
      const video = tile.querySelector('video');
      if (video) track.attach(video);
    } else if (track.kind === 'audio') {
      // For audio, attach to a dedicated <audio> element on the tile
      let audio = tile.querySelector('audio');
      if (!audio) {
        audio = document.createElement('audio');
        audio.autoplay = true;
        tile.appendChild(audio);
      }
      track.attach(audio);
    }
  }

  function detachTrack(track) {
    track.detach().forEach(el => el.remove());
  }

  function removeTile(sid) {
    const tile = document.querySelector(`[data-sid="${sid}"]`);
    if (tile) tile.remove();
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, c => ({
      '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'
    }[c]));
  }

  // ── Controls ────────────────────────────────────────────────────
  micToggleBtn.addEventListener('click', async () => {
    if (!room) return;
    const enabled = micToggleBtn.dataset.on === 'true';
    await room.localParticipant.setMicrophoneEnabled(!enabled);
    micToggleBtn.dataset.on = (!enabled).toString();
    micToggleBtn.querySelector('.icon-mic-on').style.display  = !enabled ? '' : 'none';
    micToggleBtn.querySelector('.icon-mic-off').style.display = !enabled ? 'none' : '';
  });

  camToggleBtn.addEventListener('click', async () => {
    if (!room) return;
    const enabled = camToggleBtn.dataset.on === 'true';
    await room.localParticipant.setCameraEnabled(!enabled);
    camToggleBtn.dataset.on = (!enabled).toString();
    camToggleBtn.querySelector('.icon-cam-on').style.display  = !enabled ? '' : 'none';
    camToggleBtn.querySelector('.icon-cam-off').style.display = !enabled ? 'none' : '';
  });

  hangupBtn.addEventListener('click', async () => {
    if (room) await room.disconnect();
    window.location.href = '/talk';
  });

  copyInviteBtn.addEventListener('click', async () => {
    // The invite URL is the current page URL but with only the invite_token,
    // not the host JWT. We need to construct it from cfg.inviteToken.
    const inviteUrl = `${window.location.origin}/talk/${cfg.roomId}?t=${cfg.inviteToken}`;
    try {
      await navigator.clipboard.writeText(inviteUrl);
      toast('Invite link copied!');
    } catch {
      // Fallback: prompt
      window.prompt('Copy this invite link:', inviteUrl);
    }
  });

  // Cleanup on unload
  window.addEventListener('beforeunload', () => {
    if (room) room.disconnect();
  });

})();
