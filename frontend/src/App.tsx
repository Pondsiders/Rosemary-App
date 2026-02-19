import { BrowserRouter, Routes, Route, useParams, useNavigate } from "react-router-dom";
import { useState, useEffect } from "react";
import ChatPage from "./pages/ChatPage";
import { Plus, MessageSquare } from "lucide-react";

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
  const [sidebarOpen] = useState(true);

  // Fetch sessions on mount and after new session is created
  const refreshSessions = () => {
    fetch("/api/sessions")
      .then((r) => r.json())
      .then(setSessions)
      .catch(console.error);
  };

  useEffect(() => { refreshSessions(); }, [sessionId]);

  return (
    <div className="h-screen flex bg-background text-text">
      {/* Sidebar */}
      {sidebarOpen && (
        <aside className="w-64 flex-shrink-0 bg-surface border-r border-border flex flex-col">
          <div className="p-3">
            <button
              onClick={() => navigate("/chat")}
              className="w-full flex items-center gap-2 px-3 py-2.5 rounded-lg bg-transparent border border-border text-text cursor-pointer text-sm hover:bg-background/50"
            >
              <Plus size={16} />
              New chat
            </button>
          </div>
          <div className="flex-1 overflow-y-auto px-2">
            {sessions.map((s) => (
              <button
                key={s.session_id}
                onClick={() => navigate(`/chat/${s.session_id}`)}
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
      )}

      {/* Main chat area */}
      <main className="flex-1 flex flex-col min-w-0">
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
