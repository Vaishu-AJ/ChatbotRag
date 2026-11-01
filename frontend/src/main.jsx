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

function MediaCard({ item }) {
  const [mediaUrl, setMediaUrl] = useState("");
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let cancelled = false;
    let objectUrl = "";
    setMediaUrl("");
    setFailed(false);
    fetch(item.url)
      .then((response) => {
        if (!response.ok) throw new Error("media unavailable");
        return response.blob();
      })
      .then((blob) => {
        objectUrl = URL.createObjectURL(blob);
        if (cancelled) URL.revokeObjectURL(objectUrl);
        else setMediaUrl(objectUrl);
      })
      .catch(() => { if (!cancelled) setFailed(true); });
    return () => { cancelled = true; if (objectUrl) URL.revokeObjectURL(objectUrl); };
  }, [item.url]);

  return <figure key={item.url}>
    {failed ? <div className="media-unavailable">File is currently unavailable.</div>
      : !mediaUrl ? <div className="media-unavailable">Loading document…</div>
      : item.type === "video" ? <video controls preload="metadata" src={mediaUrl} />
      : item.type === "document" ? <iframe title={item.name} src={mediaUrl} loading="lazy" />
      : <a href={mediaUrl} target="_blank" rel="noreferrer"><img src={mediaUrl} alt={item.name} loading="lazy" /></a>}
    <figcaption>{item.name}{item.location ? ` · ${item.location}` : ""}</figcaption>
    {!failed && mediaUrl && <a className="media-download" href={mediaUrl} download={item.name}>
      {item.type === "video" ? "Download video" : item.type === "document" ? "Download document" : "Download image"}
    </a>}
  </figure>;
}

function App() {
  const [chats, setChats] = useState([]);
  const [activeId, setActiveId] = useState(null);
  const [documents, setDocuments] = useState([]);
  const [indexedChunks, setIndexedChunks] = useState(0);
  const [index, setIndex] = useState({ status: "idle", message: "" });
  const [providerReady, setProviderReady] = useState(false);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [theme, setTheme] = useState(() => window.localStorage.getItem("askme-theme") === "dark" ? "dark" : "light");
  const [paused, setPaused] = useState(false);
  const pausedRef = useRef(false);
  const pauseResolverRef = useRef(null);
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  const [copiedMessage, setCopiedMessage] = useState("");
  const [error, setError] = useState("");
  const [uploading, setUploading] = useState(false);
  const [deleting, setDeleting] = useState("");
  const [documentToDelete, setDocumentToDelete] = useState("");
  const endRef = useRef(null);
  const fileRef = useRef(null);
  const composerRef = useRef(null);
  const activeChat = chats.find((chat) => chat.id === activeId);

  useEffect(() => {
    if (!documentToDelete) return undefined;
    const handleKeyDown = (event) => {
      if (event.key === "Escape") setDocumentToDelete("");
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [documentToDelete]);

  const copyMessage = async (content, key) => {
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(content);
      } else {
        const field = document.createElement("textarea");
        field.value = content;
        field.setAttribute("readonly", "");
        field.style.position = "fixed";
        field.style.opacity = "0";
        document.body.appendChild(field);
        field.select();
        const copied = document.execCommand("copy");
        field.remove();
        if (!copied) throw new Error("Clipboard copy failed");
      }
      setCopiedMessage(key);
      window.setTimeout(() => setCopiedMessage((current) => current === key ? "" : current), 1600);
    } catch {
      setError("Could not copy this message. Check your browser clipboard permissions.");
    }
  };

  const load = useCallback(async () => {
    try {
      const response = await api("/api/bootstrap");
      const data = await response.json();
      let history = (data.chats || []).map((chat) => ({
        ...chat,
        messages: (chat.messages || []).filter((message) => !(message.role === "assistant" && message.content?.startsWith("I couldn't complete that request:"))),
      }));
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
    document.documentElement.dataset.theme = theme;
    window.localStorage.setItem("askme-theme", theme);
    document.querySelector('meta[name="theme-color"]')?.setAttribute("content", theme === "dark" ? "#0b100d" : "#f5f7f3");
  }, [theme]);
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
  useEffect(() => {
    if (!busy) return undefined;
    const startedAt = performance.now();
    setElapsedSeconds(0);
    const timer = window.setInterval(() => {
      setElapsedSeconds((performance.now() - startedAt) / 1000);
    }, 100);
    return () => window.clearInterval(timer);
  }, [busy]);
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

  const deleteDocument = async (name) => {
    setDocumentToDelete("");
    setDeleting(name); setError("");
    try {
      const response = await api(`/api/documents/${encodeURIComponent(name)}`, { method: "DELETE" });
      const result = await response.json();
      setDocuments(result.documents || []);
      setIndex(result.index || { status: "idle", message: "" });
      setIndexedChunks(result.index?.chunks || 0);
    } catch (cause) { setError(cause.message); }
    finally { setDeleting(""); }
  };

  const send = async (event) => {
    event?.preventDefault();
    const question = draft.trim();
    if (!question || busy || !activeChat) return;
    setDraft(""); setBusy(true); setError("");
    const userMessage = { role: "user", content: question };
    const assistantMessage = { role: "assistant", content: "", media: [] };
    setChats((current) => current.map((chat) => chat.id === activeId ? {
      ...chat,
      title: chat.messages?.some((message) => message.role === "user" && !isGreeting(message.content)) || isGreeting(question)
        ? chat.title : question.slice(0, 48),
      messages: [...(chat.messages || []), userMessage, assistantMessage],
    } : chat));
    const removePendingAnswer = () => setChats((current) => current.map((chat) => {
      if (chat.id !== activeId) return chat;
      const messages = chat.messages || [];
      const last = messages[messages.length - 1];
      return last?.role === "assistant" && !last.content ? { ...chat, messages: messages.slice(0, -1) } : chat;
    }));
    try {
      const response = await api(`/api/chats/${activeId}/messages`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ question }),
      });
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let answer = "";
      let buffer = "";
      let failed = false;
      const receiveEvent = (block) => {
        const line = block.split("\n").find((item) => item.startsWith("data: "));
        if (!line) return;
        const event = JSON.parse(line.slice(6));
        if (event.type === "error") {
          failed = true;
          setError(friendlyChatError(event.message));
          return;
        }
        if (event.type === "text") answer += event.text || "";
        setChats((current) => current.map((chat) => chat.id === activeId ? {
          ...chat, messages: chat.messages.map((message, i, all) => i === all.length - 1
            ? {
                ...message,
                content: answer,
                ...(event.type === "media" ? { media: event.media || [] } : {}),
                ...(event.type === "timing" ? { duration_seconds: event.seconds } : {}),
              }
            : message),
        } : chat));
      };
      const waitIfPaused = async () => {
        while (pausedRef.current) {
          await new Promise((resolve) => { pauseResolverRef.current = resolve; });
          pauseResolverRef.current = null;
        }
      };
      while (true) {
        await waitIfPaused();
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const blocks = buffer.split("\n\n");
        buffer = blocks.pop() || "";
        for (const block of blocks) {
          await waitIfPaused();
          receiveEvent(block);
        }
      }
      buffer += decoder.decode();
      if (buffer.trim()) {
        await waitIfPaused();
        receiveEvent(buffer);
      }
      if (failed && !answer) removePendingAnswer();
      setChats((current) => current.map((chat) => chat.id === activeId ? { ...chat, title: chatTitle([...chat.messages.slice(0, -2), userMessage]) } : chat));
    } catch (cause) {
      setError(friendlyChatError(cause.message));
      removePendingAnswer();
    } finally {
      pausedRef.current = false;
      pauseResolverRef.current?.();
      pauseResolverRef.current = null;
      setPaused(false);
      setBusy(false);
    }
  };

  const togglePause = () => {
    const next = !pausedRef.current;
    pausedRef.current = next;
    setPaused(next);
    if (!next) {
      pauseResolverRef.current?.();
      pauseResolverRef.current = null;
    }
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
          <span>{uploading ? "◌" : "＋"}</span> {uploading ? "Uploading…" : "Add files"}
        </button>
        <input ref={fileRef} type="file" accept=".pdf,.png,.jpg,.jpeg,.webp,.bmp,.tif,.tiff,.wav,.mp3,.m4a,.aac,.flac,.ogg,.wma,.mp4,.mov,.mkv,.avi,.webm,.m4v" multiple hidden onChange={upload} />
        <div className="file-hint">PDFs, images, audio, and video are indexed automatically</div>
        {documents.length > 0 && <div className="document-box">
          {documents.map((name) => <div className="document-row" key={name}>
            <div className="document-name" title={name}><span className="pdf-icon">{documentLabel(name)}</span><span>{name}</span></div>
            <button className="delete-document" aria-label={`Delete ${name}`} title="Delete document" disabled={Boolean(deleting) || index.status === "indexing" || index.status === "queued"} onClick={() => setDocumentToDelete(name)}>{deleting === name ? "…" : "×"}</button>
          </div>)}
        </div>}
        {index.status === "indexing" || index.status === "queued" ? <div className="status-line"><span className="pulse" />{index.message || "Indexing documents…"}</div> : null}
        {index.status === "ready" && <div className="status-line ready"><span>✓</span> Documents ready</div>}
        {!providerReady && documents.length > 0 && <div className="status-line unavailable">Model service unavailable</div>}
      </div>
    </aside>

    <main className="main-panel">
      <header className="topbar"><div className="breadcrumbs"><span>Workspace</span><b>/</b><strong> assistant</strong></div><div className="topbar-actions"><button className="theme-toggle" type="button" onClick={() => setTheme((current) => current === "dark" ? "light" : "dark")} aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} theme`} title={`Switch to ${theme === "dark" ? "light" : "dark"} theme`}><span aria-hidden="true">{theme === "dark" ? "☀" : "☾"}</span><span>{theme === "dark" ? "Light" : "Dark"}</span></button><span className="top-status"><i />{providerReady ? "Ready" : "Local workspace"}</span></div></header>
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
            <div className={`avatar ${message.role === "user" ? "user-avatar" : "assistant-avatar"}`} aria-label={message.role === "user" ? "You" : "Assistant"} title={message.role === "user" ? "You" : "Assistant"}>
              {message.role === "user" ? <PersonIcon /> : <RobotIcon />}
            </div>
            <div className="message-content">
              {message.content ? renderMarkdown(message.content) : (busy && i === activeChat.messages.length - 1 ? <span className="typing"><i /><i /><i /></span> : null)}
              {message.role === "assistant" && busy && i === activeChat.messages.length - 1 && <div className="message-timing live">{paused ? "Paused" : "Generating"} · {formatDuration(elapsedSeconds)}</div>}
              {message.media?.length > 0 && <div className="message-media">{message.media.map((item) => <MediaCard key={item.url} item={item} />)}</div>}
              {message.role === "assistant" && Number.isFinite(message.duration_seconds) && <div className="message-timing">Answered in {formatDuration(message.duration_seconds)}</div>}
              {message.content && <div className={`message-actions ${message.role === "user" ? "user-message-actions" : "assistant-message-actions"}`}><button className="copy-message" type="button" onClick={() => copyMessage(message.content, `${activeChat.id}-${i}`)} aria-label={copiedMessage === `${activeChat.id}-${i}` ? "Copied" : message.role === "user" ? "Copy question" : "Copy answer"} title={copiedMessage === `${activeChat.id}-${i}` ? "Copied" : message.role === "user" ? "Copy question" : "Copy answer"}>
                {copiedMessage === `${activeChat.id}-${i}` ? <CheckIcon /> : <CopyIcon />}
              </button></div>}
            </div>
          </article>)}
          <div ref={endRef} />
        </div>}
        {error && <div className="error-banner">{error}<button onClick={() => setError("")}>×</button></div>}
      </section>
      <form className="composer-wrap" onSubmit={send}>
        <div className="composer">
          <textarea ref={composerRef} value={draft} onChange={(event) => setDraft(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey) send(event); }} placeholder={canChat ? "Ask anything about your PDFs…" : "Upload and index a PDF to start chatting…"} disabled={!canChat || busy} rows="1" />
          {busy && <button className="pause-button" type="button" onClick={togglePause} aria-label={paused ? "Resume answer" : "Pause answer"}>{paused ? "Resume" : "Pause"}</button>}
          <button className="send-button" type="submit" disabled={!canChat || busy || !draft.trim()} aria-label="Send message">↑</button>
        </div>
        <div className="composer-foot">Answers are generated from your documents. Check important details against the source PDFs.</div>
      </form>
    </main>
    {documentToDelete && <div className="confirm-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) setDocumentToDelete(""); }}>
      <section className="confirm-dialog" role="alertdialog" aria-modal="true" aria-labelledby="delete-title" aria-describedby="delete-description">
        <div className="confirm-icon" aria-hidden="true">×</div>
        <div className="confirm-kicker">Remove document</div>
        <h2 id="delete-title">Delete this file?</h2>
        <p id="delete-description">“{documentToDelete}” will be removed from your knowledge base. You can add it again later.</p>
        <div className="confirm-actions">
          <button className="confirm-cancel" type="button" onClick={() => setDocumentToDelete("")}>Keep document</button>
          <button className="confirm-delete" type="button" autoFocus onClick={() => deleteDocument(documentToDelete)}>Delete file</button>
        </div>
      </section>
    </div>}
  </div>;
}

function PersonIcon() {
  return <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><circle cx="12" cy="8" r="3.2" /><path d="M5.5 19c.5-3.1 2.8-5 6.5-5s6 1.9 6.5 5v1h-13z" /></svg>;
}

function RobotIcon() {
  return <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="M12 3v2.2M9.8 3h4.4" /><rect x="4.5" y="7" width="15" height="12" rx="3" /><path d="M8 19v2m8-2v2M2.5 11v4m19-4v4" /><circle cx="9" cy="12" r="1" /><circle cx="15" cy="12" r="1" /><path d="M9 16h6" /></svg>;
}

function CopyIcon() {
  return <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><rect x="8" y="8" width="12" height="13" rx="2" /><path d="M16 8V5a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v11a2 2 0 0 0 2 2h2" /></svg>;
}

function CheckIcon() {
  return <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="m5 12 4 4L19 6" /></svg>;
}

function renderMarkdown(text) {
  const lines = text.split(/\r?\n/);
  const blocks = [];
  const isListItem = (line) => /^\s*(?:[-*+]\s+|\d+[.)]\s+)/.test(line);
  let index = 0;

  while (index < lines.length) {
    const line = lines[index].trim();
    if (!line) { index += 1; continue; }

    const heading = line.match(/^(#{1,6})\s+(.+)$/);
    if (heading) {
      const level = heading[1].length;
      const Tag = `h${level}`;
      blocks.push(<Tag key={`heading-${index}`}>{renderInlineMarkdown(heading[2])}</Tag>);
      index += 1;
      continue;
    }

    if (isListItem(line)) {
      const ordered = /^\d+[.)]\s+/.test(line);
      const Tag = ordered ? "ol" : "ul";
      const items = [];
      while (index < lines.length && isListItem(lines[index])) {
        const item = lines[index].trim().replace(/^(?:[-*+]\s+|\d+[.)]\s+)/, "");
        items.push(<li key={`item-${index}`}>{renderInlineMarkdown(item)}</li>);
        index += 1;
      }
      blocks.push(<Tag key={`list-${index}`}>{items}</Tag>);
      continue;
    }

    const paragraph = [line];
    index += 1;
    while (index < lines.length && lines[index].trim() && !/^#{1,6}\s+/.test(lines[index].trim()) && !isListItem(lines[index])) {
      paragraph.push(lines[index].trim());
      index += 1;
    }
    blocks.push(<p key={`paragraph-${index}`}>{renderInlineMarkdown(paragraph.join(" "))}</p>);
  }
  return blocks;
}

function renderInlineMarkdown(text) {
  const pattern = /(\*\*.+?\*\*|__.+?__|`[^`]+`|\*[^*]+\*|_[^_]+_)/g;
  return text.split(pattern).filter(Boolean).map((part, index) => {
    if ((part.startsWith("**") && part.endsWith("**")) || (part.startsWith("__") && part.endsWith("__"))) {
      return <strong key={index}>{part.slice(2, -2)}</strong>;
    }
    if (part.startsWith("`")) return <code key={index}>{part.slice(1, -1)}</code>;
    if ((part.startsWith("*") && part.endsWith("*")) || (part.startsWith("_") && part.endsWith("_"))) {
      return <em key={index}>{part.slice(1, -1)}</em>;
    }
    return part;
  });
}

function formatDuration(seconds) {
  if (seconds < 60) return `${seconds.toFixed(2)} seconds`;
  const minutes = Math.floor(seconds / 60);
  return `${minutes} ${minutes === 1 ? "minute" : "minutes"}`;
}

function friendlyChatError(message = "") {
  const normalized = message.toLowerCase();
  if (normalized.includes("timeout") || normalized.includes("timed out")) return "The request took too long. Please try again.";
  return "I couldn't complete that request. Please try again.";
}

function isGreeting(text = "") {
  return new Set(["hi", "hello", "hey", "hiya", "howdy", "good morning", "good afternoon", "good evening", "hi there", "hello there", "hey there", "how are you", "how are you doing"]).has(text.toLowerCase().trim().replace(/[.,!?;:]+$/, ""));
}
function chatTitle(messages) {
  return messages.find((message) => message.role === "user" && !isGreeting(message.content))?.content?.slice(0, 48) || "New chat";
}
function documentLabel(name) {
  const extension = name.split(".").pop()?.toLowerCase();
  if (extension === "pdf") return "PDF";
  if (["png", "jpg", "jpeg", "webp", "bmp", "tif", "tiff"].includes(extension)) return "IMG";
  if (["mp4", "mov", "mkv", "avi", "webm", "m4v"].includes(extension)) return "VID";
  return "AUD";
}

createRoot(document.getElementById("root")).render(<React.StrictMode><App /></React.StrictMode>);
