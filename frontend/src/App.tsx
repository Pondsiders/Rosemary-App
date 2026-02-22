import { BrowserRouter, Routes, Route, useParams, useNavigate } from "react-router-dom";
import { useState, useEffect, useCallback } from "react";
import ChatPage from "./pages/ChatPage";
import { Plus, MessageSquare, Menu, PanelLeftClose } from "lucide-react";

/** Returns true when viewport is below 768px. */
function useIsMobile() {
  const [isMobile, setIsMobile] = useState(
    () => window.matchMedia("(max-width: 767px)").matches
  );
  useEffect(() => {
    const mql = window.matchMedia("(max-width: 767px)");
    const handler = (e: MediaQueryListEvent) => setIsMobile(e.matches);
    mql.addEventListener("change", handler);
    return () => mql.removeEventListener("change", handler);
  }, []);
  return isMobile;
}

// OS theme detection
function useTheme() {
  useEffect(() => {
    const mql = window.matchMedia("(prefers-color-scheme: dark)");
    const update = () => {
      document.documentElement.classList.toggle("dark", mql.matches);
    };
    update();
    mql.addEventListener("change", update);
    return () => mql.removeEventListener("change", update);
  }, []);
}

type Session = {
  session_id: string;
  title: string;
  created_at: string;
  updated_at: string;
};

function formatRelative(timestamp: string): string {
  const date = new Date(timestamp);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffMins = Math.floor(diffMs / 60000);
  const diffHours = Math.floor(diffMs / 3600000);
  const diffDays = Math.floor(diffMs / 86400000);
  if (diffMins < 1) return "just now";
  if (diffMins < 60) return `${diffMins}m ago`;
  if (diffHours < 24) return `${diffHours}h ago`;
  if (diffDays === 1) return "yesterday";
  return `${diffDays}d ago`;
}

function Layout() {
  useTheme();
  const { sessionId } = useParams();
  const navigate = useNavigate();
  const [sessions, setSessions] = useState<Session[]>([]);
  const isMobile = useIsMobile();
  const [sidebarOpen, setSidebarOpen] = useState(!isMobile);

  // Close/open sidebar when crossing the breakpoint
  useEffect(() => { setSidebarOpen(!isMobile); }, [isMobile]);

  const refreshSessions = () => {
    fetch("/api/sessions")
      .then((r) => r.json())
      .then(setSessions)
      .catch(console.error);
  };

  useEffect(() => { refreshSessions(); }, [sessionId]);

  const handleSessionClick = useCallback(
    (id: string) => {
      navigate(`/chat/${id}`);
      if (isMobile) setSidebarOpen(false);
    },
    [navigate, isMobile]
  );

  const handleNewChat = useCallback(() => {
    navigate("/chat");
    if (isMobile) setSidebarOpen(false);
  }, [navigate, isMobile]);

  const sidebar = (
    <aside
      className={`w-64 flex-shrink-0 bg-surface border-r border-border flex flex-col h-full ${
        isMobile ? "fixed inset-y-0 left-0 z-50" : ""
      }`}
      style={
        isMobile
          ? {
              transform: sidebarOpen ? "translateX(0)" : "translateX(-100%)",
              transition: "transform 200ms ease-in-out",
            }
          : undefined
      }
    >
      {/* Sidebar header with close button */}
      <div className="p-3 flex items-center gap-2">
        <button
          onClick={() => setSidebarOpen(false)}
          className="p-1.5 rounded-lg bg-transparent border-none text-muted hover:text-text hover:bg-background/50 cursor-pointer"
          aria-label="Close sidebar"
        >
          <PanelLeftClose size={18} />
        </button>
        <button
          onClick={handleNewChat}
          className="flex-1 flex items-center gap-2 px-3 py-2.5 rounded-lg bg-transparent border border-border text-text cursor-pointer text-sm hover:bg-background/50"
        >
          <Plus size={16} />
          New chat
        </button>
      </div>
      <div className="flex-1 overflow-y-auto px-2">
        {sessions.map((s) => (
          <button
            key={s.session_id}
            onClick={() => handleSessionClick(s.session_id)}
            className={`w-full flex items-center gap-2 px-3 py-2 rounded-lg text-left text-sm cursor-pointer mb-0.5 border-none ${
              sessionId === s.session_id
                ? "bg-background/80 text-text"
                : "bg-transparent text-muted hover:bg-background/30"
            }`}
          >
            <MessageSquare size={14} className="shrink-0 opacity-50" />
            <span className="flex-1 overflow-hidden text-ellipsis whitespace-nowrap">
              {s.title || "New chat"}
            </span>
            <span className="text-xs text-muted/50 shrink-0">
              {formatRelative(s.updated_at)}
            </span>
          </button>
        ))}
      </div>
    </aside>
  );

  return (
    <div className="h-screen flex bg-background text-text">
      {/* Desktop: sidebar sits inline with width transition */}
      {!isMobile && (
        <div
          className="overflow-hidden flex-shrink-0"
          style={{
            width: sidebarOpen ? "16rem" : "0",
            transition: "width 200ms ease-in-out",
          }}
        >
          {sidebar}
        </div>
      )}

      {/* Mobile: overlay sidebar + backdrop */}
      {isMobile && (
        <>
          {/* Backdrop */}
          <div
            className="fixed inset-0 z-40 bg-black/50"
            style={{
              opacity: sidebarOpen ? 1 : 0,
              pointerEvents: sidebarOpen ? "auto" : "none",
              transition: "opacity 200ms ease-in-out",
            }}
            onClick={() => setSidebarOpen(false)}
          />
          {/* Sidebar rendered always (for transition), visibility handled by transform */}
          {sidebar}
        </>
      )}

      {/* Main chat area */}
      <main className="flex-1 flex flex-col min-w-0">
        {/* Menu button to open sidebar when it's closed */}
        {!sidebarOpen && (
          <button
            onClick={() => setSidebarOpen(true)}
            className="absolute top-3 left-3 z-30 p-2 rounded-lg bg-surface border border-border text-muted hover:text-text hover:bg-background/50 cursor-pointer"
            aria-label="Open sidebar"
          >
            <Menu size={18} />
          </button>
        )}
        <ChatPage key={sessionId || "new"} onSessionCreated={refreshSessions} />
      </main>
    </div>
  );
}

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Layout />} />
        <Route path="/chat" element={<Layout />} />
        <Route path="/chat/:sessionId" element={<Layout />} />
      </Routes>
    </BrowserRouter>
  );
}

export default App;
