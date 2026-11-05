import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode, Suspense, lazy, type ReactNode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { Layout } from "./components/Layout";
import { Skeleton, ToastProvider } from "./components/ui";
import { RunProvider } from "./lib/hooks";
import { Queue } from "./pages/Queue";
import { Reviews } from "./pages/Reviews";
import { Runs } from "./pages/Runs";
import "./index.css";

// Chart-heavy pages load recharts on demand.
const Overview = lazy(() => import("./pages/Overview").then((m) => ({ default: m.Overview })));
const Benchmark = lazy(() => import("./pages/Benchmark").then((m) => ({ default: m.Benchmark })));
const page = (el: ReactNode) => <Suspense fallback={<Skeleton className="h-[600px]" />}>{el}</Suspense>;

const qc = new QueryClient({
  defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false } },
});

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={qc}>
      <ToastProvider>
        <BrowserRouter>
          <RunProvider>
            <Routes>
              <Route element={<Layout />}>
                <Route index element={page(<Overview />)} />
                <Route path="reviews" element={<Reviews />} />
                <Route path="queue" element={<Queue />} />
                <Route path="runs" element={<Runs />} />
                <Route path="benchmark" element={page(<Benchmark />)} />
                <Route path="*" element={<Navigate to="/" replace />} />
              </Route>
            </Routes>
          </RunProvider>
        </BrowserRouter>
      </ToastProvider>
    </QueryClientProvider>
  </StrictMode>,
);
