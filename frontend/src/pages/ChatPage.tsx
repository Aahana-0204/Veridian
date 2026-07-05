/**
 * ChatPage — full conversational UI with streaming, citations, and session history.
 *
 * Layout (desktop):
 *   +── Session sidebar (260 px) ──+── Chat area ──+
 *   │ [+ New Chat]                 │ Messages      │
 *   │ Session list                 │ Input bar     │
 *   +──────────────────────────────+───────────────+
 *
 * On mobile, the session sidebar collapses behind a toggle button.
 */
import {
  type FormEvent,
  type KeyboardEvent,
  useCallback,
  useEffect,
  useRef,
  useState,
} from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import toast from 'react-hot-toast';
import { deleteSession, listSessions, type ChatSession, type Citation } from '../api/chat';
import { useChat, type MessageState } from '../hooks/useChat';
import { Modal } from '../components/ui/Modal';

// ── Citation expansion ────────────────────────────────────────────────────────

interface CitationProps {
  citations: Citation[];
}

function CitationList({ citations }: CitationProps) {
  const [expanded, setExpanded] = useState<string | null>(null);

  if (citations.length === 0) return null;

  return (
    <div className="mt-3 space-y-1.5" data-testid="citation-list">
      <p className="text-xs text-gray-500 font-medium uppercase tracking-wide">Sources</p>
      {citations.map((c, i) => (
        <div key={c.chunk_id} className="rounded-lg border border-gray-700 overflow-hidden">
          <button
            onClick={() => setExpanded(expanded === c.chunk_id ? null : c.chunk_id)}
            className="w-full flex items-center justify-between px-3 py-2 text-left text-xs text-gray-300 hover:bg-gray-800 transition-colors"
            aria-expanded={expanded === c.chunk_id}
            data-testid={`citation-toggle-${i}`}
          >
            <span className="font-medium truncate">
              [{i + 1}] {c.source_filename}
              {c.page_number != null && ` · p.${c.page_number}`}
            </span>
            <svg
              className={`w-3.5 h-3.5 ml-2 shrink-0 transition-transform ${
                expanded === c.chunk_id ? 'rotate-180' : ''
              }`}
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M19 9l-7 7-7-7"
              />
            </svg>
          </button>

          {expanded === c.chunk_id && (
            <div
              className="px-3 py-2 bg-gray-900/60 border-t border-gray-700 text-xs text-gray-400 leading-relaxed"
              data-testid={`citation-snippet-${i}`}
            >
              <p className="text-gray-300 font-medium mb-1">{c.source_filename}</p>
              <blockquote className="text-gray-400 italic">&ldquo;{c.snippet}&rdquo;</blockquote>
              <p className="mt-1 text-gray-600">
                Score: {(c.score * 100).toFixed(0)}% · Chunk #{c.chunk_index}
              </p>
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

// ── Individual message bubble ─────────────────────────────────────────────────

function MessageBubble({ msg }: { msg: MessageState }) {
  const isUser = msg.role === 'user';

  return (
    <div
      className={`flex ${isUser ? 'justify-end' : 'justify-start'} mb-4`}
      data-testid={`message-${msg.role}`}
    >
      {/* Assistant avatar */}
      {!isUser && (
        <div className="w-7 h-7 rounded-full bg-indigo-600 flex items-center justify-center shrink-0 mr-2 mt-1">
          <span className="text-white text-xs font-bold">V</span>
        </div>
      )}

      <div className={`max-w-[80%] min-w-0 ${isUser ? '' : 'flex-1'}`}>
        <div
          className={`rounded-2xl px-4 py-3 ${
            isUser
              ? 'bg-indigo-600 text-white ml-auto'
              : msg.failed
                ? 'bg-red-950/50 border border-red-800 text-red-300'
                : 'bg-gray-800 text-gray-100'
          }`}
        >
          {isUser ? (
            <p className="text-sm whitespace-pre-wrap">{msg.content}</p>
          ) : (
            <div className="prose prose-invert prose-sm max-w-none">
              <ReactMarkdown
                remarkPlugins={[remarkGfm]}
                components={{
                  code({ children, className }) {
                    const isBlock = className?.startsWith('language-');
                    return isBlock ? (
                      <pre className="bg-gray-900/80 rounded-lg p-3 overflow-x-auto text-xs leading-relaxed">
                        <code className={className}>{children}</code>
                      </pre>
                    ) : (
                      <code className="bg-gray-900/80 rounded px-1 py-0.5 text-xs font-mono">
                        {children}
                      </code>
                    );
                  },
                  table({ children }) {
                    return (
                      <div className="overflow-x-auto">
                        <table className="text-xs">{children}</table>
                      </div>
                    );
                  },
                }}
              >
                {msg.content}
              </ReactMarkdown>
              {msg.streaming && (
                <span
                  className="inline-block w-2 h-4 bg-indigo-400 animate-pulse ml-0.5 align-text-bottom"
                  aria-hidden="true"
                />
              )}
            </div>
          )}
        </div>

        {/* Citations */}
        {!isUser && !msg.streaming && <CitationList citations={msg.citations} />}
      </div>
    </div>
  );
}

// ── Session sidebar ───────────────────────────────────────────────────────────

interface SessionSidebarProps {
  activeSessionId: string | undefined;
  onSelect: (id: string) => void;
  onNew: () => void;
}

function SessionSidebar({ activeSessionId, onSelect, onNew }: SessionSidebarProps) {
  const qc = useQueryClient();
  const [deletingId, setDeletingId] = useState<string | null>(null);

  const { data, isLoading } = useQuery({
    queryKey: ['chat-sessions'],
    queryFn: () => listSessions(1, 50),
    refetchInterval: 15_000,
  });

  const handleDelete = async (id: string) => {
    try {
      await deleteSession(id);
      qc.invalidateQueries({ queryKey: ['chat-sessions'] });
      toast.success('Session deleted');
      if (id === activeSessionId) onNew();
    } catch {
      toast.error('Failed to delete session');
    } finally {
      setDeletingId(null);
    }
  };

  return (
    <aside
      className="w-64 shrink-0 flex flex-col border-r border-gray-800 bg-gray-950"
      data-testid="session-sidebar"
    >
      <div className="p-3">
        <button
          onClick={onNew}
          className="w-full flex items-center justify-center gap-2 px-3 py-2 text-sm font-medium text-gray-100 bg-indigo-600 hover:bg-indigo-500 rounded-lg transition-colors"
          data-testid="new-chat-btn"
        >
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
          </svg>
          New Chat
        </button>
      </div>

      <div className="flex-1 overflow-y-auto px-2 space-y-0.5 pb-4">
        {isLoading && <p className="text-xs text-gray-600 text-center py-4">Loading sessions…</p>}
        {data?.items.length === 0 && !isLoading && (
          <p className="text-xs text-gray-600 text-center py-4" data-testid="no-sessions">
            No sessions yet
          </p>
        )}
        {data?.items.map((session: ChatSession) => (
          <div
            key={session.id}
            className={`group flex items-center gap-1 rounded-lg transition-colors ${
              session.id === activeSessionId ? 'bg-gray-800' : 'hover:bg-gray-900'
            }`}
          >
            <button
              onClick={() => onSelect(session.id)}
              className="flex-1 text-left px-3 py-2 min-w-0"
              data-testid={`session-btn-${session.id}`}
            >
              <p className="text-xs text-gray-300 truncate">{session.title ?? 'Untitled Chat'}</p>
              <p className="text-[10px] text-gray-600 mt-0.5">
                {new Date(session.created_at).toLocaleDateString()}
              </p>
            </button>
            <button
              onClick={(e) => {
                e.stopPropagation();
                setDeletingId(session.id);
              }}
              className="p-1.5 mr-1 text-gray-700 hover:text-red-400 opacity-0 group-hover:opacity-100 transition-all rounded"
              aria-label={`Delete session: ${session.title}`}
              data-testid={`session-delete-${session.id}`}
            >
              <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"
                />
              </svg>
            </button>
          </div>
        ))}
      </div>

      {/* Delete session modal */}
      <Modal open={!!deletingId} onClose={() => setDeletingId(null)} title="Delete chat session?">
        <p className="text-sm text-gray-400 mb-5">
          This will permanently remove the session and all its messages.
        </p>
        <div className="flex gap-3">
          <button
            onClick={() => deletingId && handleDelete(deletingId)}
            className="flex-1 py-2 text-sm font-medium text-white bg-red-600 hover:bg-red-500 rounded-lg transition-colors"
          >
            Delete
          </button>
          <button
            onClick={() => setDeletingId(null)}
            className="flex-1 py-2 text-sm font-medium text-gray-300 bg-gray-700 hover:bg-gray-600 rounded-lg transition-colors"
          >
            Cancel
          </button>
        </div>
      </Modal>
    </aside>
  );
}

// ── Chat input ────────────────────────────────────────────────────────────────

interface ChatInputProps {
  onSend: (text: string) => void;
  onCancel: () => void;
  disabled: boolean;
  streaming: boolean;
}

function ChatInput({ onSend, onCancel, disabled, streaming }: ChatInputProps) {
  const [text, setText] = useState('');
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const submit = useCallback(() => {
    const trimmed = text.trim();
    if (!trimmed || disabled) return;
    onSend(trimmed);
    setText('');
    // Reset textarea height
    if (textareaRef.current) textareaRef.current.style.height = 'auto';
  }, [text, disabled, onSend]);

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  };

  const handleInput = () => {
    const ta = textareaRef.current;
    if (!ta) return;
    ta.style.height = 'auto';
    ta.style.height = `${Math.min(ta.scrollHeight, 160)}px`;
  };

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    submit();
  };

  return (
    <form
      onSubmit={handleSubmit}
      className="flex items-end gap-3 px-4 py-3 border-t border-gray-800 bg-gray-950"
    >
      <textarea
        ref={textareaRef}
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={handleKeyDown}
        onInput={handleInput}
        placeholder="Ask a question about your documents… (Enter to send, Shift+Enter for newline)"
        rows={1}
        className="flex-1 resize-none bg-gray-800 border border-gray-700 rounded-xl px-4 py-3 text-sm text-gray-100 placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-indigo-500 min-h-[44px] max-h-40"
        aria-label="Chat message input"
        disabled={disabled && !streaming}
      />

      {streaming ? (
        <button
          type="button"
          onClick={onCancel}
          className="shrink-0 px-4 py-2.5 text-sm font-medium text-gray-300 bg-gray-700 hover:bg-gray-600 rounded-xl transition-colors"
        >
          Stop
        </button>
      ) : (
        <button
          type="submit"
          disabled={!text.trim() || disabled}
          className="shrink-0 px-4 py-2.5 text-sm font-medium text-white bg-indigo-600 hover:bg-indigo-500 disabled:opacity-40 disabled:cursor-not-allowed rounded-xl transition-colors"
        >
          Send
        </button>
      )}
    </form>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export function ChatPage() {
  const { sessionId, messages, isStreaming, send, cancel, loadSession, newChat } = useChat();
  const [showSidebar, setShowSidebar] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to bottom on new messages
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  return (
    <div className="flex h-full">
      {/* Desktop session sidebar */}
      <div className="hidden md:flex">
        <SessionSidebar
          activeSessionId={sessionId}
          onSelect={(id) => loadSession(id)}
          onNew={newChat}
        />
      </div>

      {/* Mobile sidebar toggle + overlay */}
      {showSidebar && (
        <div className="md:hidden fixed inset-0 z-40 flex">
          <div
            className="absolute inset-0 bg-black/60"
            onClick={() => setShowSidebar(false)}
            aria-hidden="true"
          />
          <div className="relative z-50 flex">
            <SessionSidebar
              activeSessionId={sessionId}
              onSelect={(id) => {
                loadSession(id);
                setShowSidebar(false);
              }}
              onNew={() => {
                newChat();
                setShowSidebar(false);
              }}
            />
          </div>
        </div>
      )}

      {/* Chat area */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Mobile header with sidebar toggle */}
        <div className="md:hidden flex items-center gap-3 px-4 py-2 border-b border-gray-800">
          <button
            onClick={() => setShowSidebar(true)}
            className="p-1 text-gray-400 hover:text-gray-100"
            aria-label="Open sessions"
          >
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M4 6h16M4 12h16M4 18h16"
              />
            </svg>
          </button>
          <span className="text-sm font-medium text-gray-300">
            {sessionId ? 'Chat' : 'New Chat'}
          </span>
        </div>

        {/* Messages */}
        <div className="flex-1 overflow-y-auto px-4 py-6">
          {messages.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-full text-center">
              <div className="w-16 h-16 rounded-2xl bg-indigo-600/20 flex items-center justify-center mb-4">
                <svg
                  className="w-8 h-8 text-indigo-400"
                  fill="none"
                  stroke="currentColor"
                  viewBox="0 0 24 24"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={1.5}
                    d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z"
                  />
                </svg>
              </div>
              <h2 className="text-lg font-semibold text-gray-100 mb-2">Ask Veridian</h2>
              <p className="text-sm text-gray-500 max-w-sm">
                Upload documents, then ask questions about them. Veridian will retrieve relevant
                passages and cite its sources.
              </p>
            </div>
          ) : (
            messages.map((msg) => <MessageBubble key={msg.id} msg={msg} />)
          )}
          <div ref={bottomRef} />
        </div>

        {/* Input */}
        <ChatInput onSend={send} onCancel={cancel} disabled={isStreaming} streaming={isStreaming} />
      </div>
    </div>
  );
}
