import { useState } from "react";
import { Navigate, Route, Routes } from "react-router-dom";

import { AppShell } from "./components";
import { api, type RuntimeMeta } from "./api";
import { DashboardPage } from "./pages/DashboardPage";
import { AboutPage } from "./pages/AboutPage";
import { EvidencePage } from "./pages/EvidencePage";
import { JobDetailPage } from "./pages/JobDetailPage";
import { JobsPage } from "./pages/JobsPage";
import { ShortlistPage } from "./pages/ShortlistPage";
import { SourcesPage } from "./pages/SourcesPage";
import { VerifyPage } from "./pages/VerifyPage";
import { ProfileDrawer } from "./ProfileDrawer";
import { RuntimeProvider } from "./RuntimeProvider";
import { defaultRuntime } from "./runtime";
import { useRemote } from "./useRemote";

export function App() {
  const [profileOpen, setProfileOpen] = useState(false);
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const runtime = useRemote(() => api<RuntimeMeta>("/api/meta"));
  const resolvedRuntime =
    runtime.data ??
    (runtime.error
      ? { ...defaultRuntime, label: "运行模式确认失败 · 只读保护" }
      : defaultRuntime);
  return (
    <RuntimeProvider value={resolvedRuntime}>
      <AppShell
        profileOpen={profileOpen}
        onProfileOpen={() => setProfileOpen(true)}
        mobileNavOpen={mobileNavOpen}
        onMobileNavToggle={() => setMobileNavOpen((value) => !value)}
        runtime={resolvedRuntime}
      >
        <Routes>
          <Route path="/about" element={<AboutPage />} />
          <Route path="/" element={<DashboardPage />} />
          <Route path="/jobs" element={<JobsPage />} />
          <Route path="/jobs/:id" element={<JobDetailPage />} />
          <Route path="/verify" element={<VerifyPage />} />
          <Route path="/sources" element={<SourcesPage />} />
          <Route path="/shortlist" element={<ShortlistPage />} />
          <Route path="/evidence" element={<EvidencePage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
        {profileOpen && <ProfileDrawer onClose={() => setProfileOpen(false)} />}
      </AppShell>
    </RuntimeProvider>
  );
}
