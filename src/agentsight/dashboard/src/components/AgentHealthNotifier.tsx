import React, { useState, useEffect, useRef, useCallback } from 'react';
import { fetchAgentProcessHealth } from '../utils/apiClient';
import { useI18n } from '../i18n';

interface Toast {
  id: number;
  message: string;
}

/**
 * AgentHealthNotifier — invisible global watcher that polls agent health and
 * raises toast notifications for crashes and hangs on every page.
 *
 * The visible health panel lives in pages/AgentHealthPage; this component only
 * keeps the cross-page alerting behavior of the former sidebar.
 */
export const AgentHealthNotifier: React.FC = () => {
  const { t } = useI18n();
  const [toasts, setToasts] = useState<Toast[]>([]);
  const toastIdRef = useRef(0);
  // Track which PIDs we've already notified about (negative PID = hung notice)
  const notifiedRef = useRef<Set<number>>(new Set());

  const addToast = useCallback((message: string) => {
    const id = ++toastIdRef.current;
    setToasts(prev => [...prev, { id, message }]);
    setTimeout(() => setToasts(prev => prev.filter(t => t.id !== id)), 5000);
  }, []);

  useEffect(() => {
    let active = true;
    let requestId = 0;
    let appliedRequestId = 0;
    const poll = async () => {
      if (!active) return;
      const currentRequestId = ++requestId;
      try {
        const data = await fetchAgentProcessHealth({ includeClients: true });
        // Keep retrying stalled requests without allowing obsolete snapshots.
        if (!active || currentRequestId < appliedRequestId) return;
        appliedRequestId = currentRequestId;
        const agents = Array.isArray(data?.agents) ? data.agents : [];

        agents.forEach(a => {
          if (a.status === 'offline' && a.has_crash && !notifiedRef.current.has(a.pid)) {
            notifiedRef.current.add(a.pid);
            addToast(t('comp.agentHealth.crashToast', { name: a.agent_name, pid: a.pid }));
          }
          if (a.status === 'hung' && !notifiedRef.current.has(-a.pid)) {
            notifiedRef.current.add(-a.pid);
            addToast(t('comp.agentHealth.hungToast', { name: a.agent_name, pid: a.pid }));
          }
        });
        const currentPids = new Set(agents.map(a => a.pid));
        notifiedRef.current.forEach(pid => {
          if (!currentPids.has(Math.abs(pid))) notifiedRef.current.delete(pid);
        });
        // Recovery ends an anomaly episode, so a later occurrence can notify.
        agents.forEach(a => {
          if (a.status !== 'hung') notifiedRef.current.delete(-a.pid);
          if (a.status !== 'offline' || !a.has_crash) notifiedRef.current.delete(a.pid);
        });
      } catch {
        // Notifications are best effort; retry on the next polling interval.
      }
    };
    void poll();
    const timer = setInterval(poll, 10_000);
    return () => {
      active = false;
      clearInterval(timer);
    };
  }, [addToast, t]);

  return (
    <div className="fixed top-4 left-1/2 -translate-x-1/2 z-50 flex flex-col items-center gap-2 pointer-events-none">
      {toasts.map(t => (
        <div
          key={t.id}
          className="bg-red-600 text-white text-sm px-5 py-3 rounded-lg shadow-xl animate-pulse pointer-events-auto"
        >
          {t.message}
        </div>
      ))}
    </div>
  );
};

export default AgentHealthNotifier;
