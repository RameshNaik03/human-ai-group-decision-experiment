import { useEffect, useRef, useState } from "react";

const wsUrl = () => `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws`;
const name = (label, me) => `Player ${label}${label === me ? " (you)" : ""}`;
const TITLE = "Group Decision Study";
// No vote = abstention. Only the count is shown, never who abstained.
const abstentions = (tally, labels) => labels.length - labels.reduce((s, l) => s + (tally[l] || 0), 0);
const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;

function useCountdown(endsAt) {
  const [left, setLeft] = useState(0);
  useEffect(() => {
    if (!endsAt) return;
    const tick = () => setLeft(Math.max(0, Math.ceil((endsAt - Date.now()) / 1000)));
    tick();
    const id = setInterval(tick, 250);
    return () => clearInterval(id);
  }, [endsAt]);
  return left;
}

export default function App() {
  const [stage, setStage] = useState("intro"); // intro | waiting | game | final | closed
  const [me, setMe] = useState(null);
  const [labels, setLabels] = useState(["A", "B", "C"]);
  const [phase, setPhase] = useState(null);    // {phase, round, rounds, endsAt, tally}
  const [messages, setMessages] = useState([]);
  const [votes, setVotes] = useState({});      // round -> target
  const [final, setFinal] = useState(null);
  const [error, setError] = useState(null);
  const [closedMsg, setClosedMsg] = useState(null);
  const wsRef = useRef(null);

  useEffect(() => () => wsRef.current?.close(), []);

  // Flash the tab title while a vote is pending so background tabs notice.
  const mustVote = stage === "game" && phase?.phase === "voting" && !votes[phase.round];
  useEffect(() => {
    if (!mustVote) {
      document.title = TITLE;
      return;
    }
    let on = true;
    document.title = "🗳️ Vote now!";
    const id = setInterval(() => {
      on = !on;
      document.title = on ? "🗳️ Vote now!" : TITLE;
    }, 1000);
    return () => {
      clearInterval(id);
      document.title = TITLE;
    };
  }, [mustVote]);

  const join = () => {
    const ws = new WebSocket(wsUrl());
    wsRef.current = ws;
    setStage("waiting");
    ws.onmessage = (e) => {
      const m = JSON.parse(e.data);
      switch (m.type) {
        case "welcome":
          setMe(m.you);
          setLabels(m.settings.labels);
          break;
        case "phase":
          setStage("game");
          setPhase({ ...m, endsAt: Date.now() + m.seconds * 1000 });
          if (m.phase === "break" && m.tally)
            setMessages((prev) => [...prev, { system: true, round: m.round, tally: m.tally }]);
          if (m.phase === "discussion" && m.round > 1)
            setMessages((prev) => [...prev, { system: true, text: `Round ${m.round} begins` }]);
          if (m.phase === "voting")
            setMessages((prev) => [...prev, { system: true, alert: true, text: "Discussion over: time to vote!" }]);
          break;
        case "chat":
          setMessages((prev) => [...prev, m]);
          break;
        case "vote_ack":
          setVotes((v) => ({ ...v, [m.round]: m.target }));
          break;
        case "final":
          setFinal(m);
          setStage("final");
          break;
        case "error":
          setError(m.message);
          break;
        case "timeout":
          setClosedMsg(m.message);
          setStage("closed");
          break;
      }
    };
    ws.onclose = () => setStage((s) => (s === "final" ? s : "closed"));
  };

  const send = (payload) => wsRef.current?.readyState === 1 && wsRef.current.send(JSON.stringify(payload));

  return (
    <div className="page">
      <header>
        <h1>Group Decision Study</h1>
        {me && <span className="badge">You are Player {me}</span>}
      </header>
      {error && <div className="error">{error}</div>}
      {stage === "intro" && <Intro onJoin={join} />}
      {stage === "waiting" && <Waiting />}
      {stage === "game" && phase && (
        <Game me={me} labels={labels} phase={phase} messages={messages}
              myVote={votes[phase.round]} send={send} />
      )}
      {stage === "final" && <Final me={me} labels={labels} final={final} />}
      {stage === "closed" && (
        <div className="card center">
          <p>{closedMsg || "The connection was closed."}</p>
          <button onClick={() => location.reload()}>{closedMsg ? "Try again" : "Start over"}</button>
        </div>
      )}
    </div>
  );
}

function Intro({ onJoin }) {
  return (
    <div className="card">
      <h2>Welcome</h2>
      <p>You will be matched with <b>two other participants</b>. All participants are anonymous and
        will be shown as <i>Player A</i>, <i>Player B</i> and <i>Player C</i>.</p>
      <p>Your group's task: chat and decide <b>who among the three of you should be the Decision
        Maker</b> for a later task. There are 2 short rounds of discussion (about 1 minute each).
        At the end of each round everyone votes. The final round's votes decide.</p>
      <button className="primary" onClick={onJoin}>Join the study</button>
    </div>
  );
}

function Waiting() {
  return (
    <div className="card center">
      <div className="spinner" />
      <h2>Waiting room</h2>
      <p>Waiting for other participants to join. The study starts automatically.</p>
      <p className="muted">Please keep this tab open.</p>
    </div>
  );
}

function Game({ me, labels, phase, messages, myVote, send }) {
  const left = useCountdown(phase.endsAt);
  const [text, setText] = useState("");
  const listRef = useRef(null);
  const voteRef = useRef(null);
  const canChat = phase.phase === "discussion";
  const voteOpen = phase.phase === "voting" && !myVote;

  useEffect(() => {
    listRef.current?.scrollTo(0, listRef.current.scrollHeight);
  }, [messages]);

  // Bring the vote buttons into view when voting starts (e.g. on small screens).
  useEffect(() => {
    if (phase.phase === "voting") voteRef.current?.scrollIntoView({ behavior: "smooth", block: "center" });
  }, [phase.phase, phase.round]);

  const submit = (e) => {
    e.preventDefault();
    if (!text.trim() || !canChat) return;
    send({ type: "chat", text: text.trim() });
    setText("");
  };

  const phaseText = {
    discussion: "Discussion",
    voting: "Voting",
    break: "Round results",
  }[phase.phase];

  return (
    <div className="game">
      <div className="status">
        <span>Round {phase.round} / {phase.rounds}</span>
        <span className={`phase ${phase.phase}`}>{phaseText}</span>
        <span className={`timer ${left <= 10 ? "low" : ""}`}>{left}s</span>
      </div>

      {voteOpen && (
        <div className="vote-banner" role="alert">
          Voting is open! Choose the Decision Maker below within <b>{left}s</b>. No vote counts as an abstention.
        </div>
      )}

      <div className="chat" ref={listRef}>
        {messages.length === 0 && <p className="muted center">No messages yet. Say hi!</p>}
        {messages.map((m, i) =>
          m.system ? (
            <div key={i} className={`system ${m.alert ? "alert" : ""}`}>
              {m.tally
                ? <>Round {m.round} votes: {labels.map((l) => `${name(l, me)}: ${m.tally[l]}`).join(" · ")}
                    {abstentions(m.tally, labels) > 0 && ` · ${plural(abstentions(m.tally, labels), "abstention")}`}</>
                : m.text}
            </div>
          ) : (
            <div key={i} className={`msg ${m.from === me ? "mine" : ""}`}>
              <span className={`who p${m.from}`}>{name(m.from, me)}</span>
              <span>{m.text}</span>
            </div>
          )
        )}
      </div>

      {canChat && (
        <form className="composer" onSubmit={submit}>
          <input value={text} maxLength={300} autoFocus placeholder="Type a message…"
                 onChange={(e) => setText(e.target.value)} />
          <button className="primary" disabled={!text.trim()}>Send</button>
        </form>
      )}

      {phase.phase === "voting" && (
        <div ref={voteRef} className={`vote ${voteOpen ? "open" : ""}`}>
          {myVote ? (
            <p>You voted for <b>{name(myVote, me)}</b>. Waiting for the others…</p>
          ) : (
            <>
              <p>Who should be the <b>Decision Maker</b>?</p>
              <div className="vote-buttons">
                {labels.map((l) => (
                  <button key={l} className={`p${l}`} onClick={() => send({ type: "vote", target: l })}>
                    {name(l, me)}
                  </button>
                ))}
              </div>
            </>
          )}
        </div>
      )}

      {phase.phase === "break" && (
        <div className="vote"><p>Next round starts in {left}s…</p></div>
      )}
    </div>
  );
}

function Final({ me, labels, final }) {
  return (
    <div className="card center">
      <h2>Results</h2>
      <p className="winner">
        <span className={`who p${final.winner}`}>Player {final.winner}</span> is the Decision Maker
        {final.winner === me && " — that's you!"}
      </p>
      <p className="muted">Decided by {final.method}.</p>
      <table>
        <thead>
          <tr><th>Round</th>{labels.map((l) => <th key={l}>{name(l, me)}</th>)}<th>No vote</th></tr>
        </thead>
        <tbody>
          {final.tallies.map((t, i) => {
            const n = abstentions(t, labels);
            return (
              <tr key={i}>
                <td>{i + 1}</td>
                {labels.map((l) => <td key={l}>{t[l]}</td>)}
                <td className="muted">{n ? plural(n, "abstention") : "–"}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <p>Thank you for participating!</p>
    </div>
  );
}
