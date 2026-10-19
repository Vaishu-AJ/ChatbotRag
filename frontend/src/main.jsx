import React, { useCallback, useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";

const api = async (url, options = {}) => {
  const response = await fetch(url, options);
  if (!response.ok) {
    let message = await response.text();
    try { message = JSON.parse(message).detail || message; } catch { /* keep plain text */ }
    throw new Error(message || `Request failed (${response.status})`);
  }
  return response.status === 204 ? null : response;
};

function App() {
  const [chats, setChats] = useState([]);
  const [activeId, setActiveId] = useState(null);
  const [documents, setDocuments] = useState([]);
  const [indexedChunks, setIndexedChunks] = useState(0);
  const [index, setIndex] = useState({ status: "idle", message: "" });
  const [providerReady, setProviderReady] = useState(false);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [uploading, setUploading] = useState(false);
  const endRef = useRef(null);
  const fileRef = useRef(null);
  const composerRef = useRef(null);
  const activeChat = chats.find((chat) => chat.id === activeId);

  const load = useCallback(async () => {
    try {
      const response = await api("/api/bootstrap");
      const data = await response.json();
      let history = data.chats || [];
      if (!history.length) {
        const created = await (await api("/api/chats", { method: "POST" })).json();
        history = [created];
      }
      setChats(history);
      setActiveId((current) => history.some((chat) => chat.id === current) ? current : history[0].id);
      setDocuments(data.documents || []);
      setIndexedChunks(data.indexed_chunks || 0);
      setIndex(data.index || { status: "idle", message: "" });
      setProviderReady(Boolean(data.provider_ready));
      setError("");
    } catch (cause) { setError(cause.message); }
  }, []);

  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    if (index.status !== "indexing" && index.status !== "queued") return undefined;
    const timer = window.setInterval(async () => {
      try {
        const response = await api("/api/index");
        const currentIndex = await response.json();
        setIndex(currentIndex);
        if (currentIndex.status === "ready") {
          const state = await (await api("/api/bootstrap")).json();
          setDocuments(state.documents || []);
          setIndexedChunks(state.indexed_chunks || 0);
          setProviderReady(Boolean(state.provider_ready));
        }
      } catch { /* temporary server errors are retried on the next interval */ }
    }, 1500);
    return () => window.clearInterval(timer);
  }, [index.status]);
  useEffect(() => { endRef.current?.scrollIntoView({ behavior: "smooth" }); }, [activeId, activeChat?.messages?.length]);

  const newChat = async () => {
    try {
      const chat = await (await api("/api/chats", { method: "POST" })).json();
      setChats((current) => [chat, ...current]);
      setActiveId(chat.id);
      setError("");
    } catch (cause) { setError(cause.message); }
  };

  const deleteChat = async (event, chatId) => {
    event.stopPropagation();
    try {
      await api(`/api/chats/${chatId}`, { method: "DELETE" });
      const remaining = chats.filter((chat) => chat.id !== chatId);
      if (activeId === chatId) {
        if (remaining.length) {
          setChats(remaining);
          setActiveId(remaining[0].id);
        } else {
          const fresh = await (await api("/api/chats", { method: "POST" })).json();
          setChats([fresh]);
          setActiveId(fresh.id);
        }
      } else setChats(remaining);
    } catch (cause) { setError(cause.message); }
  };

  const upload = async (event) => {
    const files = [...(event.target.files || [])];
    event.target.value = "";
    if (!files.length) return;
    setUploading(true); setError("");
    const body = new FormData();
    files.forEach((file) => body.append("files", file));
    try {
      const response = await api("/api/documents", { method: "POST", body });
      const result = await response.json();
      setDocuments((current) => [...new Set([...current, ...result.documents])]);
      setIndex(result.index);
    } catch (cause) { setError(cause.message); }
    finally { setUploading(false); }
  };

  const send = async (event) => {
    event?.preventDefault();
    const question = draft.trim();
    if (!question || busy || !activeChat) return;
    setDraft(""); setBusy(true); setError("");
    const userMessage = { role: "user", content: question };
    const assistantMessage = { role: "assistant", content: "" };
    setChats((current) => current.map((chat) => chat.id === activeId ? {
      ...chat,
      title: chat.messages?.some((message) => message.role === "user" && !isGreeting(message.content)) || isGreeting(question)
        ? chat.title : question.slice(0, 48),
      messages: [...(chat.messages || []), userMessage, assistantMessage],
    } : chat));
    try {
      const response = await api(`/api/chats/${activeId}/messages`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ question }),
      });
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let answer = "";
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        answer += decoder.decode(value, { stream: true });
        setChats((current) => current.map((chat) => chat.id === activeId ? {
          ...chat, messages: chat.messages.map((message, i, all) => i === all.length - 1 ? { ...message, content: answer } : message),
        } : chat));
      }
      setChats((current) => current.map((chat) => chat.id === activeId ? { ...chat, title: chatTitle([...chat.messages.slice(0, -2), userMessage]) } : chat));
    } catch (cause) {
      setError(cause.message);
      setChats((current) => current.map((chat) => chat.id === activeId ? {
        ...chat, messages: chat.messages.map((message, i, all) => i === all.length - 1 ? { ...message, content: `I couldn't complete that request: ${cause.message}` } : message),
      } : chat));
    } finally { setBusy(false); }
  };

  const tryQuestion = (question) => {
    setDraft(question);
    requestAnimationFrame(() => composerRef.current?.focus());
  };

  const canChat = documents.length > 0 && indexedChunks > 0 && providerReady && index.status !== "indexing" && index.status !== "queued";

  return <div className="app-shell">
    <aside className="sidebar">
      <div className="brand"><span className="brand-mark">✳</span><span>Ask<span className="brand-accent">Me</span></span></div>
      <button className="new-chat" onClick={newChat}><span>＋</span> Start a new chat</button>
      <div className="section-heading history-heading"><span>Recent chats</span><span className="history-count">{chats.filter((chat) => chat.messages?.length).length}</span></div>
      <div className="chat-list" aria-label="Chat history">
        {chats.filter((chat) => chat.messages?.length).map((chat) => <div key={chat.id} className={`chat-row ${chat.id === activeId ? "selected" : ""}`}>
          <button className="chat-select" onClick={() => setActiveId(chat.id)} title={chat.title}><span className="chat-icon">◌</span><span className="chat-title">{chat.title}</span></button>
          <button className="delete-chat" aria-label={`Delete ${chat.title}`} title="Delete chat" onClick={(event) => deleteChat(event, chat.id)}>×</button>
        </div>)}
        {!chats.some((chat) => chat.messages?.length) && <p className="empty-history">Your conversations will appear here.</p>}
      </div>
      <div className="sidebar-bottom library">
        <div className="library-heading"><div><div className="section-heading">Knowledge base</div><div className="library-title">Your documents</div></div><span className="library-count">{documents.length}</span></div>
        <button className="upload-button" onClick={() => fileRef.current?.click()} disabled={uploading}>
          <span>{uploading ? "◌" : "＋"}</span> {uploading ? "Uploading…" : "Add PDF files"}
        </button>
        <input ref={fileRef} type="file" accept="application/pdf,.pdf" multiple hidden onChange={upload} />
        <div className="file-hint">PDFs are indexed automatically</div>
        {documents.length > 0 && <div className="document-box">
          {documents.map((name) => <div className="document-name" key={name} title={name}><span className="pdf-icon">PDF</span><span>{name}</span></div>)}
        </div>}
        {index.status === "indexing" || index.status === "queued" ? <div className="status-line"><span className="pulse" />{index.message || "Indexing documents…"}</div> : null}
        {index.status === "ready" && <div className="status-line ready"><span>✓</span> Documents ready</div>}
        {!providerReady && documents.length > 0 && <div className="status-line unavailable">Model service unavailable</div>}
      </div>
    </aside>

    <main className="main-panel">
      <header className="topbar"><div className="breadcrumbs"><span>Workspace</span><b>/</b><strong> assistant</strong></div><span className="top-status"><i />{providerReady ? "Ready" : "Local workspace"}</span></header>
      <section className="conversation">
        {!activeChat?.messages?.length ? <div className="welcome">
          <div className="eyebrow"><span>✦</span> YOUR DOCUMENT ASSISTANT</div>
          <h1>What would you<br />like to explore?</h1>
          <p>Ask a question and get a clear, thoughtful answer.</p>
          {documents.length === 0 && <div className="welcome-note"><b>Start with a PDF</b><br />Upload a document from the sidebar to begin. It will be indexed automatically.</div>}
          {documents.length > 0 && !canChat && <div className="welcome-note"><b>Getting your documents ready</b><br />{index.message || "Make sure Ollama or your configured model service is running."}</div>}
          {canChat && <div className="suggestion-area"><div className="suggestion-heading">A good place to start <span>Choose a prompt</span></div><div className="suggestion-grid">
            <button className="suggestion-card" onClick={() => tryQuestion("Summarize the key points from my PDFs")}><span className="suggestion-icon green">↗</span><span><b>Summarize my files</b><small>Get a concise overview of your documents</small></span><span className="suggestion-arrow">↗</span></button>
            <button className="suggestion-card" onClick={() => tryQuestion("What are the most important details in my documents?")}><span className="suggestion-icon amber">⌕</span><span><b>Find an important detail</b><small>Ask about a person, fact, or topic</small></span><span className="suggestion-arrow">↗</span></button>
            <button className="suggestion-card" onClick={() => tryQuestion("What topics are covered in my PDFs?")}><span className="suggestion-icon blue">◇</span><span><b>Explore my PDFs</b><small>See what information is available</small></span><span className="suggestion-arrow">↗</span></button>
          </div></div>}
        </div> : <div className="messages">
          {activeChat.messages.map((message, i) => <article className={`message ${message.role}`} key={`${activeChat.id}-${i}`}>
            <div className="avatar">{message.role === "user" ? "◉" : "✳"}</div>
            <div className="message-content">{message.content || (busy && i === activeChat.messages.length - 1 ? <span className="typing"><i /><i /><i /></span> : null)}</div>
          </article>)}
          <div ref={endRef} />
        </div>}
        {error && <div className="error-banner">{error}<button onClick={() => setError("")}>×</button></div>}
      </section>
      <form className="composer-wrap" onSubmit={send}>
        <div className="composer">
          <textarea ref={composerRef} value={draft} onChange={(event) => setDraft(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey) send(event); }} placeholder={canChat ? "Ask anything about your PDFs…" : "Upload and index a PDF to start chatting…"} disabled={!canChat || busy} rows="1" />
          <button className="send-button" type="submit" disabled={!canChat || busy || !draft.trim()} aria-label="Send message">↑</button>
        </div>
        <div className="composer-foot">Answers are generated from your documents. Check important details against the source PDFs.</div>
      </form>
    </main>
  </div>;
}

function isGreeting(text = "") {
  return new Set(["hi", "hello", "hey", "hiya", "howdy", "good morning", "good afternoon", "good evening", "hi there", "hello there", "hey there", "how are you", "how are you doing"]).has(text.toLowerCase().trim().replace(/[.,!?;:]+$/, ""));
}
function chatTitle(messages) {
  return messages.find((message) => message.role === "user" && !isGreeting(message.content))?.content?.slice(0, 48) || "New chat";
}

createRoot(document.getElementById("root")).render(<React.StrictMode><App /></React.StrictMode>);
