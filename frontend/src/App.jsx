import React, { useState, useEffect, useCallback } from 'react';

const API_BASE = 'http://localhost:8000';

const VALORANT_AGENTS = [
  'Jett',
  'Hush',
  'Reyna',
  'Raze',
  'Phoenix',
  'Yoru',
  'Iso',
  'Neon',
  'Waylay',
  'Sova',
  'Fade',
  'Skye',
  'KAY/O',
  'Breach',
  'Gekko',
  'Tejo',
  'Omen',
  'Brimstone',
  'Astra',
  'Harbor',
  'Viper',
  'Clove',
  'Cypher',
  'Killjoy',
  'Chamber',
  'Sage',
  'Vyse',
  'Deadlock',
];

const formatInterruptText = (payload) => {
  if (!payload) return '';
  if (typeof payload === 'string') return payload;
  if (typeof payload === 'object') {
    return payload.prompt || payload.drafted_directive || JSON.stringify(payload, null, 2);
  }
  return String(payload);
};

export default function App() {
  const [activeTab, setActiveTab] = useState('ingest');

  // Player & Match Lookup State
  const [apiKey, setApiKey] = useState('');
  const [geminiKey, setGeminiKey] = useState('');
  const [region, setRegion] = useState('na');
  const [name, setName] = useState('');
  const [tag, setTag] = useState('');
  const [recentGames, setRecentGames] = useState([]);
  const [loadingRecent, setLoadingRecent] = useState(false);
  const [selectedRecentMatchId, setSelectedRecentMatchId] = useState('');
  const [selectedAgent, setSelectedAgent] = useState('Jett');
  const [threadId, setThreadId] = useState('');

  const [loading, setLoading] = useState(false);
  const [progress, setProgress] = useState(0);
  const [progressMessage, setProgressMessage] = useState('');
  const [playbook, setPlaybook] = useState(null);
  const [roundReviews, setRoundReviews] = useState([]);
  const [roundFilter, setRoundFilter] = useState('all'); // 'all' | 'won' | 'lost'
  const [interruptPrompt, setInterruptPrompt] = useState('');
  const [coachFeedback, setCoachFeedback] = useState('');

  // Team Notes & History State
  const [matches, setMatches] = useState([]);
  const [selectedMatchId, setSelectedMatchId] = useState('');
  const [auditOverview, setAuditOverview] = useState(null);
  const [activeCoach, setActiveCoach] = useState('coach_alpha');
  const [teamMemories, setTeamMemories] = useState([]);
  const [newPrivateNote, setNewPrivateNote] = useState('');
  const [accessLogs, setAccessLogs] = useState([]);
  const [accessBanner, setAccessBanner] = useState(null);

  // Inline Note Edit State
  const [correctingId, setCorrectingId] = useState(null);
  const [correctionText, setCorrectionText] = useState('');

  const selectedTeam = activeCoach === 'coach_alpha' ? 'team_alpha' : 'team_bravo';

  useEffect(() => {
    if (!loading) {
      return;
    }

    const stages = [
      { pct: 14, label: 'Getting your match info...' },
      { pct: 30, label: 'Getting round 1 data...' },
      { pct: 48, label: 'Saving your headshots & kills...' },
      { pct: 66, label: 'Checking economy buys & site trades...' },
      { pct: 84, label: 'Asking AI coach for round-by-round notes...' },
      { pct: 93, label: 'Building your round-by-round cards...' },
    ];

    let idx = 0;
    setProgress(stages[0].pct);
    setProgressMessage(stages[0].label);

    const interval = setInterval(() => {
      idx = Math.min(idx + 1, stages.length - 1);
      setProgress(stages[idx].pct);
      setProgressMessage(stages[idx].label);
    }, 1400);

    return () => clearInterval(interval);
  }, [loading]);

  // Auto-load the player's last 5 games once API key, region, name, and tag are entered
  useEffect(() => {
    if (!apiKey.trim() || !name.trim() || !tag.trim()) {
      setRecentGames([]);
      setSelectedRecentMatchId('');
      return;
    }

    const timer = setTimeout(async () => {
      setLoadingRecent(true);
      try {
        const res = await fetch(`${API_BASE}/api/recent-matches`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            region,
            name: name.trim(),
            tag: tag.trim(),
            api_key: apiKey.trim(),
          }),
        });
        if (res.ok) {
          const data = await res.json();
          const list = Array.isArray(data.matches) ? data.matches : [];
          setRecentGames(list);
          if (list.length > 0) {
            setSelectedRecentMatchId(list[0].match_id);
            if (list[0].agent_played) {
              setSelectedAgent(list[0].agent_played);
            }
          }
        }
      } catch (err) {
        console.error('Could not load last 5 matches:', err);
      } finally {
        setLoadingRecent(false);
      }
    }, 600);

    return () => clearTimeout(timer);
  }, [apiKey, region, name, tag]);

  const loadAuditData = useCallback(
    async (matchIdToLoad, coachActor = activeCoach) => {
      try {
        const logsUrl = matchIdToLoad
          ? `${API_BASE}/api/audit/access-log?match_id=${encodeURIComponent(matchIdToLoad)}`
          : `${API_BASE}/api/audit/access-log`;
        const logsRes = await fetch(logsUrl);
        if (logsRes.ok) {
          const logsJson = await logsRes.json();
          setAccessLogs(logsJson.logs || []);
        }

        const team = coachActor === 'coach_alpha' ? 'team_alpha' : 'team_bravo';
        const memUrl = `${API_BASE}/api/audit/memories/${team}?actor=${encodeURIComponent(coachActor)}${
          matchIdToLoad ? `&match_id=${encodeURIComponent(matchIdToLoad)}` : ''
        }`;
        const memRes = await fetch(memUrl);
        if (memRes.ok) {
          const memJson = await memRes.json();
          setTeamMemories(memJson.memories || []);
        }

        if (matchIdToLoad) {
          const ovRes = await fetch(
            `${API_BASE}/api/audit/matches/${encodeURIComponent(matchIdToLoad)}/overview`
          );
          if (ovRes.ok) {
            const ovJson = await ovRes.json();
            setAuditOverview(ovJson);
            if (ovJson.interrupt) {
              setThreadId(ovJson.match_id);
              setInterruptPrompt(formatInterruptText(ovJson.interrupt));
              if (
                !coachFeedback &&
                typeof ovJson.interrupt === 'object' &&
                ovJson.interrupt.drafted_directive
              ) {
                setCoachFeedback(ovJson.interrupt.drafted_directive);
              }
            }
            if (ovJson.final_brief) {
              setPlaybook(ovJson.final_brief);
            }
          }
        }
      } catch (err) {
        console.error('Error loading coach room data:', err);
      }
    },
    [activeCoach, coachFeedback]
  );

  const fetchMatches = useCallback(
    async (preferredMatchId = null) => {
      try {
        const res = await fetch(`${API_BASE}/api/matches`);
        const data = await res.json();
        const matchList = Array.isArray(data) ? data : [];
        setMatches(matchList);
        const targetId =
          preferredMatchId ||
          selectedMatchId ||
          (matchList.length > 0 ? matchList[matchList.length - 1].match_id : '');
        if (targetId) {
          setSelectedMatchId(targetId);
          setThreadId((prev) => prev || targetId);
          await loadAuditData(targetId, activeCoach);
        } else {
          await loadAuditData('', activeCoach);
        }
      } catch (err) {
        console.error(err);
      }
    },
    [selectedMatchId, activeCoach, loadAuditData]
  );

  useEffect(() => {
    fetchMatches();
  }, [activeTab]);

  const handleIngest = async (e) => {
    e.preventDefault();
    setLoading(true);
    setPlaybook(null);
    setRoundReviews([]);
    setInterruptPrompt('');

    try {
      const res = await fetch(`${API_BASE}/api/ingest`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          region,
          name: name.trim(),
          tag: tag.trim(),
          api_key: apiKey.trim(),
          llm_api_key: geminiKey.trim() || null,
          selected_match_id: selectedRecentMatchId || null,
          agent_name: selectedAgent || null,
          thread_id: selectedRecentMatchId || null,
        }),
      });
      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.detail || 'Could not load that Ranked match.');
      }

      const activeThread = data.thread_id || data.match_id;
      setThreadId(activeThread);
      setSelectedMatchId(data.match_id);

      setProgress(100);
      setProgressMessage('Match data ready!');

      if (data.status === 'paused') {
        setInterruptPrompt(formatInterruptText(data.interrupt_prompt));
        if (
          typeof data.interrupt_prompt === 'object' &&
          data.interrupt_prompt?.drafted_directive
        ) {
          setCoachFeedback(data.interrupt_prompt.drafted_directive);
        }
      } else {
        setPlaybook(data.final_playbook || '');
        setRoundReviews(Array.isArray(data.round_reviews) ? data.round_reviews : []);
        setRoundFilter('all');
        setActiveTab('rounds');
      }

      await fetchMatches(data.match_id);
    } catch (err) {
      alert('Unable to load match right now: ' + err.message);
    } finally {
      setLoading(false);
    }
  };

  const handleResume = async (e) => {
    e.preventDefault();
    const activeThread = threadId || selectedMatchId;
    if (!activeThread) {
      alert('Please load a match first.');
      return;
    }
    setLoading(true);

    try {
      const res = await fetch(`${API_BASE}/api/resume`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          thread_id: activeThread,
          coach_feedback: coachFeedback.trim() || 'approved',
        }),
      });
      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.detail || 'Could not save your coaching plan.');
      }
      setProgress(100);
      setProgressMessage('Round-by-round review ready!');
      setPlaybook(data.final_playbook || '');
      setRoundReviews(Array.isArray(data.round_reviews) ? data.round_reviews : []);
      setRoundFilter('all');
      setInterruptPrompt('');
      setActiveTab('rounds');
      await fetchMatches(selectedMatchId || activeThread);
    } catch (err) {
      alert('Unable to save your coaching plan: ' + err.message);
    } finally {
      setLoading(false);
    }
  };

  const handleSwitchCoach = async (nextCoach) => {
    setActiveCoach(nextCoach);
    setAccessBanner(null);
    await loadAuditData(selectedMatchId, nextCoach);
  };

  const handleAddPrivateNote = async (e) => {
    e.preventDefault();
    if (!newPrivateNote.trim()) return;
    try {
      const res = await fetch(`${API_BASE}/api/audit/memories/${selectedTeam}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          actor: activeCoach,
          body: newPrivateNote.trim(),
          kind: 'note',
          match_id: selectedMatchId || null,
        }),
      });
      const data = await res.json();
      const teamLabel = selectedTeam === 'team_alpha' ? 'Team Alpha' : 'Team Bravo';
      setAccessBanner({
        allowed: Boolean(data.allowed),
        text: data.allowed
          ? `Saved private note for ${teamLabel}.`
          : `Blocked: ${data.error}`,
      });
      setNewPrivateNote('');
      await loadAuditData(selectedMatchId, activeCoach);
    } catch (err) {
      console.error(err);
    }
  };

  const handleBlockedAccessProbe = async (actorToTest, targetTeam = 'team_alpha') => {
    try {
      const res = await fetch(`${API_BASE}/api/audit/access-test`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          actor: actorToTest,
          action: 'read_private_memory',
          team: targetTeam,
          match_id: selectedMatchId || null,
        }),
      });
      const data = await res.json();
      const friendlyRole =
        actorToTest === 'coach_bravo'
          ? 'Coach Bravo'
          : actorToTest === 'economy_analyst'
          ? 'Economy Specialist'
          : actorToTest;
      const friendlyTeam = targetTeam === 'team_alpha' ? 'Team Alpha' : 'Team Bravo';
      setAccessBanner({
        allowed: Boolean(data.ok),
        text: data.ok
          ? `${friendlyRole} viewed ${friendlyTeam}'s private notes.`
          : `Blocked: ${friendlyRole} cannot view ${friendlyTeam}'s private notes.`,
      });
      await loadAuditData(selectedMatchId, activeCoach);
    } catch (err) {
      console.error(err);
    }
  };

  const handleSubmitCorrection = async (findingId) => {
    if (!correctionText.trim()) return;
    try {
      const res = await fetch(`${API_BASE}/api/audit/findings/${findingId}/correct`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          actor: 'spatial_analyst',
          new_body: correctionText.trim(),
        }),
      });
      if (!res.ok) {
        const errData = await res.json();
        alert(errData.detail || 'Could not update note.');
        return;
      }
      setCorrectingId(null);
      setCorrectionText('');
      await loadAuditData(selectedMatchId, activeCoach);
    } catch (err) {
      console.error(err);
    }
  };

  const friendlyRoleLabel = (actor) => {
    if (actor === 'economy_analyst') return 'Economy Specialist';
    if (actor === 'spatial_analyst') return 'Map & Entry Specialist';
    if (actor === 'head_coach') return 'Head Coach';
    if (actor === 'coach_alpha') return 'Coach Alpha';
    if (actor === 'coach_bravo') return 'Coach Bravo';
    return actor;
  };

  const friendlyActionLabel = (action) => {
    if (action === 'read_shared') return 'Read shared notes';
    if (action === 'write_shared') return 'Added shared note';
    if (action === 'correct_finding') return 'Updated round note';
    if (action === 'read_private_memory') return 'Viewed team notes';
    if (action === 'write_private_memory') return 'Added team note';
    if (action === 'publish_to_team_memory') return 'Shared plan with team';
    return action;
  };

  const friendlyTargetLabel = (target) => {
    if (!target) return '';
    return target
      .replace('team_alpha', 'Team Alpha')
      .replace('team_bravo', 'Team Bravo')
      .replace('coach_memories:', 'Team Notebook: ')
      .replace('tactical_findings:shared:', 'Shared Board: ');
  };

  const traceSteps = auditOverview?.trace || [
    {
      step: 1,
      agent: 'economy_analyst',
      label: '1. Economy & Buy Rounds → Map Specialist',
      stage_key: 'economy_done',
      completed: false,
      active: false,
      summary: 'Waiting to check round spending and eco/save calls.',
    },
    {
      step: 2,
      agent: 'spatial_analyst',
      label: '2. Map Control & Site Entries → Head Coach',
      stage_key: 'spatial_done',
      completed: false,
      active: false,
      summary: 'Waiting to check site pushes and opening fights.',
    },
    {
      step: 3,
      agent: 'head_coach',
      label: '3. Head Coach Game Plan & Approval',
      stage_key: 'awaiting_coach',
      completed: false,
      active: false,
      summary: 'Waiting for your review before sharing with the team.',
    },
  ];

  const formattedInterrupt = formatInterruptText(interruptPrompt);

  const filteredRounds = roundReviews.filter((r) => {
    if (roundFilter === 'won') return Boolean(r.won);
    if (roundFilter === 'lost') return !r.won;
    return true;
  });

  const wonCount = roundReviews.filter((r) => Boolean(r.won)).length;
  const lostCount = roundReviews.filter((r) => !r.won).length;

  const renderProgressBar = () =>
    loading && (
      <div className="rounded-lg border border-zinc-800 bg-zinc-950/90 p-3.5 space-y-2">
        <div className="flex items-center justify-between text-xs">
          <span className="font-medium text-cyan-300 flex items-center gap-2">
            <span className="h-2 w-2 rounded-full bg-cyan-400 animate-ping" />
            {progressMessage || 'Getting your match info...'}
          </span>
          <span className="font-mono text-zinc-400">{progress}%</span>
        </div>
        <div className="w-full h-2 rounded-full bg-zinc-800 overflow-hidden">
          <div
            className="h-full bg-gradient-to-r from-red-500 via-amber-400 to-cyan-400 transition-all duration-500 ease-out"
            style={{ width: `${progress}%` }}
          />
        </div>
      </div>
    );

  return (
    <div className="min-h-screen bg-zinc-950 text-zinc-50 flex font-sans selection:bg-red-500 selection:text-white bg-[url('https://4kwallpapers.com/images/walls/thumbs_3t/21087.jpeg')] bg-cover bg-center bg-fixed">
      <div className="absolute inset-0 bg-zinc-950/92 backdrop-blur-md pointer-events-none" />

      {/* Sidebar */}
      <aside className="relative z-10 w-72 bg-zinc-900/90 border-r border-zinc-800/80 p-6 flex flex-col justify-between shadow-2xl">
        <div className="space-y-6">
          <div className="px-2 py-1">
            <h2 className="text-lg font-bold tracking-tight text-zinc-100 flex items-center gap-2">
              <span className="h-2 w-2 rounded-full bg-red-500 animate-pulse"></span>
              COACH DESK
            </h2>
            <p className="text-xs text-zinc-400 mt-0.5">Valorant Ranked Match Helper</p>
          </div>

          <nav className="space-y-1.5">
            <button
              onClick={() => setActiveTab('ingest')}
              className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-md text-sm font-medium transition-all cursor-pointer ${
                activeTab === 'ingest'
                  ? 'bg-zinc-800 text-zinc-50 shadow-sm border border-zinc-700/50'
                  : 'text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800/40'
              }`}
            >
              <svg className="w-4 h-4 text-red-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M13 10V3L4 14h7v7l9-11h-7z" />
              </svg>
              Recent Ranked Matches
            </button>
            <button
              onClick={() => setActiveTab('rounds')}
              className={`w-full flex items-center justify-between px-3 py-2.5 rounded-md text-sm font-medium transition-all cursor-pointer ${
                activeTab === 'rounds'
                  ? 'bg-zinc-800 text-zinc-50 shadow-sm border border-zinc-700/50'
                  : 'text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800/40'
              }`}
            >
              <span className="flex items-center gap-3">
                <svg className="w-4 h-4 text-emerald-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" />
                </svg>
                Round-by-Round
              </span>
              {roundReviews.length > 0 && (
                <span className="text-[11px] font-mono px-2 py-0.5 rounded-full bg-zinc-900 text-cyan-300 border border-zinc-700">
                  {roundReviews.length}
                </span>
              )}
            </button>
            <button
              onClick={() => setActiveTab('database')}
              className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-md text-sm font-medium transition-all cursor-pointer ${
                activeTab === 'database'
                  ? 'bg-zinc-800 text-zinc-50 shadow-sm border border-zinc-700/50'
                  : 'text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800/40'
              }`}
            >
              <svg className="w-4 h-4 text-cyan-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M4 7v10c0 2.21 3.582 4 8 4s8-1.79 8-4V7M4 7c0 2.21 3.582 4 8 4s8-1.79 8-4M4 7c0-2.21 3.582-4 8-4s8 1.79 8 4m0 5c0 2.21-3.582 4-8 4s-8-1.79-8-4" />
              </svg>
              Team Notes & History
            </button>
          </nav>
        </div>

        <div className="bg-zinc-950/50 border border-zinc-800/60 rounded-lg p-3 text-xs text-zinc-400 space-y-1">
          <div className="font-semibold text-zinc-300">Coaching Bench</div>
          <div>Player: {name && tag ? `${name} #${tag}` : 'Enter a Riot ID'}</div>
          <div>Agent: {selectedAgent}</div>
          <div className="text-emerald-400 text-[11px] flex items-center gap-1 mt-1">
            ● Progress Saved Automatically
          </div>
        </div>
      </aside>

      {/* Main Container */}
      <main className="relative z-10 flex-1 p-10 overflow-y-auto max-w-5xl mx-auto space-y-8">
        {activeTab === 'ingest' && (
          <>
            <div className="space-y-1">
              <h1 className="text-2xl font-bold tracking-tight text-zinc-100">
                Valorant Ranked Coaching Assistant
              </h1>
              <p className="text-sm text-zinc-400">
                Pulls your last 5 Valorant Ranked matches, lets you choose which game and agent to review, and breaks down what you and your team could have done better round by round.
              </p>
            </div>

            {/* Player Lookup Form */}
            <div className="rounded-xl border border-zinc-800 bg-zinc-900/60 text-zinc-50 shadow-xl backdrop-blur-xl">
              <div className="p-6 border-b border-zinc-800/80">
                <h3 className="text-base font-semibold leading-none tracking-tight">
                  Pick a Match & Agent to Review
                </h3>
                <p className="text-sm text-zinc-400 mt-1">
                  Enter your match lookup key, your own Gemini API key, and your Riot ID—your last 5 matches will appear automatically so you can pick one.
                </p>
              </div>
              <form onSubmit={handleIngest} className="p-6 space-y-5">
                <div className="grid grid-cols-2 gap-4">
                  <div className="space-y-2">
                    <label className="text-xs font-medium leading-none text-zinc-300">Match Lookup Key</label>
                    <input
                      type="password"
                      value={apiKey}
                      onChange={(e) => setApiKey(e.target.value)}
                      className="flex h-9 w-full rounded-md border border-zinc-800 bg-zinc-950/80 px-3 py-1 text-sm shadow-sm placeholder:text-zinc-600 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-red-500"
                      placeholder="Paste your match lookup API key"
                      required
                    />
                  </div>
                  <div className="space-y-2">
                    <label className="text-xs font-medium leading-none text-zinc-300">Region</label>
                    <select
                      value={region}
                      onChange={(e) => setRegion(e.target.value)}
                      className="flex h-9 w-full rounded-md border border-zinc-800 bg-zinc-950/80 px-3 py-1 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-red-500 text-zinc-200"
                    >
                      <option value="na">North America</option>
                      <option value="eu">Europe</option>
                      <option value="ap">Asia Pacific</option>
                      <option value="kr">Korea</option>
                    </select>
                  </div>
                  <div className="space-y-2">
                    <label className="text-xs font-medium leading-none text-zinc-300">Riot ID Name</label>
                    <input
                      type="text"
                      value={name}
                      onChange={(e) => setName(e.target.value)}
                      placeholder="e.g. PlayerName"
                      required
                      className="flex h-9 w-full rounded-md border border-zinc-800 bg-zinc-950/80 px-3 py-1 text-sm shadow-sm placeholder:text-zinc-600 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-red-500"
                    />
                  </div>
                  <div className="space-y-2">
                    <label className="text-xs font-medium leading-none text-zinc-300">Tagline</label>
                    <input
                      type="text"
                      value={tag}
                      onChange={(e) => setTag(e.target.value)}
                      placeholder="e.g. NA1"
                      required
                      className="flex h-9 w-full rounded-md border border-zinc-800 bg-zinc-950/80 px-3 py-1 text-sm shadow-sm placeholder:text-zinc-600 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-red-500"
                    />
                  </div>

                  {/* Gemini API Key Input (No hardcoded key) */}
                  <div className="space-y-2 col-span-2">
                    <label className="text-xs font-medium leading-none text-zinc-300">
                      Your Gemini API Key (Optional if already set on the server)
                    </label>
                    <input
                      type="password"
                      value={geminiKey}
                      onChange={(e) => setGeminiKey(e.target.value)}
                      placeholder="Paste your own Gemini API key (get one at aistudio.google.com)"
                      className="flex h-9 w-full rounded-md border border-zinc-800 bg-zinc-950/80 px-3 py-1 text-sm shadow-sm placeholder:text-zinc-600 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-red-500"
                    />
                  </div>

                  {/* Auto-populated Last 5 Matches Dropdown */}
                  <div className="space-y-2">
                    <label className="text-xs font-medium leading-none text-zinc-300">
                      {loadingRecent ? 'Loading Last 5 Matches...' : 'Select From Your Last 5 Matches'}
                    </label>
                    <select
                      value={selectedRecentMatchId}
                      onChange={(e) => {
                        const chosenId = e.target.value;
                        setSelectedRecentMatchId(chosenId);
                        const found = recentGames.find((g) => g.match_id === chosenId);
                        if (found?.agent_played) {
                          setSelectedAgent(found.agent_played);
                        }
                      }}
                      className="flex h-9 w-full rounded-md border border-zinc-800 bg-zinc-950/80 px-3 py-1 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-red-500 text-zinc-200"
                    >
                      {recentGames.length === 0 ? (
                        <option value="">Latest Ranked Match (Auto)</option>
                      ) : (
                        recentGames.map((g) => (
                          <option key={g.match_id} value={g.match_id}>
                            {g.label}
                          </option>
                        ))
                      )}
                    </select>
                  </div>

                  {/* Agent Played Dropdown */}
                  <div className="space-y-2">
                    <label className="text-xs font-medium leading-none text-zinc-300">
                      Agent You Played
                    </label>
                    <select
                      value={selectedAgent}
                      onChange={(e) => setSelectedAgent(e.target.value)}
                      className="flex h-9 w-full rounded-md border border-zinc-800 bg-zinc-950/80 px-3 py-1 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-red-500 text-zinc-200"
                    >
                      {VALORANT_AGENTS.map((ag) => (
                        <option key={ag} value={ag}>
                          {ag}
                        </option>
                      ))}
                    </select>
                  </div>
                </div>

                <button
                  type="submit"
                  disabled={loading}
                  className="inline-flex items-center justify-center rounded-md text-sm font-medium transition-colors bg-zinc-50 text-zinc-900 shadow hover:bg-zinc-200 h-9 px-4 py-2 w-full mt-2 cursor-pointer disabled:opacity-50"
                >
                  {loading
                    ? 'Reviewing Your Match...'
                    : `Review Selected Match (${selectedAgent})`}
                </button>

                {renderProgressBar()}
              </form>
            </div>

            {/* Step-by-Step Coaching Breakdown */}
            <div className="rounded-xl border border-zinc-800 bg-zinc-900/60 p-6 space-y-4 shadow-xl backdrop-blur-xl">
              <div className="flex items-center justify-between">
                <div>
                  <h3 className="text-base font-semibold text-zinc-100">How the Coaching Review Flows</h3>
                  <p className="text-xs text-zinc-400 mt-0.5">
                    Economy check → Site & entry check → Your coaching call → Round-by-round review
                  </p>
                </div>
                {auditOverview?.map_name && (
                  <span className="px-2.5 py-1 rounded-full text-xs bg-cyan-950/80 text-cyan-300 border border-cyan-800">
                    Map: {auditOverview.map_name}
                  </span>
                )}
              </div>

              <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                {traceSteps.map((s) => (
                  <div
                    key={s.step}
                    className={`rounded-lg border p-4 space-y-2 ${
                      s.completed
                        ? 'border-emerald-700/60 bg-emerald-950/20'
                        : s.active
                        ? 'border-amber-500/60 bg-amber-950/20'
                        : 'border-zinc-800 bg-zinc-950/60'
                    }`}
                  >
                    <div className="flex items-center justify-between text-xs">
                      <span className="text-zinc-400">STEP {s.step}</span>
                      <span
                        className={
                          s.completed
                            ? 'text-emerald-400'
                            : s.active
                            ? 'text-amber-400'
                            : 'text-zinc-500'
                        }
                      >
                        {s.completed ? 'Done' : s.active ? 'Your Turn' : 'Up Next'}
                      </span>
                    </div>
                    <div className="text-sm font-semibold text-zinc-100">{s.label}</div>
                    <p className="text-xs text-zinc-300 leading-relaxed">{s.summary}</p>
                    {s.handoff_note && (
                      <div className="text-[11px] text-cyan-300/90 bg-zinc-950/70 p-2 rounded border border-zinc-800/80">
                        {s.handoff_note}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>

            {/* Coach Approval Box */}
            {formattedInterrupt && (
              <div className="rounded-xl border border-red-500/40 bg-red-950/20 text-zinc-50 shadow-xl backdrop-blur-xl p-6 space-y-4">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2 text-red-400 font-semibold text-base">
                    <svg className="w-5 h-5 animate-bounce" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
                    </svg>
                    Coach Review Needed Before Sharing
                  </div>
                  <span className="text-xs text-zinc-400">
                    {auditOverview?.map_name ? `Map: ${auditOverview.map_name}` : 'Paused for Coach'}
                  </span>
                </div>
                <div className="bg-zinc-950/80 border border-zinc-800/80 p-4 rounded-lg text-xs text-zinc-300 whitespace-pre-wrap leading-relaxed">
                  {formattedInterrupt}
                </div>
                <form onSubmit={handleResume} className="space-y-4 pt-2">
                  <div className="space-y-2">
                    <label className="text-xs font-medium text-zinc-300">
                      Your Call for the Team (adds straight to Team Alpha&apos;s game plan)
                    </label>
                    <textarea
                      value={coachFeedback}
                      onChange={(e) => setCoachFeedback(e.target.value)}
                      rows="3"
                      className="flex w-full rounded-md border border-zinc-800 bg-zinc-950/80 px-3 py-2 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-red-500 text-zinc-100 placeholder:text-zinc-600"
                      placeholder="Write your callout for the team, or type 'approved' to use the suggested plan..."
                    />
                  </div>
                  <button
                    type="submit"
                    disabled={loading}
                    className="inline-flex items-center justify-center rounded-md text-sm font-medium transition-colors bg-red-600 text-white hover:bg-red-500 h-9 px-4 py-2 w-full shadow-lg disabled:opacity-50 cursor-pointer"
                  >
                    {loading ? 'Building Round-by-Round Review...' : 'Approve & Open Round-by-Round Review'}
                  </button>
                  {renderProgressBar()}
                </form>
              </div>
            )}

            {/* Summary Review Output */}
            {playbook && (
              <div className="rounded-xl border border-zinc-800 bg-zinc-900/60 text-zinc-50 shadow-xl backdrop-blur-xl p-6 space-y-4">
                <div className="flex items-center justify-between border-b border-zinc-800/80 pb-3">
                  <h3 className="text-base font-semibold text-cyan-400">
                    Match Coaching Summary
                  </h3>
                  <button
                    type="button"
                    onClick={() => setActiveTab('rounds')}
                    className="px-3 py-1 rounded-md bg-cyan-600 hover:bg-cyan-500 text-xs font-semibold text-white cursor-pointer"
                  >
                    View Round-by-Round Cards →
                  </button>
                </div>
                <pre className="bg-zinc-950/90 p-4 rounded-lg text-xs text-zinc-300 overflow-x-auto whitespace-pre-wrap border border-zinc-800/80 leading-relaxed font-sans">
                  {playbook}
                </pre>
              </div>
            )}
          </>
        )}

        {activeTab === 'rounds' && (
          <div className="space-y-6">
            <div className="flex flex-wrap items-center justify-between gap-4">
              <div className="space-y-1">
                <h1 className="text-2xl font-bold tracking-tight text-zinc-100">
                  Round-by-Round Coaching Breakdown
                </h1>
                <p className="text-sm text-zinc-400">
                  Every round from {auditOverview?.map_name || 'your match'} as{' '}
                  <span className="text-cyan-400 font-medium">{selectedAgent}</span>—what happened and how to improve each round.
                </p>
              </div>
              <button
                type="button"
                onClick={() => setActiveTab('ingest')}
                className="px-3.5 py-2 rounded-md border border-zinc-700 bg-zinc-900 hover:bg-zinc-800 text-xs font-medium text-zinc-200 cursor-pointer"
              >
                ← Back to Match Picker
              </button>
            </div>

            {/* Filter Toggle: All Rounds / Won Rounds / Lost Rounds */}
            {roundReviews.length > 0 && (
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div className="flex items-center gap-1.5 bg-zinc-950 p-1 rounded-lg border border-zinc-800">
                  {[
                    { key: 'all', label: `All Rounds (${roundReviews.length})` },
                    { key: 'won', label: `Won Rounds (${wonCount})` },
                    { key: 'lost', label: `Lost Rounds (${lostCount})` },
                  ].map((item) => (
                    <button
                      key={item.key}
                      type="button"
                      onClick={() => setRoundFilter(item.key)}
                      className={`px-3 py-1.5 rounded-md text-xs font-semibold transition-colors cursor-pointer ${
                        roundFilter === item.key
                          ? 'bg-cyan-600 text-white'
                          : 'text-zinc-400 hover:text-zinc-200'
                      }`}
                    >
                      {item.label}
                    </button>
                  ))}
                </div>
                <span className="text-xs text-zinc-400">
                  Showing {filteredRounds.length} of {roundReviews.length} rounds
                </span>
              </div>
            )}

            {roundReviews.length === 0 ? (
              <div className="rounded-xl border border-zinc-800 bg-zinc-900/60 p-8 text-center space-y-2">
                <p className="text-sm text-zinc-300 font-medium">No round-by-round breakdown loaded yet.</p>
                <p className="text-xs text-zinc-400">
                  Pick a match and approve the coach callout to see Round 1, Round 2, Round 3, and every round in the match here.
                </p>
              </div>
            ) : filteredRounds.length === 0 ? (
              <div className="rounded-xl border border-zinc-800 bg-zinc-900/60 p-8 text-center space-y-2">
                <p className="text-sm text-zinc-300 font-medium">
                  No {roundFilter === 'won' ? 'won' : 'lost'} rounds in this match.
                </p>
                <button
                  type="button"
                  onClick={() => setRoundFilter('all')}
                  className="px-3 py-1.5 rounded-md bg-zinc-800 hover:bg-zinc-700 text-xs text-zinc-200 cursor-pointer"
                >
                  Show All Rounds
                </button>
              </div>
            ) : (
              <div className="space-y-4">
                {filteredRounds.map((rnd) => (
                  <div
                    key={rnd.round_num}
                    className="rounded-xl border border-zinc-800 bg-zinc-900/70 p-6 space-y-4 shadow-lg backdrop-blur-xl"
                  >
                    <div className="flex flex-wrap items-center justify-between gap-2 border-b border-zinc-800/80 pb-3">
                      <div className="flex items-center gap-3">
                        <span className="text-base font-bold text-zinc-100">
                          Round {rnd.round_num}
                        </span>
                        <span
                          className={`px-2.5 py-0.5 rounded-full text-xs font-semibold ${
                            rnd.won
                              ? 'bg-emerald-950 text-emerald-300 border border-emerald-700/70'
                              : 'bg-red-950 text-red-300 border border-red-700/70'
                          }`}
                        >
                          {rnd.won ? 'Round Won' : 'Round Lost'}
                        </span>
                        <span className="text-xs text-zinc-400">Area / Site: {rnd.site}</span>
                      </div>

                      <div className="text-xs font-mono text-zinc-400 flex flex-wrap gap-3">
                        <span>
                          Spend: {Number(rnd.team_spend || 0).toLocaleString()} vs{' '}
                          {Number(rnd.enemy_spend || 0).toLocaleString()}
                        </span>
                        <span>Untraded Deaths: {rnd.untraded_deaths}</span>
                      </div>
                    </div>

                    <p className="text-xs text-zinc-400 leading-relaxed">{rnd.what_happened}</p>

                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                      <div className="rounded-lg border border-cyan-900/50 bg-cyan-950/15 p-4 space-y-1.5">
                        <div className="text-xs font-semibold uppercase tracking-wide text-cyan-300">
                          What You Could Have Done Better ({selectedAgent})
                        </div>
                        <p className="text-xs text-zinc-200 leading-relaxed">{rnd.you_better}</p>
                      </div>

                      <div className="rounded-lg border border-amber-900/50 bg-amber-950/15 p-4 space-y-1.5">
                        <div className="text-xs font-semibold uppercase tracking-wide text-amber-300">
                          What Your Team Could Have Done Better
                        </div>
                        <p className="text-xs text-zinc-200 leading-relaxed">{rnd.team_better}</p>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {activeTab === 'database' && (
          <>
            <div className="flex flex-wrap items-center justify-between gap-4">
              <div className="space-y-1">
                <h1 className="text-2xl font-bold tracking-tight text-zinc-100">
                  Team Notes & Coaching History
                </h1>
                <p className="text-sm text-zinc-400">
                  Review past Ranked matches, edit round notes, keep each team&apos;s private notes separate, and see who checked what.
                </p>
              </div>
              <button
                onClick={() => fetchMatches(selectedMatchId)}
                className="px-3 py-1.5 rounded-md border border-zinc-700 bg-zinc-900 hover:bg-zinc-800 text-xs font-medium text-zinc-200 cursor-pointer"
              >
                Refresh
              </button>
            </div>

            {/* Match Picker */}
            <div className="space-y-2">
              <label className="text-xs font-medium text-zinc-300">Pick a Match</label>
              <select
                value={selectedMatchId}
                onChange={(e) => {
                  const id = e.target.value;
                  setSelectedMatchId(id);
                  setThreadId(id);
                  loadAuditData(id, activeCoach);
                }}
                className="flex h-9 w-full rounded-md border border-zinc-800 bg-zinc-900 px-3 py-1 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-cyan-500 text-zinc-200"
              >
                {matches.length === 0 && <option value="">No matches checked yet</option>}
                {matches.map((m, idx) => (
                  <option key={m.match_id} value={m.match_id}>
                    {m.map_name} — Match #{idx + 1} (
                    {m.pipeline_stage === 'completed'
                      ? 'Game Plan Ready'
                      : m.pipeline_stage === 'awaiting_coach'
                      ? 'Waiting for Coach'
                      : m.status}
                    )
                  </option>
                ))}
              </select>
            </div>

            {/* 1. Breakdown Summary */}
            {auditOverview && (
              <div className="rounded-xl border border-zinc-800 bg-zinc-900/60 p-6 space-y-4">
                <div className="flex items-center justify-between">
                  <h3 className="text-base font-semibold text-zinc-100">1. Match Breakdown Steps</h3>
                  <span className="text-xs text-cyan-400">
                    Map: {auditOverview.map_name}
                  </span>
                </div>
                <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                  {auditOverview.trace.map((step) => (
                    <div
                      key={step.step}
                      className="rounded-lg border border-zinc-800 bg-zinc-950/70 p-4 space-y-1.5"
                    >
                      <div className="flex items-center justify-between text-xs text-zinc-400">
                        <span>{friendlyRoleLabel(step.agent)}</span>
                        <span className={step.completed ? 'text-emerald-400' : 'text-amber-400'}>
                          {step.completed ? 'Finished' : 'In Progress'}
                        </span>
                      </div>
                      <div className="text-sm font-semibold text-zinc-100">{step.label}</div>
                      <p className="text-xs text-zinc-300">{step.summary}</p>
                    </div>
                  ))}
                </div>

                {/* Resume from here if still waiting on coach */}
                {auditOverview.interrupt && (
                  <div className="rounded-lg border border-amber-500/40 bg-amber-950/20 p-4 space-y-3">
                    <div className="text-xs font-semibold text-amber-300">
                      This Match Is Still Waiting for Your Coaching Call
                    </div>
                    <p className="text-xs text-zinc-300">
                      {formatInterruptText(auditOverview.interrupt)}
                    </p>
                    <form onSubmit={handleResume} className="flex gap-2">
                      <input
                        type="text"
                        value={coachFeedback}
                        onChange={(e) => setCoachFeedback(e.target.value)}
                        placeholder="Type 'approved' or your own callout..."
                        className="flex-1 h-9 rounded-md border border-zinc-700 bg-zinc-950 px-3 text-xs text-zinc-100"
                      />
                      <button
                        type="submit"
                        disabled={loading}
                        className="px-4 h-9 rounded-md bg-emerald-600 hover:bg-emerald-500 text-xs font-semibold text-white cursor-pointer"
                      >
                        Approve & Share
                      </button>
                    </form>
                    {renderProgressBar()}
                  </div>
                )}
              </div>
            )}

            {/* 2. Shared Match Notes */}
            <div className="rounded-xl border border-zinc-800 bg-zinc-900/60 p-6 space-y-4">
              <div className="flex items-center justify-between">
                <div>
                  <h3 className="text-base font-semibold text-zinc-100">
                    2. Shared Match Notes
                  </h3>
                  <p className="text-xs text-zinc-400">
                    Current notes go into the team game plan. Older notes you update stay crossed out below so you can see what changed.
                  </p>
                </div>
              </div>

              {!auditOverview || auditOverview.findings.length === 0 ? (
                <p className="text-xs text-zinc-400">No match notes recorded yet.</p>
              ) : (
                <div className="space-y-3">
                  {auditOverview.findings.map((f) => {
                    const isOutdated = f.status !== 'active';
                    return (
                      <div
                        key={f.id}
                        className={`rounded-lg border p-4 space-y-2 ${
                          isOutdated
                            ? 'border-amber-800/50 bg-zinc-950/40 opacity-80'
                            : 'border-zinc-800 bg-zinc-950/80'
                        }`}
                      >
                        <div className="flex flex-wrap items-center justify-between gap-2 text-xs">
                          <div className="flex items-center gap-2">
                            <span className="px-2 py-0.5 rounded bg-zinc-800 text-cyan-300">
                              {friendlyRoleLabel(f.author)}
                            </span>
                            <span className="px-2 py-0.5 rounded bg-zinc-800 text-zinc-300">
                              {f.kind} (Update #{f.version})
                            </span>
                            {f.corrects_id && (
                              <span className="px-2 py-0.5 rounded bg-emerald-950 text-emerald-300 border border-emerald-800">
                                Revised note
                              </span>
                            )}
                          </div>
                          <div className="flex items-center gap-2">
                            <span
                              className={`px-2 py-0.5 rounded text-[11px] font-semibold ${
                                isOutdated
                                  ? 'bg-amber-950 text-amber-300 border border-amber-700'
                                  : 'bg-emerald-950 text-emerald-300 border border-emerald-700'
                              }`}
                            >
                              {isOutdated ? 'Replaced' : 'Current'}
                            </span>
                            {!isOutdated && f.kind !== 'directive' && (
                              <button
                                onClick={() => {
                                  setCorrectingId(f.id);
                                  setCorrectionText(f.body);
                                }}
                                className="px-2 py-0.5 rounded bg-zinc-800 hover:bg-zinc-700 text-zinc-200 cursor-pointer"
                              >
                                Edit Note
                              </button>
                            )}
                          </div>
                        </div>

                        <p
                          className={`text-xs leading-relaxed ${
                            isOutdated ? 'line-through text-zinc-400' : 'text-zinc-200'
                          }`}
                        >
                          {f.body}
                        </p>

                        {correctingId === f.id && (
                          <div className="pt-2 space-y-2 border-t border-zinc-800">
                            <textarea
                              rows="2"
                              value={correctionText}
                              onChange={(e) => setCorrectionText(e.target.value)}
                              className="w-full rounded-md border border-zinc-700 bg-zinc-900 p-2 text-xs text-zinc-100"
                            />
                            <div className="flex gap-2">
                              <button
                                onClick={() => handleSubmitCorrection(f.id)}
                                className="px-3 py-1 rounded bg-cyan-600 hover:bg-cyan-500 text-xs font-semibold text-white cursor-pointer"
                              >
                                Save Updated Note
                              </button>
                              <button
                                onClick={() => setCorrectingId(null)}
                                className="px-3 py-1 rounded bg-zinc-800 text-xs text-zinc-300 cursor-pointer"
                              >
                                Cancel
                              </button>
                            </div>
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              )}
            </div>

            {/* 3. Separate Team Notebooks */}
            <div className="rounded-xl border border-zinc-800 bg-zinc-900/60 p-6 space-y-4">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <h3 className="text-base font-semibold text-zinc-100">
                    3. Private Team Notebooks
                  </h3>
                  <p className="text-xs text-zinc-400">
                    Each coach only sees private notes for their own roster so strats stay private.
                  </p>
                </div>

                {/* Coach Alpha / Bravo Switcher */}
                <div className="flex items-center gap-2 bg-zinc-950 p-1 rounded-lg border border-zinc-800">
                  <button
                    onClick={() => handleSwitchCoach('coach_alpha')}
                    className={`px-3 py-1.5 rounded-md text-xs font-semibold transition-colors cursor-pointer ${
                      activeCoach === 'coach_alpha'
                        ? 'bg-cyan-600 text-white'
                        : 'text-zinc-400 hover:text-zinc-200'
                    }`}
                  >
                    Coach Alpha (Team Alpha)
                  </button>
                  <button
                    onClick={() => handleSwitchCoach('coach_bravo')}
                    className={`px-3 py-1.5 rounded-md text-xs font-semibold transition-colors cursor-pointer ${
                      activeCoach === 'coach_bravo'
                        ? 'bg-cyan-600 text-white'
                        : 'text-zinc-400 hover:text-zinc-200'
                    }`}
                  >
                    Coach Bravo (Team Bravo)
                  </button>
                </div>
              </div>

              {/* Privacy Check Buttons */}
              <div className="flex flex-wrap items-center gap-2 pt-1">
                <button
                  onClick={() => handleBlockedAccessProbe('coach_bravo', 'team_alpha')}
                  className="px-3 py-1.5 rounded-md bg-red-950/70 hover:bg-red-900/80 border border-red-700/70 text-xs font-semibold text-red-200 cursor-pointer"
                >
                  Try Viewing Team Alpha as Coach Bravo
                </button>
                <button
                  onClick={() => handleBlockedAccessProbe('economy_analyst', 'team_alpha')}
                  className="px-3 py-1.5 rounded-md bg-red-950/70 hover:bg-red-900/80 border border-red-700/70 text-xs font-semibold text-red-200 cursor-pointer"
                >
                  Try Viewing Team Alpha as Economy Specialist
                </button>
              </div>

              {accessBanner && (
                <div
                  className={`p-3 rounded-lg border text-xs ${
                    accessBanner.allowed
                      ? 'border-emerald-700 bg-emerald-950/40 text-emerald-200'
                      : 'border-red-600 bg-red-950/50 text-red-200'
                  }`}
                >
                  {accessBanner.text}
                </div>
              )}

              {/* Current Coach's Private Notes */}
              <div className="space-y-2">
                <div className="text-xs font-semibold text-zinc-300">
                  Private Notes for{' '}
                  <span className="text-cyan-400">
                    {activeCoach === 'coach_alpha' ? 'Team Alpha' : 'Team Bravo'}
                  </span>
                  :
                </div>
                {teamMemories.length === 0 ? (
                  <p className="text-xs text-zinc-500">No private notes yet.</p>
                ) : (
                  <div className="space-y-2">
                    {teamMemories.map((m) => (
                      <div
                        key={m.id}
                        className="rounded-lg border border-zinc-800 bg-zinc-950/80 p-3 text-xs space-y-1"
                      >
                        <div className="flex items-center justify-between text-[11px] text-zinc-400">
                          <span>
                            For{' '}
                            <strong className="text-cyan-300">
                              {m.owner === 'team_alpha' ? 'Team Alpha' : 'Team Bravo'}
                            </strong>{' '}
                            • {friendlyRoleLabel(m.author)}
                          </span>
                          <span>{m.kind === 'directive' ? 'Game Plan Call' : 'Coach Note'}</span>
                        </div>
                        <p className="text-zinc-200">{m.body}</p>
                      </div>
                    ))}
                  </div>
                )}

                <form onSubmit={handleAddPrivateNote} className="flex gap-2 pt-2">
                  <input
                    type="text"
                    value={newPrivateNote}
                    onChange={(e) => setNewPrivateNote(e.target.value)}
                    placeholder={`Write a private note for ${
                      activeCoach === 'coach_alpha' ? 'Team Alpha' : 'Team Bravo'
                    }...`}
                    className="flex-1 h-9 rounded-md border border-zinc-800 bg-zinc-950 px-3 text-xs text-zinc-100"
                  />
                  <button
                    type="submit"
                    className="px-4 h-9 rounded-md bg-zinc-100 hover:bg-zinc-200 text-zinc-900 text-xs font-semibold cursor-pointer"
                  >
                    Save Note
                  </button>
                </form>
              </div>
            </div>

            {/* 4. Activity & Privacy Log */}
            <div className="rounded-xl border border-zinc-800 bg-zinc-900/60 p-6 space-y-3">
              <h3 className="text-base font-semibold text-zinc-100">
                4. Activity & Privacy Log
              </h3>
              <div className="overflow-x-auto rounded-lg border border-zinc-800">
                <table className="w-full text-left text-xs">
                  <thead className="bg-zinc-950 text-zinc-400 uppercase">
                    <tr>
                      <th className="px-3 py-2">Who</th>
                      <th className="px-3 py-2">What They Tried</th>
                      <th className="px-3 py-2">Where</th>
                      <th className="px-3 py-2">Status</th>
                      <th className="px-3 py-2">Details</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-zinc-800/80">
                    {accessLogs.length === 0 ? (
                      <tr>
                        <td colSpan="5" className="px-3 py-4 text-center text-zinc-500">
                          No activity recorded yet.
                        </td>
                      </tr>
                    ) : (
                      accessLogs.map((entry) => {
                        const isDenied = entry.result === 'denied';
                        return (
                          <tr
                            key={entry.id}
                            className={
                              isDenied
                                ? 'bg-red-950/40 text-red-200'
                                : 'bg-zinc-950/50 text-zinc-300'
                            }
                          >
                            <td className="px-3 py-2 font-semibold">
                              {friendlyRoleLabel(entry.actor)}
                            </td>
                            <td className="px-3 py-2">{friendlyActionLabel(entry.action)}</td>
                            <td className="px-3 py-2 text-zinc-400">
                              {friendlyTargetLabel(entry.target)}
                            </td>
                            <td className="px-3 py-2">
                              <span
                                className={`px-2 py-0.5 rounded uppercase text-[10px] font-bold ${
                                  isDenied
                                    ? 'bg-red-600 text-white'
                                    : 'bg-emerald-950 text-emerald-300 border border-emerald-700'
                                }`}
                              >
                                {isDenied ? 'Blocked' : 'Allowed'}
                              </span>
                            </td>
                            <td className="px-3 py-2">{entry.reason}</td>
                          </tr>
                        );
                      })
                    )}
                  </tbody>
                </table>
              </div>
            </div>

            {/* Active Game Plan Preview */}
            {auditOverview?.final_brief && (
              <div className="rounded-xl border border-zinc-800 bg-zinc-900/60 text-zinc-50 shadow-xl p-6 space-y-3">
                <h3 className="text-sm font-semibold tracking-wide text-zinc-200">
                  Saved Team Game Plan
                </h3>
                <pre className="bg-zinc-950/90 p-4 rounded-lg text-xs text-zinc-300 overflow-x-auto whitespace-pre-wrap border border-zinc-800/80 leading-relaxed font-sans">
                  {auditOverview.final_brief}
                </pre>
              </div>
            )}
          </>
        )}
      </main>
    </div>
  );
}