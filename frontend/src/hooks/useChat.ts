/**
 * useChat — streaming chat state management hook.
 *
 * Manages:
 * - Active session ID (undefined = start a new session on first send)
 * - Full message list (user + assistant messages with citations)
 * - Streaming state: which assistant slot is being streamed into
 * - Auto-scrolling via a provided ref callback
 *
 * Streaming lifecycle:
 * 1. User sends → add user message immediately.
 * 2. Add a placeholder assistant message (streaming: true, content: '').
 * 3. Tokens from SSE → append to placeholder content.
 * 4. Done event → finalize message with citations; update sessionId.
 * 5. Error event or fetch error → mark message as failed.
 */
import { useCallback, useRef, useState } from 'react';
import {
  streamQuery,
  getSessionHistory,
  type ChatMessage,
  type ChatDoneEvent,
  type Citation,
} from '../api/chat';

export interface MessageState {
  id: string; // local UUID or server message_id after done
  role: 'user' | 'assistant';
  content: string;
  citations: Citation[];
  streaming: boolean;
  failed: boolean;
  created_at: string;
}

let _localId = 0;
const nextId = () => `local-${++_localId}`;

export function useChat() {
  const [sessionId, setSessionId] = useState<string | undefined>();
  const [messages, setMessages] = useState<MessageState[]>([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  /** Cancel an in-progress stream. */
  const cancel = useCallback(() => {
    abortRef.current?.abort();
  }, []);

  /**
   * Send a user message and stream the assistant's response.
   * @param text — the query text
   */
  const send = useCallback(
    (text: string) => {
      if (isStreaming || !text.trim()) return;

      const userMsgId = nextId();
      const asstMsgId = nextId();
      const now = new Date().toISOString();

      // 1. Add user message immediately
      setMessages((prev) => [
        ...prev,
        {
          id: userMsgId,
          role: 'user',
          content: text.trim(),
          citations: [],
          streaming: false,
          failed: false,
          created_at: now,
        },
      ]);

      // 2. Add streaming placeholder
      setMessages((prev) => [
        ...prev,
        {
          id: asstMsgId,
          role: 'assistant',
          content: '',
          citations: [],
          streaming: true,
          failed: false,
          created_at: now,
        },
      ]);

      setIsStreaming(true);

      abortRef.current = streamQuery(
        { message: text.trim(), session_id: sessionId },
        {
          onToken: (token) => {
            setMessages((prev) =>
              prev.map((m) =>
                m.id === asstMsgId ? { ...m, content: m.content + token } : m
              )
            );
          },
          onDone: (event: ChatDoneEvent) => {
            setSessionId(event.session_id);
            setMessages((prev) =>
              prev.map((m) =>
                m.id === asstMsgId
                  ? {
                      ...m,
                      id: event.message_id,
                      citations: event.citations,
                      streaming: false,
                    }
                  : m
              )
            );
            setIsStreaming(false);
          },
          onError: (event) => {
            setMessages((prev) =>
              prev.map((m) =>
                m.id === asstMsgId
                  ? {
                      ...m,
                      content:
                        m.content ||
                        `Error: ${event.message}`,
                      streaming: false,
                      failed: true,
                    }
                  : m
              )
            );
            setIsStreaming(false);
          },
        }
      );
    },
    [isStreaming, sessionId]
  );

  /**
   * Load a past session's message history from the API.
   * Clears current messages and replaces with the loaded history.
   */
  const loadSession = useCallback(async (id: string) => {
    setSessionId(id);
    setIsStreaming(false);
    abortRef.current?.abort();

    try {
      const data = await getSessionHistory(id);
      const loaded: MessageState[] = data.messages.map((m: ChatMessage) => ({
        id: m.id,
        role: m.role,
        content: m.content,
        citations: (m.sources as Citation[] | null) ?? [],
        streaming: false,
        failed: false,
        created_at: m.created_at,
      }));
      setMessages(loaded);
    } catch {
      setMessages([]);
    }
  }, []);

  /** Start a fresh conversation (no session ID). */
  const newChat = useCallback(() => {
    abortRef.current?.abort();
    setSessionId(undefined);
    setMessages([]);
    setIsStreaming(false);
  }, []);

  return { sessionId, messages, isStreaming, send, cancel, loadSession, newChat };
}
