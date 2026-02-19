/**
 * ChatPage — The main conversation view.
 *
 * Uses Zustand for state management and useExternalStoreRuntime to bridge
 * to assistant-ui primitives. State lives in the store, not in React state.
 */

import { useState, useEffect, useCallback, useRef } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { ArrowUp, Square } from "lucide-react";
import { ToolFallback } from "../components/ToolFallback";
import {
  ComposerAttachments,
  ComposerAddAttachment,
  UserMessageAttachments,
} from "../components/Attachment";
import {
  useExternalStoreRuntime,
  AssistantRuntimeProvider,
  ThreadPrimitive,
  ComposerPrimitive,
  MessagePrimitive,
  AssistantIf,
  SimpleImageAttachmentAdapter,
} from "@assistant-ui/react";
import type { ThreadMessageLike, AppendMessage } from "@assistant-ui/react";
import { MarkdownText } from "../components/MarkdownText";
import {
  useGreenhouseStore,
  type Message,
  type JSONValue,
  type ToolCallPart,
} from "../store";

// Font scale for standard sizing (ChatGPT-like)
const fontScale = 1;

// -----------------------------------------------------------------------------
// SSE Stream Reader
// -----------------------------------------------------------------------------

interface StreamEvent {
  type: "text-delta" | "text" | "thinking-delta" | "tool-call" | "tool-result" | "session-id" | "context" | "done" | "error" | "archive-error";
  data: unknown;
}

async function* readSSEStream(
  reader: ReadableStreamDefaultReader<Uint8Array>
): AsyncGenerator<StreamEvent> {
  const decoder = new TextDecoder();
  let buffer = "";

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop() || "";

      for (const line of lines) {
        if (line.startsWith("data: ")) {
          const data = line.slice(6);
          if (data === "[DONE]") {
            yield { type: "done", data: null };
          } else {
            try {
              const parsed = JSON.parse(data);
              yield parsed as StreamEvent;
            } catch {
              // Ignore malformed JSON
            }
          }
        }
      }
    }
  } finally {
    reader.releaseLock();
  }
}

// -----------------------------------------------------------------------------
// Message Components (using MessagePrimitive)
// -----------------------------------------------------------------------------

const UserMessage = () => {
  return (
    <MessagePrimitive.Root className="flex flex-col items-end mb-4">
      {/* Attachments shown above the bubble */}
      <UserMessageAttachments />
      <div
        className="px-4 py-3 bg-user-bubble rounded-2xl max-w-[75%] text-text break-words"
        style={{ fontSize: `${16 * fontScale}px` }}
      >
        <MessagePrimitive.Parts />
      </div>
    </MessagePrimitive.Root>
  );
};

const ThinkingBlock = ({ text, status }: { text: string; status: unknown }) => {
  const isStreaming = (status as { type?: string })?.type === "running";

  return (
    <details open={isStreaming} className="mb-3 group">
      <summary
        className="cursor-pointer text-muted italic select-none list-none flex items-center gap-2"
        style={{ fontSize: `${13 * fontScale}px` }}
      >
        <span className="text-muted/60 group-open:rotate-90 transition-transform inline-block">{"\u25B6"}</span>
        {isStreaming ? "Rosemary is thinking..." : "Rosemary's thinking"}
      </summary>
      <div
        className="mt-2 pl-4 border-l-2 border-muted/20 text-muted italic leading-relaxed whitespace-pre-wrap"
        style={{ fontSize: `${13 * fontScale}px` }}
      >
        {text}
      </div>
    </details>
  );
};

const AssistantMessage = () => {
  const contentRef = useRef<HTMLDivElement>(null);
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    if (contentRef.current) {
      await navigator.clipboard.writeText(contentRef.current.textContent || "");
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };

  return (
    <MessagePrimitive.Root className="mb-6 pl-2 pr-12 group/assistant">
      <div
        ref={contentRef}
        className="text-text leading-relaxed"
        style={{ fontSize: `${16 * fontScale}px` }}
      >
        <MessagePrimitive.Parts
          components={{
            Text: MarkdownText,
            Reasoning: ThinkingBlock,
            tools: {
              Fallback: ToolFallback,
            },
          }}
        />
      </div>
      {/* Copy button — appears on hover */}
      <div className="mt-1 opacity-0 group-hover/assistant:opacity-100 transition-opacity">
        <button
          onClick={handleCopy}
          className="text-muted hover:text-text text-xs px-2 py-1 rounded bg-transparent border-none cursor-pointer"
        >
          {copied ? "Copied!" : "Copy"}
        </button>
      </div>
    </MessagePrimitive.Root>
  );
};

// -----------------------------------------------------------------------------
// Convert our Message to ThreadMessageLike
// -----------------------------------------------------------------------------

const convertMessage = (message: Message): ThreadMessageLike => {
  // Map our internal content parts to assistant-ui's expected types
  const content = message.content.map((part) => {
    if (part.type === "thinking") {
      // Map thinking blocks to assistant-ui's native "reasoning" part type
      return { type: "reasoning" as const, text: part.thinking };
    }
    return part;
  });

  return {
    id: message.id,
    role: message.role,
    content,
    createdAt: message.createdAt,
  };
};

// -----------------------------------------------------------------------------
// Thread View (External Store Runtime)
// -----------------------------------------------------------------------------

interface ThreadViewProps {
  onSessionCreated?: () => void;
}

function ThreadView({ onSessionCreated }: ThreadViewProps) {
  // === ZUSTAND STATE ===
  const messages = useGreenhouseStore((s) => s.messages);
  const isRunning = useGreenhouseStore((s) => s.isRunning);
  const sessionId = useGreenhouseStore((s) => s.sessionId);

  // === ZUSTAND ACTIONS ===
  const addUserMessage = useGreenhouseStore((s) => s.addUserMessage);
  const addAssistantPlaceholder = useGreenhouseStore((s) => s.addAssistantPlaceholder);
  const appendToAssistant = useGreenhouseStore((s) => s.appendToAssistant);
  const appendThinking = useGreenhouseStore((s) => s.appendThinking);
  const addToolCall = useGreenhouseStore((s) => s.addToolCall);
  const updateToolResult = useGreenhouseStore((s) => s.updateToolResult);
  const setMessages = useGreenhouseStore((s) => s.setMessages);
  const setSessionId = useGreenhouseStore((s) => s.setSessionId);
  const setRunning = useGreenhouseStore((s) => s.setRunning);

  // === onNew: Handle new user messages ===
  const onNew = useCallback(
    async (appendMessage: AppendMessage) => {
      // Extract text content from the message
      const textParts = appendMessage.content.filter(
        (p): p is { type: "text"; text: string } => p.type === "text"
      );
      const text = textParts.map((p) => p.text).join("\n");

      // Extract image attachments - these are in appendMessage.attachments, not content!
      // SimpleImageAttachmentAdapter puts images there as CompleteAttachment objects
      const attachments = appendMessage.attachments || [];
      const imageAttachments = attachments.filter(
        (a): a is { type: "image"; name: string; contentType: string; file?: File; content: string } =>
          a.type === "image" && "content" in a
      );

      if (!text.trim() && imageAttachments.length === 0) return;

      console.log("[Greenhouse] onNew called, text length:", text.length, "images:", imageAttachments.length);

      // 1. Add user message to store immediately (optimistic)
      // Convert attachments to our store format
      // att.content is an array like [{ type: "image", image: "data:..." }]
      const storeAttachments = imageAttachments.flatMap(a => {
        if (Array.isArray(a.content)) {
          return a.content
            .filter((c): c is { type: "image"; image: string } => c.type === "image" && "image" in c)
            .map(c => ({ type: "image" as const, image: c.image }));
        }
        return [];
      });
      addUserMessage(text, storeAttachments);

      // 2. Create placeholder for assistant response
      const assistantId = addAssistantPlaceholder();
      setRunning(true);

      // Build content for backend (Claude API format)
      const backendContent: Array<{ type: string; text?: string; source?: { type: string; media_type: string; data: string } }> = [];
      if (text.trim()) {
        backendContent.push({ type: "text", text });
      }
      for (const att of imageAttachments) {
        // att.content is an array like [{ type: "image", image: "data:image/jpeg;base64,..." }]
        if (Array.isArray(att.content)) {
          for (const contentPart of att.content) {
            if (contentPart.type === "image" && "image" in contentPart) {
              const dataUrl = contentPart.image as string;
              if (dataUrl.startsWith("data:")) {
                const [header, data] = dataUrl.split(",");
                const mediaType = header.split(":")[1].split(";")[0];
                backendContent.push({
                  type: "image",
                  source: {
                    type: "base64",
                    media_type: mediaType,
                    data: data,
                  },
                });
              }
            }
          }
        }
      }

      try {
        // 3. Call backend with content (text + images)
        console.log("[Greenhouse] Starting fetch to /api/chat...");
        const response = await fetch("/api/chat", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            sessionId,
            content: backendContent.length === 1 && backendContent[0].type === "text"
              ? text  // Simple string for text-only
              : backendContent,  // Array for multimodal
          }),
        });
        console.log("[Greenhouse] Fetch completed, status:", response.status);

        if (!response.ok) {
          throw new Error(`API error: ${response.status}`);
        }

        // 4. Stream response
        const reader = response.body?.getReader();
        if (!reader) {
          throw new Error("No response body");
        }
        console.log("[Greenhouse] Got reader, starting SSE stream...");

        for await (const event of readSSEStream(reader)) {
          // Only log non-delta events to avoid spam
          if (event.type !== "text-delta") {
            console.log("[Greenhouse] SSE event:", event.type);
          }
          switch (event.type) {
            case "thinking-delta":
              // Extended thinking — stream into collapsible thinking block
              appendThinking(assistantId, event.data as string);
              break;

            case "text-delta":
              // Real-time streaming! Append each chunk as it arrives
              appendToAssistant(assistantId, event.data as string);
              break;

            case "text":
              // Fallback for complete text blocks (shouldn't happen often with streaming)
              appendToAssistant(assistantId, event.data as string);
              break;

            case "tool-call": {
              const tc = event.data as ToolCallPart;
              addToolCall(assistantId, {
                toolCallId: tc.toolCallId,
                toolName: tc.toolName,
                args: tc.args,
                argsText: tc.argsText,
              });
              break;
            }

            case "tool-result": {
              const { toolCallId, result, isError } = event.data as {
                toolCallId: string;
                result: JSONValue;
                isError?: boolean;
              };
              updateToolResult(assistantId, toolCallId, result, isError);
              break;
            }

            case "session-id":
              setSessionId(event.data as string);
              // Notify parent so sidebar refreshes
              if (onSessionCreated) {
                onSessionCreated();
              }
              break;

            case "context":
              // No context meter in Rosemary — ignore
              break;

            case "error":
              console.error("[Greenhouse] Stream error:", event.data);
              break;

            case "archive-error":
              // Scribe archiving failed - alert the user
              console.error("[Greenhouse] Archive failed:", event.data);
              window.alert(`Warning: Message archiving failed: ${event.data}`);
              break;

            case "done":
              // Stream complete
              console.log("[Greenhouse] Stream complete (done event)");
              break;
          }
        }
        console.log("[Greenhouse] Exited SSE loop");
      } catch (error) {
        console.error("[Greenhouse] Chat error:", error);
        // Update placeholder with error message
        appendToAssistant(
          assistantId,
          `Error: ${error instanceof Error ? error.message : "Unknown error"}`
        );
      } finally {
        console.log("[Greenhouse] Finally block, setting isRunning=false");
        setRunning(false);
      }
    },
    [
      sessionId,
      addUserMessage,
      addAssistantPlaceholder,
      appendToAssistant,
      appendThinking,
      addToolCall,
      updateToolResult,
      setSessionId,
      setRunning,
      onSessionCreated,
    ]
  );

  // === RUNTIME ===
  const runtime = useExternalStoreRuntime({
    messages,
    setMessages,
    isRunning,
    onNew,
    convertMessage,
    adapters: {
      attachments: new SimpleImageAttachmentAdapter(),
    },
  });

  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <div className="h-full flex flex-col bg-background">
        {/* Thread */}
        <ThreadPrimitive.Root className="flex-1 flex flex-col overflow-hidden">
          <ThreadPrimitive.Viewport className="flex-1 flex flex-col overflow-y-scroll p-6">
            <div className="max-w-3xl mx-auto w-full flex-1">
              {/* Empty state */}
              {messages.length === 0 && !isRunning && (
                <div className="flex-1 flex items-center justify-center h-full">
                  <p className="text-muted text-xl">How can I help you today?</p>
                </div>
              )}

              <ThreadPrimitive.Messages
                components={{
                  UserMessage,
                  AssistantMessage,
                }}
              />

              {/* Thinking indicator — only shows when running */}
              <AssistantIf condition={({ thread }) => thread.isRunning}>
                <div
                  className="flex items-center gap-2 px-2 py-3 text-muted italic"
                  style={{ fontSize: `${14 * fontScale}px` }}
                >
                  <span className="inline-block w-2 h-2 bg-primary rounded-full animate-pulse-dot" />
                  Rosemary is thinking...
                </div>
              </AssistantIf>
            </div>

            {/* Bottom spacer */}
            <div aria-hidden="true" className="h-4" />
          </ThreadPrimitive.Viewport>
        </ThreadPrimitive.Root>

        {/* Composer */}
        <footer className="px-6 py-4 bg-background">
          <div className="max-w-3xl mx-auto">
            <ComposerPrimitive.Root className="flex flex-col gap-3 p-4 bg-composer rounded-2xl shadow-[0_0.25rem_1.25rem_rgba(0,0,0,0.4),0_0_0_0.5px_rgba(108,106,96,0.15)]">
              {/* Attachment previews */}
              <ComposerAttachments />

              <ComposerPrimitive.Input
                placeholder="Message Rosemary..."
                className="w-full py-2 bg-transparent border-none text-text outline-none resize-none"
                style={{ fontSize: `${16 * fontScale}px` }}
              />
              <div className="flex justify-end items-center gap-3">
                {/* Add attachment button */}
                <ComposerAddAttachment />

                {/* Send button (shown when not running) */}
                <AssistantIf condition={({ thread }) => !thread.isRunning}>
                  <ComposerPrimitive.Send className="w-9 h-9 flex items-center justify-center bg-primary border-none rounded-lg text-white cursor-pointer">
                    <ArrowUp size={20} strokeWidth={2.5} />
                  </ComposerPrimitive.Send>
                </AssistantIf>

                {/* Cancel button (shown when running) */}
                <AssistantIf condition={({ thread }) => thread.isRunning}>
                  <ComposerPrimitive.Cancel className="w-9 h-9 flex items-center justify-center bg-primary border-none rounded-lg text-white cursor-pointer">
                    <Square size={16} fill="white" />
                  </ComposerPrimitive.Cancel>
                </AssistantIf>
              </div>
            </ComposerPrimitive.Root>
            <p
              className="text-right text-muted mt-2"
              style={{ fontSize: `${11 * fontScale}px` }}
            >
              Rosemary can make mistakes. Please double-check responses.
            </p>
          </div>
        </footer>
      </div>
    </AssistantRuntimeProvider>
  );
}

// -----------------------------------------------------------------------------
// ChatPage (route handler)
// -----------------------------------------------------------------------------

interface ChatPageProps {
  onSessionCreated?: () => void;
}

export default function ChatPage({ onSessionCreated }: ChatPageProps) {
  const { sessionId } = useParams();
  const navigate = useNavigate();
  const loadSession = useGreenhouseStore((s) => s.loadSession);
  const reset = useGreenhouseStore((s) => s.reset);

  // Load state
  const [loading, setLoading] = useState(!!sessionId);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (sessionId) {
      // Load existing session
      fetch(`/api/sessions/${sessionId}`)
        .then((r) => {
          if (!r.ok) throw new Error(`Session not found`);
          return r.json();
        })
        .then((data) => {
          // Convert backend messages to our format
          const messages: Message[] = (data.messages || []).map(
            (m: { role: string; content: unknown }, i: number) => ({
              id: `loaded-${i}`,
              role: m.role as "user" | "assistant",
              content: Array.isArray(m.content)
                ? m.content
                : [{ type: "text", text: String(m.content) }],
              createdAt: new Date(),
            })
          );
          loadSession(sessionId, messages);
          setLoading(false);
        })
        .catch((err) => {
          setError(err.message);
          setLoading(false);
        });
    } else {
      // New session - reset store
      reset();
      setLoading(false);
    }
  }, [sessionId, loadSession, reset]);

  if (loading) {
    return (
      <div className="h-full flex items-center justify-center bg-background text-muted">
        Loading session...
      </div>
    );
  }

  if (error) {
    return (
      <div className="h-full flex flex-col items-center justify-center bg-background gap-4">
        <div className="text-primary">{error}</div>
        <button
          onClick={() => navigate("/chat")}
          className="px-6 py-3 bg-composer border border-border rounded-lg text-text cursor-pointer"
        >
          New Chat
        </button>
      </div>
    );
  }

  return <ThreadView onSessionCreated={onSessionCreated} />;
}
